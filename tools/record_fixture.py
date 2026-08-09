"""Generate a replayable session log from a fixture tree.

The log is the demo recording, the test fixture, and the replay source — there
is no second format (B-R23). This script produces one from a checkout by
sweeping it and laying the resulting events out in the order two agents working
in parallel would actually have produced them.

Timestamps are fixed, not sampled from the clock. A fixture whose timestamps
change on every regeneration cannot be byte-compared, and B-R4 is asserted by
byte comparison.

    python tools/record_fixture.py fixtures/synthetic-checkout fixtures/session.jsonl
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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irus.scan import scan as sweep                # noqa: E402
from irus.eventlog import EventLog                 # noqa: E402
from irus.prove import prove_schema as tier1       # noqa: E402

# A fixed epoch so regenerating the fixture is a no-op when nothing changed.
T0 = 1723190400.0


class FixedClock:
    """Monotonic, deterministic, and entirely fake."""

    def __init__(self, start: float = T0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def record(source: Path, out: Path) -> int:
    if out.exists():
        out.unlink()          # regenerate, never append onto an old recording
    clock = FixedClock()
    log = EventLog(out, clock=clock)

    result = sweep(source)

    log.append("session", command="fixture", root=source.name, synthetic=(source / "SYNTHETIC").exists())
    clock.advance(0.4)
    log.append("baseline", sha="a1b2c3d", findings=0, anchor="merge-base")

    # Agent A takes the producer side and finishes first.
    clock.advance(12.0)
    log.append("claim", agent="agent-a", target="api/checkout")
    for route in result.routes:
        clock.advance(9.0)
        log.append(
            "surface", id=route.seam, side="producer",
            shape=dict(route.model.fields) if route.model else {},
            encoding=route.encoding, file=route.file, agent="agent-a",
        )
    clock.advance(3.0)
    log.append("release", agent="agent-a", target="api/checkout")

    # Agent B takes the consumer side, having never seen agent A's half.
    clock.advance(6.0)
    log.append("claim", agent="agent-b", target="web/checkout")
    for call in result.calls:
        clock.advance(11.0)
        log.append(
            "surface", id=call.seam, side="consumer",
            shape=dict(call.fields), encoding=call.encoding, file=call.file, agent="agent-b",
        )

    # The moment the second agent finishes is the moment the arc appears
    # (B-R39). Nothing before this point is red.
    clock.advance(0.04)
    log.append("release", agent="agent-b", target="web/checkout")
    for finding in result.findings:
        clock.advance(0.02)
        log.append("finding", **finding.to_event())

    # Then, one keypress later in the demo script, proof (B-R36).
    clock.advance(2.4)
    for finding in result.findings:
        proof = tier1(finding)
        if proof.result == "skipped":
            continue
        clock.advance(0.3)
        log.append("proof", **proof.to_event())

    clock.advance(0.1)
    log.append(
        "receipt",
        total=len(result.findings),
        high=len([f for f in result.findings if f.gates()]),
        suppressed=0,
        exit_code=1 if any(f.gates() for f in result.findings) else 0,
        files=result.files_scanned,
    )
    return len(result.findings)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    source, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    count = record(source, out)
    print(f"recorded {out} from {source.name}: {count} findings")
    if (source / "SYNTHETIC").exists():
        print("NOTE: source is synthetic. This log is scaffolding, not evidence (B-R26).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
