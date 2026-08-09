"""The event log.

PRD-B section 2: one append-only JSONL file, one event per line. This is the
only state that matters; everything else is derived from it.

    B-R21  The log is append-only. Nothing is ever rewritten or deleted.
    B-R22  Every event carries a timestamp and a kind. Unknown kinds are
           ignored by readers rather than fatal.
    B-R23  The log is the demo recording, the test fixture, and the replay
           source. There is no second format.
    B-R4   Replaying the log from the start reconstructs identical state.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# Kinds the reducer understands. Anything else is carried but not folded into
# state, which is what makes B-R22 a forward-compatibility guarantee rather
# than a politeness.
KNOWN_KINDS = frozenset(
    {
        "baseline",
        "claim",
        "release",
        "surface",
        "finding",
        "proof",
        "receipt",
        "session",
    }
)


class AppendOnlyViolation(Exception):
    """Raised when something tries to open the log in a mode that could lose
    history. B-R21 is enforced here rather than trusted."""


def canonical(event: dict[str, Any]) -> str:
    """One event, one line, keys sorted so the same event always serialises
    byte-identically. Byte-stability is what lets the log be diffed and lets
    B-R4 be asserted by comparing bytes rather than by eyeballing."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"))


class EventLog:
    """Append-only JSONL. The only writer interface is `append`."""

    def __init__(self, path: str | Path, *, clock=time.time) -> None:
        self.path = Path(path)
        self._clock = clock

    # ---------------------------------------------------------------- write

    def append(self, kind: str, /, **fields: Any) -> dict[str, Any]:
        """Append one event. Returns the event as written.

        `t` is stamped here and nowhere else, so stage 1's own output stays a
        pure function of the tree (B-R1) while the log still carries time.
        """
        if "kind" in fields or "t" in fields:
            raise ValueError("`t` and `kind` are set by the log, not by callers")
        event = {"t": round(self._clock(), 2), "kind": kind, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # "a" is the only mode this class ever opens for writing. On POSIX an
        # O_APPEND write cannot land anywhere but the end of the file.
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(canonical(event) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return event

    def append_raw(self, event: dict[str, Any]) -> dict[str, Any]:
        """Append an event that already has `t` and `kind` — used when copying
        a recorded fixture forward, never for new observations."""
        if "t" not in event or "kind" not in event:
            raise ValueError("raw events must already carry `t` and `kind` (B-R22)")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(canonical(event) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return event

    # ----------------------------------------------------------------- read

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self.read()

    def read(self) -> Iterator[dict[str, Any]]:
        """Yield well-formed events in file order.

        A truncated final line (the writer was killed mid-append) and a line
        missing `t` or `kind` are both skipped rather than fatal. A log you
        cannot read is a log that cannot replay.
        """
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if "t" not in event or "kind" not in event:
                    continue
                yield event

    def tail(self, offset: int) -> tuple[list[dict[str, Any]], int]:
        """Events after byte `offset`, plus the new offset. This is how the SSE
        server streams without re-reading the whole file each tick."""
        if not self.path.exists():
            return [], 0
        out: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            fh.seek(offset)
            for line in fh:
                if not line.endswith("\n"):
                    # Partial line: a writer is mid-append. Stop here and pick
                    # it up on the next poll rather than parsing half an event.
                    break
                line = line.strip()
                offset += len(line.encode("utf-8")) + 1
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and "t" in event and "kind" in event:
                    out.append(event)
        return out, offset


# --------------------------------------------------------------------- state


@dataclass
class State:
    """The full derived view. Every field is reconstructed from the log alone;
    nothing here is remembered between replays (B-R4)."""

    baseline_sha: str | None = None
    baseline_findings: int = 0
    session: dict[str, Any] = field(default_factory=dict)
    claims: dict[str, str] = field(default_factory=dict)          # target -> agent
    surfaces: dict[str, dict[str, Any]] = field(default_factory=dict)  # "id|side" -> event
    findings: dict[str, dict[str, Any]] = field(default_factory=dict)  # finding id -> event
    proofs: dict[str, dict[str, Any]] = field(default_factory=dict)    # finding id -> event
    receipts: list[dict[str, Any]] = field(default_factory=list)
    ignored_kinds: dict[str, int] = field(default_factory=dict)
    event_count: int = 0

    def digest(self) -> str:
        """Canonical form of the whole state. Two replays are identical iff
        their digests match — this is the executable form of B-R4."""
        payload = {
            "baseline_sha": self.baseline_sha,
            "baseline_findings": self.baseline_findings,
            "session": self.session,
            "claims": dict(sorted(self.claims.items())),
            "surfaces": dict(sorted(self.surfaces.items())),
            "findings": dict(sorted(self.findings.items())),
            "proofs": dict(sorted(self.proofs.items())),
            "receipts": self.receipts,
            "event_count": self.event_count,
        }
        return canonical(payload)


def replay(events: Iterator[dict[str, Any]] | list[dict[str, Any]]) -> State:
    """Fold the log into state. Pure: same events in, same state out.

    Unknown kinds are counted and dropped (B-R22). Later events of a known
    kind overwrite earlier ones for the same identity, so the log stays
    append-only while the view still shows current truth.
    """
    state = State()
    for event in events:
        state.event_count += 1
        kind = event.get("kind")
        if kind not in KNOWN_KINDS:
            state.ignored_kinds[str(kind)] = state.ignored_kinds.get(str(kind), 0) + 1
            continue
        if kind == "baseline":
            state.baseline_sha = event.get("sha")
            state.baseline_findings = int(event.get("findings", 0) or 0)
        elif kind == "session":
            state.session = {k: v for k, v in event.items() if k not in ("t", "kind")}
        elif kind == "claim":
            target = event.get("target")
            if target:
                state.claims[str(target)] = str(event.get("agent", "unknown"))
        elif kind == "release":
            state.claims.pop(str(event.get("target")), None)
        elif kind == "surface":
            key = f"{event.get('id')}|{event.get('side')}"
            state.surfaces[key] = event
        elif kind == "finding":
            fid = event.get("id")
            if fid:
                state.findings[str(fid)] = event
        elif kind == "proof":
            fid = event.get("id")
            if fid:
                state.proofs[str(fid)] = event
        elif kind == "receipt":
            state.receipts.append(event)
    return state
