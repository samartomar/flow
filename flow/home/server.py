"""Flow Home's HTTP server: 127.0.0.1 only, one token per launch, and a fixed set of files.

A local port is reachable by every web page the user has open — a page on any site can
ask its browser to POST to `http://127.0.0.1:<port>/…`. So this server trusts nothing it
can be sent by accident, and three checks stand in front of every API call:

- **Host** must be this server's own `127.0.0.1:<port>` (or `localhost:<port>`). A DNS
  rebinding attack arrives with the attacker's host name here, which is what this stops.
- **Origin**, when a browser sends one, must be this server's own. A cross-site `fetch`
  always carries one.
- **The token**, a fresh random value per launch, must be in the `X-Flow-Token` header.
  Only the window Flow opened was given it (in the URL fragment, which never reaches a
  server). A custom header also forces a CORS preflight for any cross-site caller, and
  this server answers none — so the request is never sent.

POST bodies must be `application/json` for the same preflight reason, and are capped.
Nothing is served from a directory: `FILES` is the complete list of paths that return
anything but 404, so no spelling of a path can reach another file on the machine.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
FONTS = HERE.parent / "assets" / "fonts"

#: Every path that serves a file, and the file. Nothing else does.
FILES: dict[str, tuple[Path, str]] = {
    "/": (STATIC / "index.html", "text/html; charset=utf-8"),
    "/app.css": (STATIC / "app.css", "text/css; charset=utf-8"),
    "/app.js": (STATIC / "app.js", "text/javascript; charset=utf-8"),
    **{f"/fonts/{name}": (FONTS / name, "font/ttf") for name in (
        "IBMPlexSans-Regular.ttf", "IBMPlexSans-Medium.ttf", "IBMPlexSans-SemiBold.ttf",
        "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf",
    )},
}

#: The largest request body accepted. Every setting is a few hundred bytes.
MAX_BODY = 64 * 1024

#: Sent on every response. The policy allows the page's own files and nothing else: no
#: inline script, no remote fonts, no framing by another site.
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}

#: What a window from an earlier launch is told. Its token died with that process.
STALE = "this window belongs to a Flow that has quit - open Flow Home again from the pill"


class HomeServer(ThreadingHTTPServer):
    """The server. `handle(method, path, body) -> (status, payload)` answers the API."""

    daemon_threads = True

    def __init__(self, handle, token: str | None = None) -> None:
        self.handle_api = handle
        self.token = token or secrets.token_urlsafe(32)
        #: Monotonic time of the last authenticated API call: a Home window polls every
        #: second or so, so a recent one means a window is open. See `connected`.
        self.last_seen = 0.0
        super().__init__(("127.0.0.1", 0), _Handler)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, daemon=True,
                                        name="flow-home")
        self._thread.start()

    def stop(self) -> None:
        try:
            self.shutdown()
        finally:
            self.server_close()

    def connected(self, within: float = 3.0) -> bool:
        """Whether a Home window has polled recently — that is, whether one is open."""
        return self.last_seen > 0 and time.monotonic() - self.last_seen < within


class _Handler(BaseHTTPRequestHandler):
    server: HomeServer
    protocol_version = "HTTP/1.1"
    server_version = "FlowHome"
    sys_version = ""

    def log_message(self, *_args) -> None:
        # The console is Flow's own startup log; a line per poll would bury it.
        pass

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_HEAD(self) -> None:
        self._route("GET")

    # -- the checks ----------------------------------------------------------

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        return host in (f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in (
            self.server.origin, f"http://localhost:{self.server.port}")

    def _token_ok(self) -> bool:
        got = self.headers.get("X-Flow-Token", "")
        return hmac.compare_digest(got.encode("utf-8", "replace"),
                                   self.server.token.encode("utf-8"))

    # -- the answers ---------------------------------------------------------

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        for key, value in HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if status >= 400:
            # A refusal may not have read the body it refused, and on a kept-alive
            # connection those unread bytes would be parsed as the next request.
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict | None:
        """The JSON object a POST carried, or None when it is not one."""
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length < 0 or length > MAX_BODY:
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    def _route(self, method: str) -> None:
        if not self._host_ok():
            self._json(421, {"error": "wrong host"})
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            if not self._origin_ok():
                self._json(403, {"error": "not from Flow Home"})
                return
            if not self._token_ok():
                self._json(401, {"error": STALE})
                return
            body: dict = {}
            if method == "POST":
                parsed = self._body()
                if parsed is None:
                    self._json(400, {"error": "expected a JSON object"})
                    return
                body = parsed
            self.server.last_seen = time.monotonic()
            status, payload = self.server.handle_api(method, path, body)
            self._json(status, payload)
            return
        if method != "GET":
            self._json(405, {"error": "not here"})
            return
        entry = FILES.get(path)
        if entry is None:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        file, ctype = entry
        try:
            data = file.read_bytes()
        except OSError:
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(200, data, ctype)
