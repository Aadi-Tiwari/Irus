"""A-R4: environment variables read in source but set nowhere.

Prior art check (Aug 2026) found this genuinely unoccupied: dotenv-linter only
lints `.env` syntax and never reads source, knip has no env issue types, and
Python's `os.environ["X"]` is a string-keyed dict lookup that AST linters do not
follow. Nothing cross-references code against CI configuration.

A read that supplies a default is not a failure and is never reported.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..model import EnvRead, Loc

try:  # optional; a regex fallback covers the case where PyYAML is absent
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


_JS_READS = [
    re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"process\.env\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
    re.compile(r"import\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
]

# A read is "defaulted", and therefore not a failure, when the code already
# copes with it being absent. Three shapes, all found in real repositories:
#   process.env.X || "fallback"      an explicit fallback
#   process.env.X ?? "fallback"      the same, nullish
#   process.env.X ? a : b            a ternary that branches on absence
#   !!process.env.CI                 a presence check, never a requirement
_JS_DEFAULTED = re.compile(
    r"(?:process\.env|import\.meta\.env)(?:\.|\[\s*['\"])([A-Za-z_][A-Za-z0-9_]*)"
    r"(?:['\"]\s*\])?\s*(?:\|\||\?\?|\?[^.])"
)
_JS_PRESENCE = re.compile(
    r"(?:!!?|Boolean\(\s*)(?:process\.env|import\.meta\.env)"
    r"(?:\.|\[\s*['\"])([A-Za-z_][A-Za-z0-9_]*)"
)

_KV = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[:=]", re.M)
_YAML_ENVLIST = re.compile(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\s*[=:]", re.M)


def py_reads_from_tree(tree: ast.AST, rel: str) -> list[EnvRead]:
    out: list[EnvRead] = []

    def name_of(node: ast.AST) -> str:
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Name):
            return node.id
        return ""

    for node in ast.walk(tree):
        # os.environ["X"]
        if isinstance(node, ast.Subscript) and name_of(node.value) == "environ":
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.append(EnvRead(key.value, Loc(rel, node.lineno), has_default=False))
        # os.environ.get("X"), os.getenv("X")
        if isinstance(node, ast.Call):
            fn = node.func
            is_get = isinstance(fn, ast.Attribute) and (
                fn.attr == "getenv"
                or (fn.attr == "get" and name_of(fn.value) == "environ")
            )
            if is_get and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    has_default = len(node.args) > 1 or bool(node.keywords)
                    out.append(EnvRead(first.value, Loc(rel, node.lineno), has_default))
    return out


def _py_reads(path: Path, rel: str, src: str | None = None) -> list[EnvRead]:
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (SyntaxError, OSError, ValueError):
        return []
    return py_reads_from_tree(tree, rel)


def js_reads_from_source(src: str, rel: str) -> list[EnvRead]:
    defaulted = {m.group(1) for m in _JS_DEFAULTED.finditer(src)}
    defaulted |= {m.group(1) for m in _JS_PRESENCE.finditer(src)}
    out: list[EnvRead] = []
    for pattern in _JS_READS:
        for m in pattern.finditer(src):
            name = m.group(1)
            line = src.count("\n", 0, m.start()) + 1
            out.append(EnvRead(name, Loc(rel, line), has_default=name in defaulted))
    return out


def _js_reads(path: Path, rel: str, src: str | None = None) -> list[EnvRead]:
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return js_reads_from_source(src, rel)


def reads_in(path: Path, root: Path, src: str | None = None) -> list[EnvRead]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    if path.suffix == ".py":
        return _py_reads(path, rel, src)
    if path.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        return _js_reads(path, rel, src)
    return []


def _yaml_names(text: str) -> set[str]:
    """Names a YAML config supplies, via a parse when possible, regex otherwise."""
    names: set[str] = set()
    if yaml is not None:
        try:
            doc = yaml.safe_load(text)
        except Exception:
            doc = None
        if doc is not None:
            def walk(node: object, under_env: bool) -> None:
                if isinstance(node, dict):
                    for k, v in node.items():
                        key = str(k)
                        if key in ("environment", "env", "secrets", "variables"):
                            if isinstance(v, dict):
                                names.update(str(x) for x in v)
                            elif isinstance(v, list):
                                for item in v:
                                    names.add(str(item).split("=")[0].split(":")[0].strip())
                            walk(v, True)
                        else:
                            if under_env and not isinstance(v, (dict, list)):
                                names.add(key)
                            walk(v, False)
                elif isinstance(node, list):
                    for item in node:
                        walk(item, under_env)
            walk(doc, False)
            return names
    names.update(m.group(1) for m in _KV.finditer(text))
    names.update(m.group(1) for m in _YAML_ENVLIST.finditer(text))
    return names


def declared_names(root: Path) -> dict[str, str]:
    """Every env name the project declares anywhere, mapped to its source file."""
    found: dict[str, str] = {}

    def add(names: set[str], where: str) -> None:
        for n in names:
            if n and n not in found:
                found[n] = where

    # A monorepo declares env in more than one place: frontend/.env is as real
    # as ./.env, and compose.override.yml is as real as compose.yml. Searching
    # only the root produced three high-confidence false positives on the
    # standard FastAPI template.
    skip = {"node_modules", ".git", ".venv", "venv", "dist", "build", ".next"}

    def nested(patterns: tuple[str, ...]) -> list[Path]:
        out: list[Path] = []
        for pattern in patterns:
            for f in root.rglob(pattern):
                if f.is_file() and not any(part in skip for part in f.parts):
                    out.append(f)
        return out

    for f in nested((".env", ".env.*", "*.env")):
        rel = f.relative_to(root).as_posix()
        add({m.group(1) for m in _KV.finditer(f.read_text("utf-8", errors="replace"))}, rel)

    for f in nested(("docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml")):
        rel = f.relative_to(root).as_posix()
        add(_yaml_names(f.read_text("utf-8", errors="replace")), rel)

    vercel = root / "vercel.json"
    if vercel.is_file():
        try:
            import json

            doc = json.loads(vercel.read_text("utf-8", errors="replace"))
            names = set()
            for key in ("env", "build"):
                block = doc.get(key)
                if isinstance(block, dict):
                    names.update(block.get("env", block) if key == "build" else block)
            add({str(n) for n in names}, "vercel.json")
        except Exception:
            pass

    wf = root / ".github" / "workflows"
    if wf.is_dir():
        for f in list(wf.glob("*.yml")) + list(wf.glob("*.yaml")):
            text = f.read_text("utf-8", errors="replace")
            add(_yaml_names(text), f".github/workflows/{f.name}")
            # `${{ secrets.FOO }}` means the platform supplies FOO.
            add(
                {m.group(1) for m in re.finditer(r"\$\{\{\s*secrets\.([A-Za-z_][A-Za-z0-9_]*)", text)},
                f".github/workflows/{f.name}",
            )

    return found
