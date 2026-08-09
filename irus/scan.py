"""Walk a tree, run every extractor, and produce the full finding set.

This is a pure function of the working tree (B-R1): no clock, no network, no
randomness, no model. The same tree always yields the same findings in the same
order, which is what makes baseline subtraction and replay work at all.

B-R14 and B-R15: extraction is cached per file against a digest of its contents,
so re-checking after one edit re-reads one file rather than the tree. The cache
key also carries a signature of the project's router mounts, because a mount
declared in one file changes the resolved path of routes declared in another.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from .compare import compare, orphan_endpoints
from .extract import envvars, py_fastapi, ts_components, ts_express, ts_fetch, ts_wrapper
from .model import HIGH, LOW, MEDIUM, Component, EnvRead, Finding, PathRef, Surface

IGNORE_DIRS = {
    ".git",
    ".irus",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "node_modules",
    "site-packages",
    "target",
    "venv",
}

PY_EXT = {".py"}
TS_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


# --------------------------------------------------------------- .gitignore
def gitignore_patterns(root: Path) -> list[str]:
    """B-R16. Deliberately simple: comments, negations and anchors are ignored.

    A pattern we fail to understand must never *hide* a file, so anything
    unparsed is simply not applied.
    """
    path = root / ".gitignore"
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        out.append(line.rstrip("/").lstrip("/"))
    return out


def ignored(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, f"{pattern}/*"):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts[:-1]):
            return True
    return False


def walk(root: Path, patterns: list[str] | None = None) -> list[Path]:
    """Depth-first scandir rather than rglob.

    `rglob` yields every entry and then each `is_file()` costs another stat.
    `scandir` carries the file/dir flag on the entry itself, which removes one
    syscall per file and lets ignored directories be pruned before descending
    into them rather than after.
    """
    patterns = gitignore_patterns(root) if patterns is None else patterns
    out: list[Path] = []
    root_len = len(str(root)) + 1

    def descend(directory: str) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                if entry.name in IGNORE_DIRS:
                    continue
                rel_dir = entry.path[root_len:].replace("\\", "/")
                if patterns and ignored(rel_dir + "/x", patterns):
                    continue
                descend(entry.path)
            elif entry.is_file(follow_symlinks=False):
                suffix = os.path.splitext(entry.name)[1]
                if suffix not in PY_EXT and suffix not in TS_EXT:
                    continue
                rel = entry.path[root_len:].replace("\\", "/")
                if patterns and ignored(rel, patterns):
                    continue
                out.append(Path(entry.path))

    descend(str(root))
    return out


# ------------------------------------------------------------------- cache
@dataclass
class FileExtract:
    producers: tuple[Surface, ...] = ()
    consumers: tuple[Surface, ...] = ()
    components: tuple[Component, ...] = ()
    used: frozenset[str] = frozenset()
    env_reads: tuple[EnvRead, ...] = ()
    path_refs: tuple[PathRef, ...] = ()
    src: str = ""
    masked: str = ""


class ScanCache:
    """B-R15. Keyed by file content, so an untouched file is never re-parsed."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], FileExtract] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def digest(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return "unreadable"

    def get(self, key: tuple[str, str, str]) -> FileExtract | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
        else:
            self.hits += 1
        return entry

    def put(self, key: tuple[str, str, str], value: FileExtract) -> None:
        self._entries[key] = value

    def __len__(self) -> int:
        return len(self._entries)


def _mount_signature(included: set[str], include_prefix: dict[str, str]) -> str:
    raw = repr(sorted(included)) + repr(sorted(include_prefix.items()))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ result
@dataclass
class ScanResult:
    root: Path
    producers: list[Surface] = field(default_factory=list)
    consumers: list[Surface] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    env_reads: list[EnvRead] = field(default_factory=list)
    path_refs: list[PathRef] = field(default_factory=list)
    declared_env: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    files: int = 0
    cache_hits: int = 0

    def by_confidence(self, level: str) -> list[Finding]:
        return [f for f in self.findings if f.confidence == level]

    @property
    def high(self) -> list[Finding]:
        return self.by_confidence(HIGH)


def env_findings(reads: list[EnvRead], declared: dict[str, str]) -> list[Finding]:
    """A-R4. A read with a default in code is never a failure."""
    out: list[Finding] = []
    seen: set[str] = set()
    for r in reads:
        if r.has_default or r.name in declared or r.name in seen:
            continue
        seen.add(r.name)
        out.append(
            Finding(
                kind="env_unset",
                seam=f"env {r.name}",
                subject=r.name,
                detail=(
                    f"`{r.name}` is read with no default and is set in no .env file, "
                    "compose file, vercel.json, or workflow"
                ),
                confidence=HIGH,
                producer_loc=r.loc,
            )
        )
    return out


# A file under a routes/ or pages/ directory is mounted by a file-based router,
# not by a JSX tag, so "nobody renders it" says nothing about whether it is used.
_ROUTE_DIRS = ("routes/", "pages/", "app/")


def _is_route_file(rel: str) -> bool:
    return any(seg in rel for seg in _ROUTE_DIRS)


def component_findings(components: list[Component], used: set[str]) -> list[Finding]:
    """Part of A-R6. Medium at best: a component can be mounted dynamically.

    A default export is never flagged: the importer chooses its own local name,
    so matching on the declared name cannot show it is unused.

    Two further classes are demoted to low rather than reported at medium,
    because measuring against fastapi/full-stack-fastapi-template showed both
    are noise rather than defects:

      * a file-based route, which a router mounts by convention;
      * a component-kit file, where three or more components in one file are all
        unused, which is a library awaiting callers and not dead code.
    """
    unused = [c for c in components if c.name not in used and not c.default_export]

    per_file: dict[str, int] = {}
    for comp in unused:
        per_file[comp.loc.file] = per_file.get(comp.loc.file, 0) + 1

    out: list[Finding] = []
    for comp in unused:
        library = per_file.get(comp.loc.file, 0) >= 3
        route = _is_route_file(comp.loc.file)
        if route:
            detail = (
                "component is never mounted as JSX, but it sits under a routes "
                "directory and a file-based router may mount it by convention"
            )
        elif library:
            detail = (
                "component is declared but never mounted; this file exports "
                f"{per_file[comp.loc.file]} unused components, so it reads as a "
                "component kit rather than dead code"
            )
        else:
            detail = "component is declared but never mounted or imported anywhere"
        out.append(
            Finding(
                kind="orphan_component",
                seam=f"component {comp.name}",
                subject=comp.name,
                detail=detail,
                confidence=LOW if (route or library) else MEDIUM,
                producer_loc=comp.loc,
            )
        )
    return out


@dataclass
class ParsedPy:
    """A Python file parsed once. Routes are resolved later, from the collector,
    because a route's final path depends on mounts declared in other files."""

    collector: object
    rel: str
    env_reads: tuple[EnvRead, ...] = ()
    path_refs: tuple[PathRef, ...] = ()
    includes: frozenset[str] = frozenset()
    include_prefix: tuple[tuple[str, str], ...] = ()
    unresolved_prefix: frozenset[str] = frozenset()
    aliases: tuple[tuple[str, str], ...] = ()
    models: tuple[tuple[str, tuple], ...] = ()


def _parse_py(path: Path, root: Path, src: str) -> ParsedPy | None:
    parsed = py_fastapi.collect(path, root, src)
    if parsed is None:
        return None
    col, rel = parsed
    tree = getattr(col, "tree", None)
    reads = tuple(envvars.py_reads_from_tree(tree, rel)) if tree is not None else ()
    return ParsedPy(
        collector=col,
        rel=rel,
        env_reads=reads,
        path_refs=tuple(envvars.path_literals(src, rel)),
        includes=frozenset(col.included),
        include_prefix=tuple(sorted(col.include_prefix.items())),
        unresolved_prefix=frozenset(getattr(col, "unresolved_prefix", set())),
        aliases=tuple(sorted(getattr(col, "aliases", {}).items())),
        models=tuple(sorted(col.models.items())),
    )


