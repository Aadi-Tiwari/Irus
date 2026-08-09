"""Environment variables: read in source, set nowhere.

PRD-A calls this the one verified-unoccupied gap, and the reason it works is
that it is nearly grep-cost and nearly false-positive-free — *provided* the
writer side is read from every place a value can legitimately come from. Missing
one writer source turns the whole check into noise, so the list here is the
requirement list from A-R4 exactly.

YAML is read with an indentation scanner rather than a parser, because PyYAML is
a dependency and B-R5 wants this installable with no network. The scanner
handles the block and inline-list forms that compose files and workflows
actually use; anything it cannot read is counted and reported, never guessed.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

# Reads
_PROCESS_ENV = re.compile(r"\b(?:process|import\.meta)\s*\.\s*env\s*(?:\.\s*([A-Z_][A-Z0-9_]*)|\[\s*[\"']([^\"']+)[\"']\s*\])")
# Writers
_DOTENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_YAML_KEY = re.compile(r"^(\s*)([A-Za-z_][\w.-]*)\s*:\s*(.*)$")
_YAML_ITEM = re.compile(r"^(\s*)-\s+(.*)$")
_GHA_SECRET = re.compile(r"\$\{\{\s*secrets\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_DOCKER_ENV = re.compile(r"^\s*(ENV|ARG)\s+(.*)$", re.IGNORECASE)
_SKIP_DIRS = frozenset({"node_modules", ".git", "__pycache__", "dist", ".venv", "venv"})


# Provided by the runtime or the CI runner rather than by anything a repository
# commits. Flagging these was a false positive found by running the checker
# against real repositories — `CI` "read, never set" is true of the file tree and
# false of the world. Reported here rather than quietly dropped, because the
# reason a name is exempt matters as much as the fact that it is (B-R27).
AMBIENT = frozenset({
    "CI", "HOME", "PATH", "PWD", "USER", "USERNAME", "SHELL", "TMPDIR", "TEMP", "TMP",
    "LANG", "LC_ALL", "TZ", "TERM", "HOSTNAME",
    "NODE_ENV", "PYTHONPATH", "PYTHONUNBUFFERED", "VIRTUAL_ENV", "CONDA_PREFIX",
    "GITHUB_ACTIONS", "GITHUB_REF", "GITHUB_SHA", "GITHUB_TOKEN", "GITHUB_WORKSPACE",
    "GITHUB_REPOSITORY", "GITHUB_EVENT_NAME", "RUNNER_OS",
})


@dataclass(frozen=True)
class EnvRead:
    name: str
    file: str
    line: int
    # "hard" — os.environ["X"], raises KeyError if absent.
    # "soft" — os.getenv("X") with no default, silently yields None.
    # "defaulted" — a fallback exists, so an unset value is not a failure.
    severity: str


@dataclass(frozen=True)
class EnvWriter:
    name: str
    source: str


# --------------------------------------------------------------------- reads


def _python_reads(path: Path, rel: str) -> list[EnvRead]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    out: list[EnvRead] = []

    # `if "X" in os.environ:` is the third way to write a default, alongside
    # `os.getenv("X", d)` and `process.env.X || d`. A file that tests for a
    # name's presence is handling its absence, so a hard read of that name in
    # the same file is not a crash waiting to happen. Scoped per file rather
    # than per block: coarser than real flow analysis, and wrong only in the
    # direction of staying quiet.
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and node.ops and isinstance(node.ops[0], (ast.In, ast.NotIn)):
            left, right = node.left, node.comparators[0]
            if (
                isinstance(left, ast.Constant) and isinstance(left.value, str)
                and isinstance(right, ast.Attribute) and right.attr == "environ"
            ):
                guarded.add(left.value)

    for node in ast.walk(tree):
        # os.environ["X"]
        if isinstance(node, ast.Subscript):
            target = node.value
            if isinstance(target, ast.Attribute) and target.attr == "environ":
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    severity = "defaulted" if key.value in guarded else "hard"
                    out.append(EnvRead(key.value, rel, node.lineno, severity))
        # os.getenv("X"[, default]) and os.environ.get("X"[, default])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            fn = node.func
            is_getenv = fn.attr == "getenv"
            is_environ_get = (
                fn.attr == "get"
                and isinstance(fn.value, ast.Attribute)
                and fn.value.attr == "environ"
            )
            if not (is_getenv or is_environ_get):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            name = node.args[0].value
            if not isinstance(name, str):
                continue
            has_default = len(node.args) > 1 or any(k.arg == "default" for k in node.keywords)
            # A default that is literally None is not a real fallback.
            if has_default and len(node.args) > 1:
                second = node.args[1]
                if isinstance(second, ast.Constant) and second.value is None:
                    has_default = False
            out.append(EnvRead(name, rel, node.lineno, "defaulted" if has_default else "soft"))
    return out


def _js_reads(path: Path, rel: str) -> list[EnvRead]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[EnvRead] = []
    for match in _PROCESS_ENV.finditer(source):
        name = match.group(1) or match.group(2)
        line_start = source.rfind("\n", 0, match.start()) + 1
        line_end = source.find("\n", match.end())
        line_text = source[line_start: line_end if line_end != -1 else len(source)]
        # `process.env.X || "fallback"` and `?? "fallback"` are defaults.
        after = source[match.end(): match.end() + 40]
        severity = "defaulted" if re.match(r"\s*(\|\||\?\?)", after) else "soft"
        if "throw" in line_text and severity == "soft":
            severity = "hard"
        out.append(EnvRead(name, rel, source.count("\n", 0, match.start()) + 1, severity))
    return out


def reads(files: list[Path], root: Path) -> list[EnvRead]:
    out: list[EnvRead] = []
    for path in sorted(files):
        rel = str(path.relative_to(root))
        if path.suffix == ".py":
            out.extend(_python_reads(path, rel))
        elif path.suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            out.extend(_js_reads(path, rel))
    out = [r for r in out if r.name not in AMBIENT]
    return sorted(out, key=lambda r: (r.name, r.file, r.line))


# ------------------------------------------------------------------- writers


def _scan_yaml_env(text: str, source: str) -> set[EnvWriter]:
    """Collect names under any `environment:` or `env:` block, plus `secrets.X`
    references, plus `env_file:` mentions (which we treat as satisfying every
    name, since we cannot see inside a file that may not be committed)."""
    out: set[EnvWriter] = set()
    lines = text.splitlines()
    block_indent: int | None = None

    for raw in lines:
        for match in _GHA_SECRET.finditer(raw):
            out.add(EnvWriter(match.group(1), f"{source} (secrets)"))

        key_match = _YAML_KEY.match(raw)
        item_match = _YAML_ITEM.match(raw)

        if block_indent is not None:
            indent = len(raw) - len(raw.lstrip())
            if raw.strip() and indent <= block_indent:
                block_indent = None      # block ended; fall through and re-test
            else:
                if item_match:
                    # - FOO=bar   or   - FOO
                    entry = item_match.group(2).strip().strip("\"'")
                    name = entry.split("=", 1)[0].split(":", 1)[0].strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        out.add(EnvWriter(name, source))
                elif key_match:
                    name = key_match.group(2)
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        out.add(EnvWriter(name, source))
                continue

        if key_match:
            key = key_match.group(2)
            rest = key_match.group(3).strip()
            if key in ("environment", "env"):
                if rest.startswith("["):
                    for entry in rest.strip("[]").split(","):
                        name = entry.strip().strip("\"'").split("=", 1)[0]
                        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                            out.add(EnvWriter(name, source))
                elif not rest:
                    block_indent = len(key_match.group(1))
    return out


def _source_writes(path: Path, rel: str) -> list[EnvWriter]:
    """Names the source itself sets: `os.environ["X"] = ...`,
    `os.environ.setdefault("X", ...)`, and `process.env.X = ...`.

    Missing this was a real false-positive source, found by pointing the ledger
    at a repository whose `tests/__init__.py` sets seven variables at import
    time and then reads them back. Every one was reported as "read, never set".
    Config files are not the only writer, so they cannot be the only place we
    look (B-R27).
    """
    out: list[EnvWriter] = []
    if path.suffix == ".py":
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            return out
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "environ"
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        out.append(EnvWriter(target.slice.value, rel))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("setdefault", "update")
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"
            ):
                if node.func.attr == "setdefault" and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        out.append(EnvWriter(first.value, rel))
                elif node.args and isinstance(node.args[0], ast.Dict):
                    for key in node.args[0].keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            out.append(EnvWriter(key.value, rel))
    else:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return out
        for match in re.finditer(
            r"\bprocess\s*\.\s*env\s*(?:\.\s*([A-Z_][A-Z0-9_]*)|\[\s*[\"']([^\"']+)[\"']\s*\])\s*=(?!=)",
            source,
        ):
            out.append(EnvWriter(match.group(1) or match.group(2), rel))
    return out


def writers(root: Path, files: list[Path] | None = None) -> tuple[set[str], dict[str, str]]:
    """Every name the repository claims to provide, and where from.

    Returns (names, name -> source) so a finding can say not just that a value
    is set, but which file set it.
    """
    found: dict[str, str] = {}

    for path in sorted(files or []):
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            continue
        for writer in _source_writes(path, rel):
            found.setdefault(writer.name, writer.source)

    def record(name: str, source: str) -> None:
        found.setdefault(name, source)

    # .env family
    for pattern in (".env", ".env.*", "*.env"):
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.lstrip().startswith("#"):
                        continue
                    match = _DOTENV_LINE.match(line)
                    if match:
                        record(match.group(1), path.name)
            except OSError:
                continue

    # compose files
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        path = root / name
        if path.is_file():
            try:
                for writer in _scan_yaml_env(path.read_text(encoding="utf-8", errors="replace"), name):
                    record(writer.name, writer.source)
            except OSError:
                pass

    # vercel.json
    path = root / "vercel.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            for section in (data.get("env"), (data.get("build") or {}).get("env")):
                if isinstance(section, dict):
                    for key in section:
                        record(key, "vercel.json")
        except (json.JSONDecodeError, OSError, AttributeError):
            pass

    # Dockerfiles. `ENV NAME=value` and `ARG NAME` are how a containerised
    # service is actually configured, and a name set there is set. Not in the
    # A-R4 list, added because leaving it out produced a false positive on the
    # first real repository swept — the requirement's intent is "set nowhere",
    # and a Dockerfile is somewhere (B-R27).
    for path in sorted(root.rglob("Dockerfile*")):
        if not path.is_file() or any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            source = str(path.relative_to(root))
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                match = _DOCKER_ENV.match(line)
                if not match:
                    continue
                body = match.group(2)
                if match.group(1).upper() == "ARG":
                    name = body.split("=", 1)[0].strip()
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        record(name, source)
                    continue
                # `ENV A=1 B=2` and the legacy `ENV A 1` both occur.
                for pair in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", body):
                    record(pair.group(1), source)
                if "=" not in body:
                    name = body.split(None, 1)[0] if body.split() else ""
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        record(name, source)
        except OSError:
            continue

    # GitHub Actions
    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        for path in sorted(workflows.glob("*.y*ml")):
            try:
                rel = str(path.relative_to(root))
                for writer in _scan_yaml_env(path.read_text(encoding="utf-8", errors="replace"), rel):
                    record(writer.name, writer.source)
            except OSError:
                continue

    return set(found), found
