"""A-R23 to A-R25: the fix loop, and the two rules that keep it honest.

The loop is a plain loop with a stopping condition, not an agent. It is about
forty lines because that is all it needs to be, and because a model in this
position would remove the one guarantee that makes it safe.

Two failure modes are designed out rather than hoped against:

  A-R23/A-R24  Oscillation. Baton cannot infer which side of a disagreement is
               wrong, so it declares one. The producer is authoritative by
               default and each failing seam is assigned to exactly one owner
               per round, which makes "A changes to match B while B changes to
               match A" structurally impossible.

  A-R25        Silent regression. A fix in round two can break a seam that
               passed in round one. Every round re-runs the full receipt set
               and is accepted only if the total strictly decreases, so the
               loop can never report progress while getting worse.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .model import CONSUMER, HIGH, PRODUCER, Finding

PRODUCER_AUTHORITATIVE = "producer"
CONSUMER_AUTHORITATIVE = "consumer"


def authority_for(finding: Finding, overrides: dict[str, str] | None = None) -> str:
    """Which side must change. Overridable per seam, recorded in the receipt."""
    if overrides and finding.seam in overrides:
        return overrides[finding.seam]
    return PRODUCER_AUTHORITATIVE


def owner_of(finding: Finding, overrides: dict[str, str] | None = None) -> str:
    """The side that adapts is the side that is not authoritative."""
    return CONSUMER if authority_for(finding, overrides) == PRODUCER_AUTHORITATIVE else PRODUCER


@dataclass(frozen=True)
class Assignment:
    seam: str
    owner: str
    authority: str
    findings: tuple[str, ...]


def assign(
    findings: list[Finding], overrides: dict[str, str] | None = None
) -> list[Assignment]:
    """A-R24: exactly one owner per seam per round."""
    grouped: dict[str, list[Finding]] = {}
    for f in findings:
        if f.confidence != HIGH:
            continue
        grouped.setdefault(f.seam, []).append(f)

    out: list[Assignment] = []
    for seam in sorted(grouped):
        group = grouped[seam]
        out.append(
            Assignment(
                seam=seam,
                owner=owner_of(group[0], overrides),
                authority=authority_for(group[0], overrides),
                findings=tuple(sorted(f.key for f in group)),
            )
        )
    return out


@dataclass
class Round:
    number: int
    before: int
    after: int
    accepted: bool
    reason: str
    assignments: list[Assignment] = field(default_factory=list)


@dataclass
class LoopResult:
    rounds: list[Round] = field(default_factory=list)
    final: int = 0
    converged: bool = False

    @property
    def accepted_rounds(self) -> list[Round]:
        return [r for r in self.rounds if r.accepted]


def run_loop(
    check: Callable[[], list[Finding]],
    fix: Callable[[list[Assignment]], None],
    revert: Callable[[], None] | None = None,
    max_rounds: int = 5,
    overrides: dict[str, str] | None = None,
) -> LoopResult:
    """Detect, assign, fix, re-check, ratchet.

    `check` must re-run the FULL receipt set, not just the seam last touched.
    Re-checking only the fixed seam is exactly how a loop converges to
    something worse than where it started.
    """
    result = LoopResult()
    findings = check()
    failing = [f for f in findings if f.confidence == HIGH]

    for number in range(1, max_rounds + 1):
        if not failing:
            result.converged = True
            break

        before = len(failing)
        assignments = assign(failing, overrides)
        fix(assignments)

        findings = check()
        after_list = [f for f in findings if f.confidence == HIGH]
        after = len(after_list)

        accepted = after < before
        reason = (
            f"{before} -> {after}"
            if accepted
            else f"rejected: {before} -> {after} is not a strict decrease"
        )
        result.rounds.append(
            Round(number, before, after, accepted, reason, assignments)
        )

        if not accepted:
            if revert is not None:
                revert()
                findings = check()
                after_list = [f for f in findings if f.confidence == HIGH]
            failing = after_list
            break

        failing = after_list

    result.final = len(failing)
    result.converged = result.converged or not failing
    return result
