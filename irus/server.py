"""The local server: `http.server` plus server-sent events.

    B-R5   Functions with no network connection. No CDN, no telemetry, no
           accounts, no hosted service.
    B-R7   No source code, file contents, or repository data leaves the machine
           under any configuration.
    B-R4   Replaying the event log from the start reconstructs identical state,
           so a browser refresh is idempotent.

The bind address is hardcoded to loopback and there is no flag to change it.
B-R7 says "under any configuration"; the way to mean that is to not offer the
configuration. SSE rather than websockets for the reason in the build plan:
there is no handshake to debug at 2am the night before.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .events import EventLog

BIND_HOST = "127.0.0.1"      # not configurable, by design (B-R7)
PAGE = Path(__file__).parent / "page" / "index.html"

# Sentinels wrapping the replay so the client can reset to an empty state and
# render once at the end rather than once per historical event.
REPLAY_START = {"t": 0, "kind": "__replay_start"}
REPLAY_END = {"t": 0, "kind": "__replay_end"}


class _Handler(BaseHTTPRequestHandler):
    server_version = "irus"
    protocol_version = "HTTP/1.1"

    # Injected by `serve`.
    log_path: Path = Path("irus.jsonl")
    poll_interval: float = 0.25
    quiet: bool = True

    def log_message(self, fmt: str, *args) -> None:
        if not self.quiet:
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------ GET

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_page()
        elif path == "/events":
            self._serve_events()
        elif path == "/log":
            self._serve_log()
        else:
            self.send_error(404)

    def _serve_page(self) -> None:
        try:
            body = PAGE.read_bytes()
        except OSError:
            self.send_error(500, "page missing")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Nothing here may reach out. The CSP is belt-and-braces on top of the
        # fact that the file contains no external reference (B-R5).
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_log(self) -> None:
        """The raw log, for `curl`. Same bytes as the file — there is no second
        format (B-R23)."""
        try:
            body = self.log_path.read_bytes() if self.log_path.exists() else b""
        except OSError:
            body = b""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        log = EventLog(self.log_path)

        def emit(payload: dict) -> None:
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
            self.wfile.flush()

        try:
            # Replay on connect. This is the whole answer to "SSE drops when
            # the laptop sleeps" — the client never needs to have been present
            # for an event to end up in the right state.
            emit(REPLAY_START)
            offset = 0
            events, offset = log.tail(0)
            for event in events:
                emit(event)
            emit(REPLAY_END)

            last_ping = time.monotonic()
            while True:
                events, offset = log.tail(offset)
                for event in events:
                    emit(event)
                now = time.monotonic()
                if now - last_ping > 15:
                    # A comment frame keeps proxies and sleeping sockets honest
                    # without adding a fake event to the stream.
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = now
                time.sleep(self.poll_interval)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return          # the tab closed; entirely normal


def serve(log_path: str | Path, port: int = 7345, *, quiet: bool = True) -> ThreadingHTTPServer:
    """Start the server on loopback and return it. Caller owns the lifetime."""
    handler = type("Handler", (_Handler,), {"log_path": Path(log_path), "quiet": quiet})
    httpd = ThreadingHTTPServer((BIND_HOST, port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd
