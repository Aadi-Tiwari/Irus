"""The demo runner: replay a recorded log into a live page.

PRD-B section 6. Ninety seconds, structure fixed.

    B-R34  Replay only, never a live agent.
    B-R38  The entire demo runs with wifi off and the laptop unplugged.
    B-R39  The canvas starts empty and gains exactly one red arc at the moment
           the second agent finishes.

And the rule this file enforces rather than merely documents:

    B-R26  Never plant a bug and present it as found.

A source log recorded from a tree carrying a SYNTHETIC marker will not play
without `--synthetic-ok`, and when it does play it prints a banner. There is no
flag combination that makes a synthetic fixture look like a real finding.

    python tools/demo.py fixtures/session.jsonl
"""

from __future__ import annotations

import sys
# Windows consoles default to cp1252 and this banner is not cp1252, which
# crashed the tool on the one platform it was most likely to be demoed on.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

import argparse
import json
import threading
import shutil
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irus.eventlog import EventLog                  # noqa: E402
from irus.web import serve                          # noqa: E402

BIND_HOST = "127.0.0.1"

BANNER = """
┌──────────────────────────────────────────────────────────────────────────┐
│  SYNTHETIC FIXTURE — the mismatch below was authored by hand, not found.  │
│  Per B-R26 this must not be presented as a discovered bug. It is here to  │
│  exercise the code path. Gate B (three real reproduced mismatches) is     │
│  still unresolved; see fixtures/README.md.                                │
└──────────────────────────────────────────────────────────────────────────┘
"""


def is_synthetic(log_path: Path) -> bool:
    """A log is synthetic if its own session event says so. The claim travels
    inside the recording, so it cannot be lost by copying the file."""
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("kind") == "session" and event.get("synthetic"):
            return True
    return False


def play(source: Path, target: Path, *, speed: float, port: int, open_browser: bool) -> int:
    events = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not events:
        print("demo: source log is empty", file=sys.stderr)
        return 2

    # Start from an empty canvas every time (B-R39). A leftover log from the
    # last rehearsal is the single most likely way the demo opens wrong.
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    # The merged server serves rooms out of a data directory rather than a
    # single log path, so point the default room at the replay target.
    from irus import web

    web.DATA_DIR = target.parent
    web._rooms.clear()
    web._rooms["default"] = EventLog(target)
    httpd = serve(port=port, host=BIND_HOST)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://{BIND_HOST}:{port}/"
    print(f"demo: serving {url}")
    print("demo: canvas is empty. Press Enter to begin the replay.")
    if open_browser:
        webbrowser.open(url)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass

    log = web._rooms["default"]
    base = events[0]["t"]
    previous = 0.0
    try:
        for event in events:
            delay = ((event["t"] - base) - previous) / speed
            if delay > 0:
                time.sleep(min(delay, 4.0))     # never stall the room on a gap
            previous = event["t"] - base
            if event["kind"] == "proof":
                # The twist (B-R36): proof waits for a keypress so "no model
                # anywhere in this" lands before the app confirms it.
                print("demo: press Enter to run the execution proof.")
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
                previous = event["t"] - base
            log.append_raw(event)
            if event["kind"] == "finding" and event.get("confidence") == "high":
                print(f"demo: red arc — {event['seam']}: {event['detail']}")
        print("demo: replay complete. Ctrl-C to stop the server.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\ndemo: stopped")
    finally:
        httpd.shutdown()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a recorded Irus session.")
    parser.add_argument("source", help="recorded log to replay")
    parser.add_argument("--target", default=".irus/demo.jsonl", help="log the page reads")
    parser.add_argument("--speed", type=float, default=12.0, help="replay speed multiplier")
    parser.add_argument("--port", type=int, default=7345)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--synthetic-ok", action="store_true",
                        help="acknowledge that the fixture is authored, not found (B-R26)")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    if not source.is_file():
        print(f"demo: no such log: {source}", file=sys.stderr)
        return 2

    if is_synthetic(source):
        if not args.synthetic_ok:
            print(BANNER, file=sys.stderr)
            print("demo: refusing to replay a synthetic fixture without --synthetic-ok (B-R26).",
                  file=sys.stderr)
            print("demo: this is not a switch to flip before going on stage. Record a real "
                  "session and resolve Gate B first.", file=sys.stderr)
            return 3
        print(BANNER)

    return play(source, Path(args.target).resolve(), speed=args.speed,
                port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
