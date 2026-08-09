"""The baseline, and the session diff.

    B-R3   The baseline is anchored to a commit SHA, never to wall-clock time,
           so two people get identical results and the demo replays exactly.
    B-R20  On a clean checkout of a repository, session-scoped findings are zero.

Why merge-base and not session start (PRD-B section 10): if agents were already
working when Irus started, a start-anchored baseline swallows their mismatch and
makes it permanently invisible. The merge-base is the last point both sides
agreed on, which is the only anchor that cannot hide the thing we are looking for.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .check import SeamCache, sweep
from .findings import Finding


class GitUnavailable(Exception):
    """Not a git repository, or git is not installed. Irus still runs; it just
    reports everything, and says so, rather than silently reporting nothing."""


@dataclass
class Baseline:
    sha: str
    finding_ids: set[str]
    count: int
    anchor: str          # "merge-base" | "head" | "none"
    cached: bool = False


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitUnavailable(result.stderr.strip() or " ".join(args))
    return result.stdout.strip()


def _worktree_heads(root: Path) -> list[str]:
    """Every commit checked out in any worktree of this repository. These are
    'the active branches' the baseline is computed between."""
    try:
        out = _git(root, "worktree", "list", "--porcelain")
    except GitUnavailable:
        return []
    heads = []
    for line in out.splitlines():
        if line.startswith("HEAD "):
            heads.append(line.split(None, 1)[1].strip())
    return heads


def anchor_sha(root: Path) -> tuple[str, str]:
    """(sha, how). A-R13 then A-R15: merge-base across active worktrees when
    there is more than one, otherwise HEAD."""
    heads = _worktree_heads(root)
    unique = sorted(set(heads))
    if len(unique) > 1:
        try:
            sha = _git(root, "merge-base", "--octopus", *unique)
            if sha:
                return sha, "merge-base"
        except GitUnavailable:
            pass
    sha = _git(root, "rev-parse", "HEAD")
    return sha, "head"


def _cache_path(root: Path, sha: str) -> Path:
    return root / ".irus" / "baseline" / f"{sha}.json"


def compute(root: str | Path, *, refresh: bool = False) -> Baseline:
    """Check the anchor commit out into a temporary worktree, sweep it, cache
    the result by SHA.

    The temporary worktree is what makes this correct: sweeping the current tree
    and subtracting by heuristic would miss that a finding's *location* moved.
    Sweeping the actual anchored tree gives real ids to subtract.
    """
    root = Path(root).resolve()
    try:
        sha, how = anchor_sha(root)
    except GitUnavailable:
        return Baseline(sha="", finding_ids=set(), count=0, anchor="none")

    cache_file = _cache_path(root, sha)
    if cache_file.is_file() and not refresh:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return Baseline(
                sha=sha,
                finding_ids=set(data["finding_ids"]),
                count=int(data["count"]),
                anchor=how,
                cached=True,
            )
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    tmp = Path(tempfile.mkdtemp(prefix="irus-baseline-"))
    worktree = tmp / "tree"
    try:
        _git(root, "worktree", "add", "--detach", "--quiet", str(worktree), sha)
        result = sweep(worktree, cache=SeamCache())
        ids = {f.id for f in result.findings}
    finally:
        # Always detach the worktree, even on failure — a leaked worktree entry
        # makes the *next* run's merge-base wrong, which is a silent corruption.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=root, capture_output=True, text=True,
        )
        shutil.rmtree(tmp, ignore_errors=True)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"sha": sha, "count": len(ids), "finding_ids": sorted(ids)}, indent=2),
        encoding="utf-8",
    )
    return Baseline(sha=sha, finding_ids=ids, count=len(ids), anchor=how)


def session_findings(findings: list[Finding], baseline: Baseline) -> tuple[list[Finding], list[Finding]]:
    """Split current findings into (introduced this session, pre-existing).

    A repository's pre-existing weirdness becomes invisible. That is the entire
    reason a first run on a large messy repo reports zero (B-R20).
    """
    new, existing = [], []
    for finding in findings:
        (existing if finding.id in baseline.finding_ids else new).append(finding)
    return new, existing
