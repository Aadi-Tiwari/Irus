"""B-R25, B-R30 to B-R32: the findings ledger.

The primary published artifact. Run the checker unfiltered against real
repositories, label every finding true or false by hand, and publish all of it
including the false positives.

The reason this exists rather than an accuracy claim: a tool that says "eleven
findings, three true, here they all are" cannot be ambushed by someone who finds
a false positive, because it published them first. A claim of zero false
positives dies to a single counterexample.

The ledger is regenerated rather than edited (B-R32). Labels already recorded
are carried forward by finding key, so regenerating never silently discards
human judgement, and a finding that disappeared is reported rather than dropped.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .model import HIGH, Finding
from .scan import ScanResult, scan

TRUE, FALSE, UNLABELLED = "true", "false", "unlabelled"


@dataclass
class Entry:
    key: str
    repo: str
    kind: str
    seam: str
    subject: str
    confidence: str
    detail: str
    location: str
    label: str = UNLABELLED
    reason: str = ""  # B-R31: a verdict without a reason is not a label

    @classmethod
    def from_finding(cls, repo: str, f: Finding) -> "Entry":
        loc = f.producer_loc or f.consumer_loc
        return cls(
            key=f.key,
            repo=repo,
            kind=f.kind,
            seam=f.seam,
            subject=f.subject,
            confidence=f.confidence,
            detail=f.detail,
            location=str(loc) if loc else "",
        )


@dataclass
class RepoReport:
    repo: str
    entries: list[Entry] = field(default_factory=list)
    files: int = 0
    error: str = ""

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def true_positives(self) -> int:
        return sum(1 for e in self.entries if e.label == TRUE)

    @property
    def false_positives(self) -> int:
        return sum(1 for e in self.entries if e.label == FALSE)

    @property
    def unlabelled(self) -> int:
        return sum(1 for e in self.entries if e.label == UNLABELLED)

    @property
    def precision(self) -> float | None:
        labelled = self.true_positives + self.false_positives
        if labelled == 0:
            return None
        return self.true_positives / labelled


@dataclass
class Ledger:
    reports: list[RepoReport] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(r.total for r in self.reports)

    @property
    def true_positives(self) -> int:
        return sum(r.true_positives for r in self.reports)

    @property
    def false_positives(self) -> int:
        return sum(r.false_positives for r in self.reports)

    @property
    def unlabelled(self) -> int:
        return sum(r.unlabelled for r in self.reports)

    @property
    def precision(self) -> float | None:
        labelled = self.true_positives + self.false_positives
        return None if labelled == 0 else self.true_positives / labelled


def previous_labels(path: Path) -> dict[str, tuple[str, str]]:
    """Carry human labels forward across a regeneration."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, tuple[str, str]] = {}
    for repo in raw.get("repos", []):
        for entry in repo.get("entries", []):
            key = str(entry.get("key", ""))
            label = str(entry.get("label", UNLABELLED))
            if key and label != UNLABELLED:
                out[key] = (label, str(entry.get("reason", "")))
    return out


def build(roots: list[Path], labels: dict[str, tuple[str, str]] | None = None) -> Ledger:
    """Unfiltered: no baseline, no suppressions. The ledger shows everything."""
    labels = labels or {}
    ledger = Ledger()
    for root in roots:
        root = Path(root)
        report = RepoReport(repo=root.name)
        try:
            result: ScanResult = scan(root)
        except Exception as exc:  # a repo that will not scan is reported, not skipped
            report.error = f"{type(exc).__name__}: {exc}"
            ledger.reports.append(report)
            continue
        report.files = result.files
        for f in result.findings:
            entry = Entry.from_finding(root.name, f)
            if entry.key in labels:
                entry.label, entry.reason = labels[entry.key]
            report.entries.append(entry)
        ledger.reports.append(report)
    return ledger


def to_json(ledger: Ledger) -> str:
    return json.dumps(
        {
            "totals": {
                "findings": ledger.total,
                "true": ledger.true_positives,
                "false": ledger.false_positives,
                "unlabelled": ledger.unlabelled,
                "precision": ledger.precision,
            },
            "repos": [
                {
                    "repo": r.repo,
                    "files": r.files,
                    "error": r.error,
                    "entries": [asdict(e) for e in r.entries],
                }
                for r in ledger.reports
            ],
        },
        indent=2,
    )


def to_markdown(ledger: Ledger) -> str:
    lines: list[str] = ["# Findings ledger", ""]
    precision = ledger.precision
    lines.append(
        f"**{ledger.total} findings across {len(ledger.reports)} repositories.** "
        f"{ledger.true_positives} true, {ledger.false_positives} false, "
        f"{ledger.unlabelled} unlabelled."
    )
    if precision is None:
        lines.append("")
        lines.append(
            "Precision is not reported because nothing has been labelled yet. "
            "An unlabelled ledger is not evidence."
        )
    else:
        lines.append("")
        lines.append(f"Precision over labelled findings: **{precision:.0%}**.")
    lines.append("")
    lines.append(
        "Every finding the checker produced is listed, including the ones that "
        "turned out to be wrong. A tool that publishes only its hits is not "
        "measurable."
    )
    lines.append("")

    for r in ledger.reports:
        lines.append(f"## {r.repo}")
        lines.append("")
        if r.error:
            lines.append(f"Scan failed: `{r.error}`")
            lines.append("")
            continue
        lines.append(
            f"{r.files} source files scanned. {r.total} findings: "
            f"{r.true_positives} true, {r.false_positives} false, {r.unlabelled} unlabelled."
        )
        lines.append("")
        if not r.entries:
            lines.append("No findings.")
            lines.append("")
            continue
        lines.append("| key | conf | kind | seam | label | reason |")
        lines.append("|---|---|---|---|---|---|")
        for e in r.entries:
            subject = f" `{e.subject}`" if e.subject else ""
            lines.append(
                f"| `{e.key}` | {e.confidence} | {e.kind} | `{e.seam}`{subject} "
                f"| {e.label} | {e.reason} |"
            )
        lines.append("")
    return "\n".join(lines)


def write(ledger: Ledger, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md, js = out_dir / "ledger.md", out_dir / "ledger.json"
    md.write_text(to_markdown(ledger), encoding="utf-8")
    js.write_text(to_json(ledger) + "\n", encoding="utf-8")
    return md, js
