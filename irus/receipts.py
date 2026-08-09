"""A-R16: turn findings into pass/fail receipt lines.

A receipt is the honest form of an agent's "done". The agent says it built the
checkout endpoint; the receipt says which parts of that claim survive contact
with the filesystem.

Readable in a terminal with no UI, because the UI is the optional part.
"""

from __future__ import annotations

from collections import defaultdict

from .compare import looks_external
from .model import Finding, Receipt, ReceiptLine, Surface
from .scan import ScanResult

PAYLOAD_KINDS = {"missing_required_field", "unexpected_field", "field_type_mismatch"}


def build(
    result: ScanResult,
    findings: list[Finding] | None = None,
    assignments: list | None = None,
) -> list[Receipt]:
    findings = result.findings if findings is None else findings

    by_seam: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_seam[f.seam].append(f)

    producers = {p.seam: p for p in result.producers}
    consumers: dict[str, Surface] = {c.seam: c for c in result.consumers}
    by_assignment = {a.seam: a for a in (assignments or [])}

    receipts: list[Receipt] = []
    for seam in sorted(set(producers) | set(consumers)):
        fs = by_seam.get(seam, [])
        kinds = {f.kind for f in fs}
        p = producers.get(seam)
        c = consumers.get(seam)

        lines = [
            # A-R3: a finding must name both sides. Reading a receipt without
            # the two file paths leaves the reader unable to act on it.
            ReceiptLine(
                "where",
                True,
                f"server {p.loc if p else 'absent'}  |  client {c.loc if c else 'absent'}",
            ),
            ReceiptLine(
                "endpoint exists",
                p is not None,
                "" if p else "no server route declares this",
            ),
            ReceiptLine(
                "route mounted",
                p is not None and p.mounted,
                "" if not p or p.mounted else "declared on a router nobody includes",
            ),
            ReceiptLine(
                "client calls it",
                c is not None,
                ""
                if c
                # A receipt that shows FAIL while the run reports zero findings
                # reads as a contradiction. Say which one it is.
                else (
                    "no client here calls it, and this route looks externally "
                    "called, so it is not reported as a finding"
                    if p is not None and looks_external(p.path)
                    else "no client in this repository calls it"
                ),
            ),
        ]

        if p and c and c.method in {"POST", "PUT", "PATCH"}:
            enc = next((f for f in fs if f.kind == "encoding_mismatch"), None)
            lines.append(ReceiptLine("encoding matches", enc is None, enc.detail if enc else ""))

            payload = [f for f in fs if f.kind in PAYLOAD_KINDS]
            lines.append(
                ReceiptLine(
                    "payload shape matches",
                    not payload,
                    "; ".join(f.detail for f in payload[:2]),
                )
            )

        if "response_shape_mismatch" in kinds:
            bad = [f for f in fs if f.kind == "response_shape_mismatch"]
            lines.append(ReceiptLine("response shape matches", False, bad[0].detail))

        proofs = [f for f in fs if f.kind == "execution_proof"]
        if proofs:
            lines.append(ReceiptLine("proven by execution", False, proofs[0].detail))

        # A-R23: the authority decision is recorded here so a later round
        # cannot quietly flip which side is expected to change.
        assignment = by_assignment.get(seam)
        if assignment is not None:
            lines.append(
                ReceiptLine(
                    "authority",
                    True,
                    f"{assignment.authority} is authoritative; {assignment.owner} adapts",
                )
            )

        receipts.append(Receipt(seam=seam, lines=lines))

    # Findings with no seam of their own still deserve a receipt.
    loose = [f for f in findings if f.seam not in producers and f.seam not in consumers]
    for f in sorted(loose, key=lambda x: x.seam):
        receipts.append(
            Receipt(seam=f.seam, lines=[ReceiptLine(f.kind.replace("_", " "), False, f.detail)])
        )
    return receipts


def render(receipts: list[Receipt], only_failing: bool = False) -> str:
    blocks = [r.render() for r in receipts if not only_failing or not r.ok]
    return "\n\n".join(blocks)
