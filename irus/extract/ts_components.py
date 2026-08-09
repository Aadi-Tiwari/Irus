"""Part of A-R6: React components that are declared but never mounted."""

from __future__ import annotations

import re
from pathlib import Path

from ..model import Component, Loc
from .ts_fetch import mask

_DEFAULT_DECL = re.compile(r"export\s+default\s+(?:function\s+)?([A-Z][\w$]*)")

_DECLS = [
    re.compile(r"export\s+default\s+function\s+([A-Z][\w$]*)"),
    re.compile(r"export\s+function\s+([A-Z][\w$]*)"),
    re.compile(r"export\s+(?:const|let)\s+([A-Z][\w$]*)\s*[:=]"),
    re.compile(r"^\s*function\s+([A-Z][\w$]*)\s*\(", re.M),
    re.compile(r"^\s*(?:const|let)\s+([A-Z][\w$]*)\s*=\s*\(", re.M),
]


def _line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def declared(
    path: Path, root: Path, src: str | None = None, masked: str | None = None
) -> list[Component]:
    if path.suffix not in (".tsx", ".jsx"):
        return []
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if masked is None:
        masked = mask(src)
    rel = str(path.relative_to(root)).replace("\\", "/")
    defaults = {m.group(1) for m in _DEFAULT_DECL.finditer(masked)}
    out: dict[str, Component] = {}
    for pattern in _DECLS:
        for m in pattern.finditer(masked):
            name = m.group(1)
            # Must actually render markup to count as a component.
            if "<" not in src:
                continue
            exported = m.group(0).lstrip().startswith("export")
            if name not in out or exported:
                out[name] = Component(
                    name,
                    Loc(rel, _line_of(src, m.start())),
                    exported,
                    default_export=name in defaults,
                )
    return list(out.values())


def used_names(path: Path, src: str | None = None) -> set[str]:
    """Component names this file mounts as JSX or imports by name."""
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names = {m.group(1) for m in re.finditer(r"<\s*([A-Z][\w$]*)", src)}
    for m in re.finditer(r"import\s+([^;]+?)\s+from", src):
        clause = m.group(1)
        names.update(re.findall(r"[A-Z][\w$]*", clause))
    # A lazily loaded component is mounted even though no tag names it here.
    for m in re.finditer(r"(?:lazy|dynamic)\s*\(", src):
        tail = src[m.end() : m.end() + 200]
        names.update(re.findall(r"[A-Z][\w$]*", tail))
    return names
