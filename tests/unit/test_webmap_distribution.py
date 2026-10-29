"""Executable launcher boundary coverage; full extracted-wheel smoke is separate."""

import hashlib
import http.client
import json
import os
import selectors
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_plugin_launcher_streams_preview_url_while_server_is_alive(tmp_path):
    """Exercise actual launcher, CLI, and HTTP server without dependency downloads.

    The uv executable shim replaces only environment bootstrapping. The engine
    process and launcher use their real entrypoints, so captured subprocess output
    would deadlock this test before the URL becomes readable. The CLI reserves
    stdout for its final JSON result and streams the URL on stderr.
    """
    plugin = tmp_path / "plugin"
    scripts = plugin / "scripts"
    scripts.mkdir(parents=True)
    launcher = scripts / "run-review.py"
    shutil.copyfile(ROOT / "plugins/metesparser/scripts/run-review.py", launcher)
    runtime = plugin / "runtime"
    runtime.mkdir()
    hashes = {}
    for name, content in (("pyproject.toml", b"[project]\n"), ("uv.lock", b"version = 1\n")):
        (runtime / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    (runtime / "engine.json").write_text(json.dumps({"fingerprint": fingerprint, "sha256": hashes}))
    binary = tmp_path / "bin"
    binary.mkdir()
    shim = binary / "uv"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import os,sys\n"
        "arguments=sys.argv[sys.argv.index('--')+1:]\n"
        "assert arguments[:3]==['python','-m','mp_review']\n"
        "os.execv(sys.executable,[sys.executable,*arguments[1:]])\n"
    )
    shim.chmod(0o755)
    output = tmp_path / "display"
    output.mkdir()
    files = {}
    for name, content in (
        ("online-map.html", b"<html>online</html>"),
        ("dashboard.html", b"<html>offline</html>"),
    ):
        (output / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()
    (output / "source.json").write_text("private source")
    (output / "web-map-manifest.json").write_text(
        json.dumps({"schema_version": "1.0", "files": files})
    )
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    env = dict(os.environ)
    env["PATH"] = str(binary) + os.pathsep + env["PATH"]
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    process = subprocess.Popen(
        [sys.executable, str(launcher), "serve-map", str(output), "--port", str(port)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        assert process.stderr is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stderr, selectors.EVENT_READ)
            assert selector.select(timeout=10), "Preview URL was buffered while the server ran"
        line = process.stderr.readline().strip()
        assert line == f"Map preview: http://localhost:{port}/online-map.html"
        assert process.poll() is None, "URL must arrive before the preview exits"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("GET", "/online-map.html", headers={"Host": f"localhost:{port}"})
            response = connection.getresponse()
            assert response.status == 200
            assert response.getheader("Referrer-Policy") == "strict-origin"
            assert response.read() == b"<html>online</html>"
        finally:
            connection.close()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "Preview left an orphan listener"
