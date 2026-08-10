"""Hosted mode: the shared coordination server.

Runs on Render. Each developer keeps their own clone and their own agent on
their own subscription; only the event stream meets here. Source code never
reaches this process. What does reach it is file paths, interface signatures
and findings, which is a real disclosure and is stated in PRD-B rather than
glossed over.

Stdlib only, so the same server runs offline on a laptop with no install step.
Binds 0.0.0.0 on $PORT, which is what Render requires.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import fileshare
from .eventlog import EventLog

HERE = Path(__file__).parent
PAGE = HERE / "page.html"

# A shared room is identified by a name; each room has its own log.
_rooms: dict[str, EventLog] = {}
_rooms_lock = threading.Lock()

DATA_DIR = Path(os.environ.get("IRUS_DATA_DIR", ".irus/rooms"))
TOKEN = os.environ.get("IRUS_TOKEN", "")

# The repository the host is sharing, and whether they agreed to share it at
# all. None means file sharing is off, which is the default: a room must never
# expose a filesystem because somebody merely started it.
SHARE_ROOT: Path | None = None


def room(name: str) -> EventLog:
    name = "".join(c for c in name if c.isalnum() or c in "-_")[:64] or "default"
    with _rooms_lock:
        if name not in _rooms:
            _rooms[name] = EventLog(DATA_DIR / f"{name}.jsonl")
        return _rooms[name]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "irus"

    # ---- helpers ---------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: object) -> None:
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def _authorised(self) -> bool:
        """A write token is required only when one is configured.

        Local use stays frictionless; a public deployment sets IRUS_TOKEN and
        every write must present it.
        """
        if not TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        return secrets.compare_digest(header, f"Bearer {TOKEN}")

    def log_message(self, fmt: str, *args: object) -> None:  # quieter logs
        return

    # ---- routes ----------------------------------------------------------
    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        name = (query.get("room") or ["default"])[0]

        if url.path == "/health":
            self._json(200, {"ok": True, "service": "irus", "rooms": len(_rooms)})
            return

        if url.path in ("/", "/index.html"):
            if PAGE.exists():
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(200, b"<h1>irus</h1><p>page.html missing</p>", "text/html")
            return

        if url.path == "/fs/list":
            if not self._file_sharing_allowed():
                return
            entries = fileshare.listing(SHARE_ROOT)  # type: ignore[arg-type]
            self._json(200, {"files": [{"path": e.path, "bytes": e.bytes} for e in entries]})
            return

        if url.path == "/fs/read":
            if not self._file_sharing_allowed():
                return
            rel = (query.get("path") or [""])[0]
            try:
                self._json(200, {"path": rel, "content": fileshare.read(SHARE_ROOT, rel)})
            except fileshare.FileShareError as exc:
                self._json(400, {"error": str(exc)})
            return

        if url.path == "/state":
            self._json(200, {"room": name, "events": room(name).replay()})
            return

        if url.path == "/events":
            since = int((query.get("since") or ["0"])[0] or 0)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                for event in room(name).stream(since):
                    payload = json.dumps(event, default=str)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            return

        self._json(404, {"error": "not found"})

    def _file_sharing_allowed(self) -> bool:
        """File sharing needs the host's opt-in and the guest's token, always.

        Findings are harmless to read; source is not, so the token is required
        for reads here even though /state does not require one.
        """
        if SHARE_ROOT is None:
            self._json(404, {"error": "this room is not sharing files"})
            return False
        if not self._authorised():
            self._json(401, {"error": "file access requires the room token"})
            return False
        return True

    def do_POST(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        name = (query.get("room") or ["default"])[0]

        if url.path == "/fs/write":
            if not self._file_sharing_allowed():
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                written = fileshare.write(
                    SHARE_ROOT, str(body.get("path", "")), str(body.get("content", ""))
                )
            except fileshare.FileShareError as exc:
                self._json(400, {"error": str(exc)})
                return
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            self._json(200, {"path": body.get("path"), "bytes": written})
            return

        if url.path != "/ingest":
            self._json(404, {"error": "not found"})
            return
        if not self._authorised():
            self._json(401, {"error": "unauthorised"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            self._json(413, {"error": "payload too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        events = body if isinstance(body, list) else [body]
        log = room(name)
        written = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = str(event.pop("kind", "")) or "unknown"
            event.pop("t", None)
            event.pop("seq", None)
            log.append(kind, **event)
            written += 1
        self._json(200, {"accepted": written, "room": name, "total": len(log)})


def serve(port: int | None = None, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    # `port or default` was wrong: 0 is falsy, and 0 is precisely how a caller
    # asks the OS for a free port. Only None means "use the default".
    if port is None:
        port = int(os.environ.get("PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def main() -> None:
    httpd = serve()
    host, port = httpd.server_address[:2]
    print(f"irus listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
