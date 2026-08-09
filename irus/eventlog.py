"""A-R18 (and B-R21, B-R22, B-R23): the append-only event log.

This is the only state that matters. The page, the receipts, the demo recording
and the test fixtures are all derived from it, and there is no second format.

Append-only is enforced rather than merely intended: there is no method that
rewrites or deletes, and readers tolerate unknown event kinds so an older
reader never crashes on a newer writer.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Iterator

KINDS = {"baseline", "claim", "release", "surface", "finding", "proof", "receipt", "round"}


class AppendOnlyViolation(Exception):
    """Something tried to write the log in a way that could lose history.

    Adopted from the Part B branch: B-R21 is enforced here rather than trusted
    to everyone who touches the file.
    """


def canonical(event: dict[str, Any]) -> str:
    """One event, one line, keys sorted, so the same event always serialises
    byte-identically. Byte stability is what lets B-R4 be asserted by comparing
    bytes instead of by eyeballing two renderings."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)


class EventLog:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._subs: list[queue.Queue[dict[str, Any]]] = []
        if self.path and self.path.exists():
            self._load()

    # ---- writing ---------------------------------------------------------
    def append(self, kind: str, /, **fields: Any) -> dict[str, Any]:
        # `kind` is positional-only (adopted from the Part B branch) so that a
        # caller passing kind="..." lands in `fields` and is rejected by the
        # guard below, rather than colliding with this parameter and raising a
        # TypeError that says nothing about append-only.
        # `t`, `kind` and `seq` are stamped by the log and never by a caller,
        # so a caller cannot forge ordering or rewrite history through append.
        for reserved in ("t", "kind", "seq"):
            if reserved in fields:
                raise AppendOnlyViolation(f"`{reserved}` is set by the log, not by callers")
        event = {"t": round(time.time(), 3), "kind": kind, **fields}
        with self._lock:
            event["seq"] = len(self._events) + 1
            self._events.append(event)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
        return event

    def append_raw(self, event: dict[str, Any]) -> dict[str, Any]:
        """Append a previously recorded event, keeping its own timestamp.

        Replay needs this: a recording is only faithful if the events keep the
        times they actually happened at. It is still an append. `seq` is always
        reassigned by the log, so a replayed event cannot claim a position it
        did not earn, and nothing is ever rewritten or removed.
        """
        if not isinstance(event, dict) or "kind" not in event:
            raise AppendOnlyViolation("a raw event must be a dict carrying a kind")
        record = {k: v for k, v in event.items() if k != "seq"}
        record.setdefault("t", round(time.time(), 3))
        with self._lock:
            record["seq"] = len(self._events) + 1
            self._events.append(record)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(canonical(record) + "\n")
                    fh.flush()
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(record)
            except queue.Full:
                pass
        return record

    # ---- reading ---------------------------------------------------------
    def _load(self) -> None:
        assert self.path is not None
        events: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn final line must not break replay
                if isinstance(obj, dict) and "kind" in obj:
                    obj.setdefault("seq", len(events) + 1)
                    events.append(obj)
        self._events = events

    def replay(self, since: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e.get("seq", 0) > since]

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e.get("kind") == kind]

    # ---- live streaming --------------------------------------------------
    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def stream(self, since: int = 0) -> Iterator[dict[str, Any]]:
        """Replay everything since `since`, then block for new events.

        Replay-then-follow is what makes a browser refresh idempotent (B-R4)
        and what makes a dropped connection recoverable without server state.
        """
        q = self.subscribe()
        try:
            for event in self.replay(since):
                yield event
            while True:
                try:
                    yield q.get(timeout=15.0)
                except queue.Empty:
                    yield {"kind": "ping", "t": round(time.time(), 3)}
        finally:
            self.unsubscribe(q)
