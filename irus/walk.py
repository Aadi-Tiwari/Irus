"""File discovery and the ignore list.

    B-R16  The file watcher ignores `node_modules`, `.git`, `__pycache__`,
           `dist`, `.venv`, and everything in `.gitignore`, and debounces
           bursts.

The same ignore set is used by the checker, not just the watcher: if the sweep
walked `node_modules` it would blow the 2-second budget in B-R13 on any real
repository, and it would find "mismatches" in vendored code nobody wrote.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

# Named in B-R16 explicitly. These are pruned by directory name at any depth.
ALWAYS_IGNORE = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        "dist",
        ".venv",
        # Not named in B-R16 but same category: large, generated, not authored.
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".next",
        "build",
        ".irus",
        "site-packages",
    }
)

PY_SUFFIXES = frozenset({".py"})
WEB_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
SOURCE_SUFFIXES = PY_SUFFIXES | WEB_SUFFIXES


class Ignore:
    """Ignore rules for one repository root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.patterns: list[str] = []
        self._load_gitignore()

    def _load_gitignore(self) -> None:
        path = self.root / ".gitignore"
        if not path.is_file():
            return
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                # Negations are not supported; treating `!x` as an ignore would
                # be worse than not reading it, so it is skipped outright.
                continue
            self.patterns.append(line.rstrip("/"))

    def ignored(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return True
        parts = rel.parts
        if any(part in ALWAYS_IGNORE for part in parts):
            return True
        rel_str = str(rel)
        for pattern in self.patterns:
            if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel.name, pattern):
                return True
            # A directory pattern ignores everything beneath it.
            if any(fnmatch.fnmatch(part, pattern) for part in parts):
                return True
        return False


def source_files(root: Path, suffixes: frozenset[str] = SOURCE_SUFFIXES) -> list[Path]:
    """Every non-ignored source file under `root`, sorted.

    Sorted output is load-bearing: it is what makes the sweep's result a pure
    function of the tree rather than of directory iteration order (B-R1).
    """
    root = Path(root)
    ignore = Ignore(root)
    out: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in ALWAYS_IGNORE or ignore.ignored(entry):
                    continue
                stack.append(entry)
            elif entry.suffix in suffixes and not ignore.ignored(entry):
                out.append(entry)
    return sorted(out)


def split_sides(files: list[Path]) -> tuple[list[Path], list[Path]]:
    """(python files, web files)."""
    py = [f for f in files if f.suffix in PY_SUFFIXES]
    web = [f for f in files if f.suffix in WEB_SUFFIXES]
    return py, web
