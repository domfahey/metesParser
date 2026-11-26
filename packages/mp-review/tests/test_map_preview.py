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
        import errno

        with pytest.raises(OSError, match="Address already in use") as exc:
            create_preview_server(root, port=port)
        assert exc.value.errno == errno.EADDRINUSE
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_preview_validation_edges_root_head_and_serve_interrupt(tmp_path, monkeypatch, capsys):
    import socket

    import mp_review.map_preview as preview_mod

    (tmp_path / "dir").mkdir()
    root = staged(tmp_path / "dir")
    # Symlink directory refused
    link_dir = tmp_path / "link"
    link_dir.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        create_preview_server(link_dir, port=8765)

    # Symlink manifest refused
    manifest_real = tmp_path / "ext-manifest.json"
    manifest_real.write_bytes((root / "web-map-manifest.json").read_bytes())
    (root / "web-map-manifest.json").unlink()
    (root / "web-map-manifest.json").symlink_to(manifest_real)
    with pytest.raises(ValueError, match="symlink"):
        create_preview_server(root, port=8765)
    (root / "web-map-manifest.json").unlink()

    # Invalid schema_version, invalid source_kind, incomplete allowlist, missing keys
    for bad_manifest, match in (
        ({"schema_version": "2.0", "files": {}}, "Invalid preview manifest"),
        ({"schema_version": "1.0", "source_kind": "unknown", "files": {}}, "source kind"),
        ({"schema_version": "1.0", "files": {"online-map.html": "0" * 64}}, "Incomplete"),
        ({"schema_version": "1.0"}, "Invalid preview manifest"),
    ):
        (root / "web-map-manifest.json").write_text(json.dumps(bad_manifest))
        with pytest.raises(ValueError, match=match):
            create_preview_server(root, port=8765)

    # Restore valid staged dir and test memory budget guard
    (tmp_path / "dir2").mkdir()
    root = staged(tmp_path / "dir2")
    monkeypatch.setattr(preview_mod, "_MAX_BYTES", 5)
    with pytest.raises(ValueError, match="memory budget"):
        create_preview_server(root, port=8765)
    monkeypatch.undo()

    # GET / resolves to /online-map.html and HEAD returns 200 with empty body
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = create_preview_server(root, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/", headers={"Host": f"localhost:{port}"})
        resp = conn.getresponse()
        assert resp.status == 200 and resp.read() == b"<html>online</html>"
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("HEAD", "/online-map.html", headers={"Host": f"localhost:{port}"})
        resp = conn.getresponse()
        assert resp.status == 200 and resp.read() == b""
        assert resp.getheader("Content-Length") == str(len(b"<html>online</html>"))
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    # serve_map_preview prints URL and handles KeyboardInterrupt cleanly
    class FakeServer:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(preview_mod, "create_preview_server", lambda d, port=8765: FakeServer())
    preview_mod.serve_map_preview(root, port=9123)
    assert "http://localhost:9123/online-map.html" in capsys.readouterr().out
