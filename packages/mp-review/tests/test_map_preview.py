"""Preview serves only hashed display files over an explicit loopback origin."""

import hashlib
import http.client
import json
import threading

import pytest
from mp_review.map_preview import create_preview_server


def staged(tmp_path):
    files = {}
    for name, content in (
        ("online-map.html", b"<html>online</html>"),
        ("dashboard.html", b"<html>offline</html>"),
    ):
        (tmp_path / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()
    (tmp_path / "web-map-manifest.json").write_text(
        json.dumps({"schema_version": "1.0", "files": files})
    )
    (tmp_path / "source.json").write_text("private source")
    return tmp_path


def test_preview_rejects_zero_port_and_tampered_files(tmp_path):
    root = staged(tmp_path)
    with pytest.raises(ValueError, match="port"):
        create_preview_server(root, port=0)
    (root / "online-map.html").write_text("tampered")
    with pytest.raises(ValueError, match="hash"):
        create_preview_server(root, port=8765)


def test_preview_rejects_symlinks_and_unexpected_manifest_paths(tmp_path):
    root = staged(tmp_path)
    (root / "online-map.html").unlink()
    (root / "online-map.html").symlink_to(root / "dashboard.html")
    with pytest.raises(ValueError, match="symlink"):
        create_preview_server(root, port=8765)
    (root / "online-map.html").unlink()
    staged(root)
    manifest = json.loads((root / "web-map-manifest.json").read_text())
    manifest["files"]["source.json"] = hashlib.sha256(b"private source").hexdigest()
    (root / "web-map-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="allowlist"):
        create_preview_server(root, port=8765)


def test_preview_http_host_paths_headers_and_no_file_changes(tmp_path):
    root = staged(tmp_path)
    # Reserve an explicit available port for this test; production never chooses a port.
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = create_preview_server(root, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:

        def request(path, host=None, method="GET"):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            connection.request(method, path, headers={"Host": host or f"localhost:{port}"})
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
            connection.close()
            return result

        status, headers, body = request("/online-map.html")
        assert status == 200 and body == b"<html>online</html>"
        assert headers["Referrer-Policy"] == "strict-origin"
        assert headers["Content-Type"].startswith("text/html")
        for path in (
            "/source.json",
            "/web-map-manifest.json",
            "/../source.json",
            "/%2e%2e/source.json",
            "/online-map.html?token=private",
        ):
            assert request(path)[0] in (400, 404)
        assert request("/online-map.html", host="example.com")[0] == 403
        assert request("/online-map.html", method="POST")[0] == 405
        with pytest.raises(OSError):
            create_preview_server(root, port=port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
