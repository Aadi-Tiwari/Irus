"""The same filtered integration report for command-line and MCP callers."""

from dataclasses import dataclass
from pathlib import Path

from . import baseline
from .intent import Brief, load as load_brief
from .scan import ScanResult, scan
from .suppress import Suppressions
from .workspace import compose


@dataclass
class Report:
    result: ScanResult
    findings: list
    baseline: baseline.Baseline
    silenced: list
    worktrees: list[str]
    sources: dict[str, list[str]]
    brief: Brief | None

    def source_locations(self, loc) -> list[str]:
        if loc is None:
            return []
        files = self.sources.get(loc.file, [str(Path(self.worktrees[0]) / loc.file)])
        return [f"{file}:{loc.line}" for file in files]


def check(root: Path, *, worktrees=(), no_baseline=False, refresh=False) -> Report:
    root = Path(root).resolve()
    brief = load_brief(root)
    sources = {}
    roots = [str(root)]
    base = baseline.Baseline("", "baseline disabled", set())
    if worktrees:
        with compose([root, *worktrees]) as workspace:
            if not no_baseline:
                base = baseline.Baseline(workspace.sha, "merge-base of selected worktrees", {f.key for f in scan(workspace.root).findings})
            workspace.apply_changes()
            result = scan(workspace.root)
            result.root = root
            sources = workspace.sources
            roots = [str(tree) for tree in workspace.worktrees]
    else:
        result = scan(root)
        if not no_baseline:
            base = baseline.compute(root, refresh=refresh)
    findings = base.suppress(result.findings)
    findings, silenced = Suppressions.load(root).apply(findings)
    return Report(result, findings, base, silenced, roots, sources, brief)
