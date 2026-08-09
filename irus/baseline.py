"""A-R13, A-R14, A-R15 (and B-R3): report only what this session introduced.

The baseline is anchored to a commit, never to wall-clock time. Anchoring to
"when the tool started" would hide the bug whenever agents were already working
before the tool was launched, which is the common case and the exact failure the
tool exists to catch.

Anchoring to the merge-base also makes the result reproducible: two people on
the same branches compute the same baseline, and a replay is identical every
run.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .model import Finding
from .scan import scan


class GitError(RuntimeError):
    pass


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def is_repo(root: Path) -> bool:
    try:
        git(root, "rev-parse", "--git-dir")
        return True
    except (GitError, FileNotFoundError):
        return False


def worktree_heads(root: Path) -> list[str]:
    """Commits currently checked out across every linked worktree."""
    try:
        out = git(root, "worktree", "list", "--porcelain")
    except (GitError, FileNotFoundError):
        return []
    heads = [line.split(" ", 1)[1].strip() for line in out.splitlines() if line.startswith("HEAD ")]
    return list(dict.fromkeys(heads))


def anchor(root: Path) -> tuple[str, str]:
    """Return (sha, how). `how` explains the choice in the receipt."""
    heads = worktree_heads(root)
    if len(heads) > 1:
        try:
            if len(heads) == 2:
                return git(root, "merge-base", *heads), f"merge-base of {len(heads)} worktrees"
            return (
                git(root, "merge-base", "--octopus", *heads),
                f"merge-base of {len(heads)} worktrees",
            )
        except GitError:
            pass
    # A-R15: a single tree with uncommitted work anchors to HEAD, so everything
    # not yet committed counts as this session.
    return git(root, "rev-parse", "HEAD"), "HEAD of a single worktree"


@dataclass
class Baseline:
    sha: str
    how: str
    keys: set[str]
    cached: bool = False

    def suppress(self, findings: list[Finding]) -> list[Finding]:
        return [f for f in findings if f.key not in self.keys]


def cache_path(root: Path, sha: str) -> Path:
    return root / ".irus" / f"baseline-{sha[:12]}.json"


def compute(root: Path, refresh: bool = False) -> Baseline:
    root = Path(root).resolve()
    if not is_repo(root):
        return Baseline(sha="", how="not a git repository", keys=set())

    sha, how = anchor(root)
    cache = cache_path(root, sha)
    if cache.exists() and not refresh:
        data = json.loads(cache.read_text(encoding="utf-8"))
        return Baseline(sha=sha, how=how, keys=set(data.get("keys", [])), cached=True)

    with tempfile.TemporaryDirectory(prefix="irus-base-") as tmp:
        checkout = Path(tmp) / "tree"
        try:
            git(root, "worktree", "add", "--detach", "--quiet", str(checkout), sha)
        except GitError as exc:
            raise GitError(f"could not check out baseline {sha[:12]}: {exc}") from exc
        try:
            keys = {f.key for f in scan(checkout).findings}
        finally:
            try:
                git(root, "worktree", "remove", "--force", str(checkout))
            except GitError:
                pass

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"sha": sha, "keys": sorted(keys)}, indent=1), encoding="utf-8"
    )
    return Baseline(sha=sha, how=how, keys=keys)
