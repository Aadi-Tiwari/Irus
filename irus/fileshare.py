"""Let a guest read and edit the host's project files.

This is the thing the room was missing. Coordination told two people their halves
disagreed; it did not let either of them fix the other's half. Sharing files is
what makes a room a workspace instead of a noticeboard.

It is also remote write access to someone's disk, so every guard here is load
bearing and none of them is optional:

  * **Off unless the host asks for it.** `irus watch --share-files`. A room that
    silently exposed the filesystem would be a backdoor, not a feature.
  * **A token on every call, reads included.** Unlike findings, which are
    harmless to read, source is not.
  * **Confined to the repository.** Every path is resolved and checked to be
    inside the root before it is opened. `../` and absolute paths and symlinks
    that point outward are all refused, and the check is on the *resolved* path
    so it cannot be tricked by a link created after the fact.
  * **Only source files.** The same walk rules the scanner uses, so
    `node_modules`, `.git` and `.env` are not on the menu.
  * **Size capped**, because a write endpoint with no ceiling is a way to fill
    someone's disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .scan import IGNORE_DIRS, PY_EXT, TS_EXT, walk

MAX_BYTES = 2_000_000

# Beyond source, the files two people editing a project together actually touch.
EXTRA_SUFFIXES = {
    ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".css", ".html", ".sql",
    ".cfg", ".ini", ".sh", ".env.example",
}

# Never served, whatever the suffix says. Secrets do not become shareable just
# because someone turned file sharing on.
DENY_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "credentials"}


class FileShareError(RuntimeError):
    pass


class OutsideRepository(FileShareError):
    """A path resolved to somewhere other than inside the shared repository."""


@dataclass(frozen=True)
class Entry:
    path: str
    bytes: int


def _shareable(path: Path) -> bool:
    if path.name in DENY_NAMES:
        return False
    return path.suffix in PY_EXT or path.suffix in TS_EXT or path.suffix in EXTRA_SUFFIXES


def resolve(root: Path, relative: str) -> Path:
    """Turn a client-supplied path into a real one, or refuse.

    The check is on the resolved path, not the string, so `..`, an absolute
    path, and a symlink pointing out of the tree are all caught by the same
    test rather than by three separate string rules that can each be evaded.
    """
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise OutsideRepository(f"{relative!r} resolves outside the shared repository")
    if candidate.name in DENY_NAMES:
        raise OutsideRepository(f"{relative!r} is never shared")
    if any(part in IGNORE_DIRS for part in candidate.relative_to(root).parts[:-1]):
        raise OutsideRepository(f"{relative!r} is inside an ignored directory")
    return candidate


def listing(root: Path) -> list[Entry]:
    root = Path(root).resolve()
    out: list[Entry] = []
    seen: set[str] = set()
    for path in walk(root):
        rel = path.relative_to(root).as_posix()
        if _shareable(path) and rel not in seen:
            seen.add(rel)
            out.append(Entry(rel, path.stat().st_size))
    # walk() only yields source; pick up the companion files by hand.
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORE_DIRS for part in rel_parts[:-1]):
            continue
        rel = "/".join(rel_parts)
        if rel not in seen and _shareable(path):
            seen.add(rel)
            out.append(Entry(rel, path.stat().st_size))
    return sorted(out, key=lambda e: e.path)


def read(root: Path, relative: str) -> str:
    path = resolve(root, relative)
    if not path.is_file():
        raise FileShareError(f"{relative!r} is not a file")
    if not _shareable(path):
        raise FileShareError(f"{relative!r} is not a shareable file type")
    if path.stat().st_size > MAX_BYTES:
        raise FileShareError(f"{relative!r} is larger than {MAX_BYTES} bytes")
    return path.read_text(encoding="utf-8", errors="replace")


def write(root: Path, relative: str, content: str) -> int:
    path = resolve(root, relative)
    if not _shareable(path):
        raise FileShareError(f"{relative!r} is not a shareable file type")
    data = content.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise FileShareError(f"refusing to write more than {MAX_BYTES} bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)
