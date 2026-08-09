"""The findings ledger — the primary published artifact (PRD-B section 5.1).

    B-R30  Every published number has its false positives published beside it.
    B-R31  Labels are recorded with a reason, not just a verdict.
    B-R32  The ledger is regenerated, not edited, whenever the checker changes.

The split that makes B-R32 enforceable: hand labels live in `findings/labels.json`
and are the only file a human edits. `findings/ledger.md` is generated from a
fresh unfiltered run joined against those labels, and says so at the top. If the
checker changes and a finding's id changes with it, the label stops matching and
the row shows up as UNLABELLED rather than silently inheriting an old verdict.

Unfiltered means unfiltered: no baseline subtraction, no confidence gate, no
suppressions. A ledger that only shows what we already gate on measures our gate,
not our checker.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .check import sweep
from .findings import Finding

LABELS_PATH = Path("findings") / "labels.json"
LEDGER_PATH = Path("findings") / "ledger.md"

VERDICTS = ("TRUE", "FALSE")


@dataclass
class Row:
    finding: Finding
    verdict: str          # TRUE | FALSE | UNLABELLED
    reason: str


@dataclass
class RepoResult:
    name: str
    path: str
    rows: list[Row]
    files_scanned: int
    duration_ms: float
    error: str = ""
    # The commit swept. Without it the ledger is a claim about "some version of
    # that repo", which is not reproducible and therefore not a measurement.
    sha: str = ""

    @property
    def true_count(self) -> int:
        return sum(1 for r in self.rows if r.verdict == "TRUE")

    @property
    def false_count(self) -> int:
        return sum(1 for r in self.rows if r.verdict == "FALSE")

    @property
    def unlabelled(self) -> int:
        return sum(1 for r in self.rows if r.verdict == "UNLABELLED")


def load_labels(root: Path) -> dict[str, dict[str, Any]]:
    path = root / LABELS_PATH
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_labels(root: Path, labels: dict[str, dict[str, Any]]) -> None:
    path = root / LABELS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(labels, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def label(root: Path, repo: str, finding_id: str, verdict: str, reason: str) -> None:
    """Record one hand label. A verdict without a reason is refused (B-R31) —
    an unexplained FALSE is how a checker quietly gets tuned to its own corpus."""
    verdict = verdict.upper()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    if not reason or not reason.strip():
        raise ValueError("a label requires a reason, not just a verdict (B-R31)")
    labels = load_labels(root)
    labels.setdefault(repo, {})[finding_id] = {"verdict": verdict, "reason": reason.strip()}
    save_labels(root, labels)


def run_repo(repo_path: str | Path, *, labels: dict[str, dict[str, Any]], name: str | None = None) -> RepoResult:
    """One repository, unfiltered."""
    repo_path = Path(repo_path).resolve()
    repo_name = name or repo_path.name
    repo_labels = labels.get(repo_name, {})
    try:
        result = sweep(repo_path)
    except Exception as exc:      # a repo we cannot sweep is reported, not hidden
        return RepoResult(repo_name, str(repo_path), [], 0, 0.0, error=f"{type(exc).__name__}: {exc}")

    sha = ""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_path,
            capture_output=True, text=True, timeout=10,
        )
        if completed.returncode == 0:
            sha = completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    rows = []
    for finding in result.findings:
        entry = repo_labels.get(finding.id)
        rows.append(
            Row(
                finding=finding,
                verdict=entry["verdict"] if entry else "UNLABELLED",
                reason=entry.get("reason", "") if entry else "",
            )
        )
    return RepoResult(repo_name, str(repo_path), rows, result.files_scanned, result.duration_ms, sha=sha)


_CLASS_LABEL = {
    "payload_mismatch": "payload mismatch",
    "no_route": "no matching route",
    "orphan_endpoint": "zero callers",
    "env_unset": "read, never set",
}


def worksheet(result: RepoResult) -> str:
    """The labelling worksheet `irus ledger` emits: every finding, with enough
    context to be judged, and a blank verdict to fill in."""
    lines = [f"# labelling worksheet — {result.name}", ""]
    if result.error:
        lines.append(f"could not sweep: {result.error}")
        return "\n".join(lines) + "\n"
    lines.append(f"{len(result.rows)} findings, unfiltered. Label each with:")
    lines.append(f"    irus label {result.name} <id> TRUE|FALSE \"reason\"")
    lines.append("")
    for row in result.rows:
        f = row.finding
        lines.append(f"{f.id}  [{f.confidence:<6}] {f.seam}  — {_CLASS_LABEL.get(f.cls, f.cls)}")
        if f.producer:
            lines.append(f"          producer  {f.producer.render()}")
        if f.consumer:
            lines.append(f"          consumer  {f.consumer.render()}")
        lines.append(f"          {f.detail}")
        lines.append(f"          verdict: {row.verdict}" + (f"  ({row.reason})" if row.reason else ""))
        lines.append("")
    return "\n".join(lines) + "\n"


def render_ledger(results: list[RepoResult]) -> str:
    """`findings/ledger.md`. Every number carries its false positives (B-R30)."""
    total_findings = sum(len(r.rows) for r in results)
    total_true = sum(r.true_count for r in results)
    total_false = sum(r.false_count for r in results)
    total_unlabelled = sum(r.unlabelled for r in results)

    lines = [
        "# Findings ledger",
        "",
        "Generated by `irus ledger`. **Do not edit this file** — edit",
        "`findings/labels.json` and regenerate (B-R32). Rows that read UNLABELLED are",
        "findings no human has judged yet; they are shown rather than hidden, because a",
        "ledger that omits its unjudged rows is a ledger with a thumb on the scale.",
        "",
        "Every run below is **unfiltered**: no baseline subtraction, no confidence gate,",
        "no suppressions. This measures the checker, not the gate.",
        "",
        "## Totals",
        "",
        f"- findings: **{total_findings}**",
        f"- true: **{total_true}**",
        f"- false: **{total_false}**",
        f"- unlabelled: **{total_unlabelled}**",
        "",
    ]
    if total_findings and (total_true + total_false):
        precision = total_true / (total_true + total_false)
        lines.append(f"Precision over labelled rows: **{precision:.0%}** ({total_true}/{total_true + total_false}).")
    lines.append("")
    lines.append(
        "This is not a claim of zero false positives and never will be (B-R25). The "
        "false-positive count above is the point of the artifact, not a footnote to it."
    )
    lines.append("")

    for result in sorted(results, key=lambda r: r.name):
        lines.append(f"## {result.name}")
        lines.append("")
        if result.error:
            lines.append(f"could not sweep: `{result.error}`")
            lines.append("")
            continue
        lines.append(
            f"```\nrepo: {result.name:<22} findings: {len(result.rows):<5} "
            f"true: {result.true_count:<4} false: {result.false_count:<4} "
            f"unlabelled: {result.unlabelled}"
        )
        for row in result.rows:
            f = row.finding
            desc = f"{f.seam} {_CLASS_LABEL.get(f.cls, f.cls)}"
            note = f"  ({row.reason})" if row.reason else ""
            lines.append(f"  {f.id}  {desc:<52} {row.verdict}{note}")
        lines.append("```")
        lines.append("")
        lines.append(
            f"_{result.files_scanned} files swept in {result.duration_ms:.0f} ms"
            + (f" at `{result.sha[:12]}`._" if result.sha else "._")
        )
        lines.append("")

    return "\n".join(lines)


def generate(root: Path, repos: list[Path]) -> tuple[str, list[RepoResult]]:
    labels = load_labels(root)
    results = [run_repo(repo, labels=labels) for repo in repos]
    return render_ledger(results), results
