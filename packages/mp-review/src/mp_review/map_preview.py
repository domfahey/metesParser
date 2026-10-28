"""Read-only loopback preview of a hash-validated display-file allowlist."""

from __future__ import annotations

import hashlib
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .relative import _invalid_number, _unique_object

_DISPLAY_PATH = re.compile(r"web-map-assets/[A-Za-z][A-Za-z0-9_.-]*\.png\Z")
_MAX_BYTES = 256 * 1024 * 1024


def _display_files(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink():
        raise ValueError("Preview directory must not be a symlink")
    root = directory.resolve(strict=True)
    manifest_path = root / "web-map-manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Invalid preview manifest or symlink")
    try:
        manifest = json.loads(
            manifest_path.read_bytes(),
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_number,
        )
        files = manifest["files"]
        source_kind = manifest.get("source_kind", "dashboard")
        if manifest["schema_version"] != "1.0" or not isinstance(files, dict):
            raise ValueError("Invalid preview manifest")
        if source_kind == "dashboard":
            required_html = {"online-map.html", "dashboard.html"}
            allowed_html = required_html
        elif source_kind == "standalone":
            required_html = {"online-map.html", "map-evidence.html"}
            allowed_html = required_html
        else:
            raise ValueError("Invalid preview source kind")
        if not required_html.issubset(files) or len(files) > 1024:
            raise ValueError("Incomplete preview allowlist")
    except (KeyError, TypeError, UnicodeError) as exc:
        raise ValueError("Invalid preview manifest") from exc
    result: dict[str, bytes] = {}
    total = 0
    for name, digest in files.items():
        if name not in allowed_html and not _DISPLAY_PATH.fullmatch(name):
            raise ValueError("Unexpected file in preview allowlist")
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError("Preview file must not be a symlink")
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError("Preview file is not a regular file within the output directory")
        total += path.stat().st_size
        if total > _MAX_BYTES:
            raise ValueError("Preview files exceed the display memory budget")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Preview file hash mismatch")
        result["/" + name] = data
    return result


def create_preview_server(directory: Path | str, *, port: int = 8765) -> ThreadingHTTPServer:
    """Validate files once, then serve immutable bytes on an explicit loopback port."""
    if isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("Preview port must be between 1 and 65535")
    files = _display_files(Path(directory))
    expected_host = f"localhost:{port}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # Request URLs can contain credentials; never log them.

        def _respond(self, *, head: bool = False) -> None:
            if self.headers.get_all("Host") != [expected_host]:
                self.send_error(403, "Use the advertised localhost origin")
                return
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if (
                parsed.scheme
                or parsed.netloc
                or parsed.query
                or parsed.fragment
                or "%" in path
                or ".." in path.split("/")
            ):
                self.send_error(400, "Invalid display path")
                return
            if path == "/":
                path = "/online-map.html"
            data = files.get(path)
            if data is None:
                self.send_error(404, "Display file unavailable")
                return
            self.send_response(200)
            self.send_header(
                "Content-Type", "image/png" if path.endswith(".png") else "text/html; charset=utf-8"
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Referrer-Policy", "strict-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not head:
                self.wfile.write(data)

        def do_GET(self) -> None:
            self._respond()

        def do_HEAD(self) -> None:
            self._respond(head=True)

        def do_POST(self) -> None:
            self.send_error(405, "Read-only preview")

        do_PUT = do_POST
        do_DELETE = do_POST
        do_PATCH = do_POST

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve_map_preview(directory: Path | str, *, port: int = 8765) -> None:
    """Print the stable origin immediately and keep the preview in the foreground."""
    with create_preview_server(directory, port=port) as server:
        print(f"Map preview: http://localhost:{port}/online-map.html", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
