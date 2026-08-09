"""Receipts: findings as pass/fail lines readable in a terminal with no UI.

The receipt is the primary output. The map is the demo; this is the product.
If the graph fails on stage (PRD-B section 7), this is what is left, so it has
to stand on its own.

    B-R19  Every line names both file paths and the exact disagreement.
    B-R25  Never claim zero false positives. Publish the count.
    B-R29  State the caveat on the merge-conflict statistic every time it is used.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from .findings import Finding
from .prove import ProofResult

# The section 3.2 palette, mapped to the nearest terminal colour. Truecolour is
# used when the terminal admits to supporting it, so the receipt and the page
# are recognisably the same product.
_TRUECOLOR = os.environ.get("COLORTERM", "") in ("truecolor", "24bit")


def _supports_colour(stream) -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    return hasattr(stream, "isatty") and stream.isatty()


class Paint:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _rgb(self, text: str, rgb: tuple[int, int, int], fallback: str) -> str:
        if not self.enabled:
            return text
        if _TRUECOLOR:
            r, g, b = rgb
            return f"\033[38;2;{r};{g};{b}m{text}\033[0m"
        return f"{fallback}{text}\033[0m"

    def broken(self, text: str) -> str:   # #d03b3b
        return self._rgb(text, (0xD0, 0x3B, 0x3B), "\033[31m")

    def orphan(self, text: str) -> str:   # #c98500
        return self._rgb(text, (0xC9, 0x85, 0x00), "\033[33m")

    def active(self, text: str) -> str:   # #3987e5
        return self._rgb(text, (0x39, 0x87, 0xE5), "\033[34m")

    def dim(self, text: str) -> str:      # #898781, the healthy/neutral gray
        return self._rgb(text, (0x89, 0x87, 0x81), "\033[90m")

    def bold(self, text: str) -> str:
        return f"\033[1m{text}\033[0m" if self.enabled else text


@dataclass
class Receipt:
    findings: list[Finding]
    suppressed: list[Finding]
    proofs: dict[str, ProofResult]
    baseline_sha: str
    baseline_anchor: str
    baseline_count: int
    files_scanned: int
    duration_ms: float

    @property
    def gating(self) -> list[Finding]:
        return [f for f in self.findings if f.gates()]

    @property
    def exit_code(self) -> int:
        """A-R17: nonzero when a high-confidence finding exists, so this works
        as a merge gate and a CI step."""
        return 1 if self.gating else 0


_CLASS_LABEL = {
    "payload_mismatch": "payload mismatch",
    "no_route": "no matching route",
    "orphan_endpoint": "zero callers",
    "env_unset": "env never set",
}


def render(receipt: Receipt, *, stream=None, colour: bool | None = None) -> str:
    stream = stream or sys.stdout
    paint = Paint(_supports_colour(stream) if colour is None else colour)
    lines: list[str] = []

    anchor = receipt.baseline_sha[:7] if receipt.baseline_sha else "none"
    header = (
        f"irus  baseline {anchor} ({receipt.baseline_anchor})  ·  "
        f"{receipt.files_scanned} files  ·  {receipt.duration_ms:.0f} ms"
    )
    lines.append(paint.bold(header))
    if receipt.baseline_count:
        lines.append(paint.dim(f"      {receipt.baseline_count} pre-existing findings suppressed by the baseline"))
    if receipt.suppressed:
        # A silenced finding is still counted out loud. A suppression file whose
        # effects are invisible is a way to lie to yourself.
        lines.append(paint.dim(f"      {len(receipt.suppressed)} silenced by .irus/suppressions.json"))
    lines.append("")

    if not receipt.findings:
        lines.append(paint.dim("PASS  no findings introduced by this session"))
    for finding in receipt.findings:
        colourise = paint.broken if finding.gates() else (
            paint.orphan if finding.cls in ("orphan_endpoint", "no_route") else paint.dim
        )
        verdict = colourise("FAIL" if finding.gates() else "WARN")
        label = _CLASS_LABEL.get(finding.cls, finding.cls)
        lines.append(
            f"{verdict}  {finding.id}  {finding.seam:<34} {label:<20} {finding.confidence}"
        )
        # B-R19: both sides, always, with the specific disagreement under them.
        # An env finding has one site rather than two, so it says "read at"
        # instead of miscalling a backend file the consumer.
        left, right = ("declared", "read at") if finding.cls == "env_unset" else ("producer", "consumer")
        if finding.producer:
            lines.append(paint.dim(f"      {left:<8}  {finding.producer.render()}"))
        if finding.consumer:
            lines.append(paint.dim(f"      {right:<8}  {finding.consumer.render()}"))
        lines.append(f"      {finding.detail}")
        proof = receipt.proofs.get(finding.id)
        if proof and proof.result != "skipped":
            mark = paint.broken("✗") if proof.result == "fail" else paint.dim("·")
            status = f" → {proof.status}" if proof.status else ""
            lines.append(paint.dim(f"      proof     {mark} {proof.method}{status}  {proof.detail[:90]}"))
        lines.append("")

    high = len(receipt.gating)
    total = len(receipt.findings)
    summary = f"{total} finding{'s' if total != 1 else ''} this session, {high} high-confidence"
    lines.append(paint.bold(summary))
    # B-R25 in the one place a reader is most likely to over-read the number.
    lines.append(paint.dim("      false positives are not zero; the measured split is in findings/ledger.md"))
    return "\n".join(lines) + "\n"


# B-R29: the caveat travels with the statistic, in the same string, so it cannot
# be quoted without it.
MERGE_CONFLICT_STAT = (
    "27.67% merge-conflict rate across 142,000+ agentic PRs (AgenticFlict, arXiv 2604.03551) "
    "— caveat: that figure counts conflicts git already surfaces, which is not the failure "
    "class Irus targets. The on-target number is integration accuracy falling 58% to 25% "
    "(The Specification Gap, arXiv 2603.24284)."
)