def _extract_ts(path: Path, root: Path, src: str) -> FileExtract:
    masked = ts_fetch.mask(src)  # masking is the expensive part; do it once
    rel = str(path.relative_to(root)).replace("\\", "/")
    return FileExtract(
        producers=tuple(ts_express.extract_file(path, root, src, masked)),
        consumers=tuple(ts_fetch.extract_file(path, root, src, masked)),
        components=tuple(ts_components.declared(path, root, src, masked)),
        used=frozenset(ts_components.used_names(path, src)),
        env_reads=tuple(envvars.js_reads_from_source(src, rel)),
        path_refs=tuple(envvars.path_literals(src, rel)),
        src=src,
        masked=masked,
    )


def scan(root: Path, cache: ScanCache | None = None) -> ScanResult:
    root = Path(root).resolve()
    # A path that does not exist must never look like a clean repository.
    # Silently returning zero findings is the worst possible failure for a tool
    # whose entire value is finding things.
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    files = walk(root)
    result = ScanResult(root=root, files=len(files))

    # Every file is read once and parsed once. Router mounts, routes and env
    # reads all come out of that single pass, because reading the same bytes
    # three times was the dominant cost.
    parsed_py: dict[Path, ParsedPy] = {}
    ts_extracts: dict[Path, FileExtract] = {}
    included: set[str] = set()
    include_prefix: dict[str, str] = {}
    unresolved: set[str] = set()
    aliases: dict[str, str] = {}
    models: dict[str, tuple] = {}

    for path in files:
        digest = ScanCache.digest(path) if cache is not None else ""
        key = (str(path), digest, "parse")
        cached = cache.get(key) if cache is not None else None

        if cached is None:
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            value: object
            if path.suffix in PY_EXT:
                value = _parse_py(path, root, src)
                if value is None:
                    continue
            else:
                value = _extract_ts(path, root, src)
            if cache is not None:
                cache.put(key, value)  # type: ignore[arg-type]
        else:
            value = cached

        if isinstance(value, ParsedPy):
            parsed_py[path] = value
            included |= set(value.includes)
            include_prefix.update(dict(value.include_prefix))
            unresolved |= set(value.unresolved_prefix)
            aliases.update(dict(value.aliases))
            models.update(dict(value.models))
        elif isinstance(value, FileExtract):
            ts_extracts[path] = value

    included = py_fastapi.resolve_aliases(included, aliases)

    # Routes are resolved only now, when every mount in the project is known.
    for parsed in parsed_py.values():
        if unresolved:
            setattr(parsed.collector, "unresolved_prefix", unresolved)
        result.producers += py_fastapi.surfaces_from(
            parsed.collector, parsed.rel, included, include_prefix, models
        )
        result.env_reads += list(parsed.env_reads)
        result.path_refs += list(parsed.path_refs)

    # Real agent code routes every request through a shared helper, so the
    # contract lives at the call site rather than at the fetch. Discover those
    # helpers first, then read the calls to them (found by Gate B).
    wrappers: dict[str, ts_wrapper.Wrapper] = {}
    for extract in ts_extracts.values():
        if extract.src:
            wrappers.update(ts_wrapper.find_wrappers(extract.src, extract.masked))
    if wrappers:
        for path, extract in ts_extracts.items():
            if extract.src:
                result.consumers += ts_wrapper.extract_calls(
                    path, root, wrappers, extract.src, extract.masked
                )

    used_components: set[str] = set()
    declared_components: dict[str, Component] = {}
    for extract in ts_extracts.values():
        result.producers += list(extract.producers)
        result.consumers += list(extract.consumers)
        result.env_reads += list(extract.env_reads)
        result.path_refs += list(extract.path_refs)
        used_components |= set(extract.used)
        for comp in extract.components:
            declared_components.setdefault(comp.name, comp)

    result.cache_hits = cache.hits if cache else 0
    result.components = list(declared_components.values())
    result.declared_env = envvars.declared_names(root)

    result.findings = (
        compare(result.producers, result.consumers)
        + orphan_endpoints(result.producers, result.consumers, result.path_refs)
        + env_findings(result.env_reads, result.declared_env)
        + component_findings(result.components, used_components)
    )
    result.findings.sort(key=lambda f: (f.confidence != HIGH, f.kind, f.seam, f.subject))
    return result
