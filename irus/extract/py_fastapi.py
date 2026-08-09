"""A-R1: extract producer surfaces from FastAPI source using the stdlib ast.

We use `ast` rather than a generic parser because it is exact for Python, ships
with the interpreter, and cannot drift from the language.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..model import (
    JSON_ENC,
    MULTIPART,
    PRODUCER,
    URLENCODED,
    Field,
    Loc,
    Surface,
    normalise_path,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

_SCALARS = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "bytes": "bytes",
    "UUID": "str",
    "EmailStr": "str",
    "Decimal": "float",
    "datetime": "str",
    "date": "str",
}


def _ann_name(node: ast.AST | None) -> str:
    if node is None:
        return "unknown"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Subscript):
        return _ann_name(node.value)
    return "unknown"


def _normalise_type(node: ast.AST | None) -> tuple[str, bool]:
    """Return (type, optional). Optional means Optional[X] or X | None."""
    if node is None:
        return "unknown", False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, lo = _normalise_type(node.left)
        right, ro = _normalise_type(node.right)
        if right == "none":
            return left, True
        if left == "none":
            return right, True
        return left, lo or ro
    if isinstance(node, ast.Constant) and node.value is None:
        return "none", True
    if isinstance(node, ast.Subscript):
        outer = _ann_name(node.value)
        if outer in ("Optional",):
            inner, _ = _normalise_type(node.slice)
            return inner, True
        if outer in ("list", "List", "tuple", "Tuple", "set", "Set"):
            return "list", False
        if outer in ("dict", "Dict", "Mapping"):
            return "dict", False
        if outer == "Union":
            elts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            opt = any(isinstance(e, ast.Constant) and e.value is None for e in elts)
            for e in elts:
                t, _ = _normalise_type(e)
                if t != "none":
                    return t, opt
            return "unknown", opt
        return outer, False
    name = _ann_name(node)
    if name in _SCALARS:
        return _SCALARS[name], False
    if name in ("list", "List"):
        return "list", False
    if name in ("dict", "Dict"):
        return "dict", False
    return name, False


def _call_func_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        return _ann_name(node.func)
    return ""


class _Collector(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.tree: ast.AST | None = None
        self.models: dict[str, tuple[Field, ...]] = {}
        self.routers: dict[str, str] = {}  # variable name -> prefix
        self.apps: set[str] = set()
        self.included: set[str] = set()  # router vars passed to include_router
        self.include_prefix: dict[str, str] = {}
        self.unresolved_prefix: set[str] = set()
        # `from x.views import router as case_router` means the include site
        # names `case_router` while the declaring module names it `router`.
        # Without this map every aliased router reads as unmounted, which was
        # 277 high-confidence false positives on Netflix/dispatch alone.
        self.aliases: dict[str, str] = {}
        self.functions: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]] = []

    # ---- Pydantic models -------------------------------------------------
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = {_ann_name(b) for b in node.bases}
        if "BaseModel" in bases:
            fields: list[Field] = []
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    typ, optional = _normalise_type(stmt.annotation)
                    has_default = stmt.value is not None
                    if has_default and _call_func_name(stmt.value) == "Field":
                        # Field(...) with Ellipsis first arg means required
                        args = stmt.value.args  # type: ignore[union-attr]
                        if args and isinstance(args[0], ast.Constant) and args[0].value is Ellipsis:
                            has_default = False
                    fields.append(
                        Field(stmt.target.id, typ, required=not (optional or has_default))
                    )
            self.models[node.name] = tuple(fields)
        self.generic_visit(node)

    # ---- app / router objects -------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        fn = _call_func_name(node.value)
        if fn in ("FastAPI", "APIRouter"):
            prefix = ""
            for kw in node.value.keywords:  # type: ignore[union-attr]
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    prefix = str(kw.value.value)
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    if fn == "FastAPI":
                        self.apps.add(tgt.id)
                        self.routers[tgt.id] = prefix
                    else:
                        self.routers[tgt.id] = prefix
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.asname:
                self.aliases[alias.asname] = alias.name
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "include_router":
            if node.args:
                target = node.args[0]
                # A router is usually mounted from another module, so the
                # argument is `items.router`, not a bare `router`. Recording
                # only ast.Name marked every such route unmounted, which was 23
                # high-confidence false positives on the standard FastAPI
                # template. The attribute's own name is the local name the
                # router was declared under in its defining module.
                if isinstance(target, ast.Name):
                    name = target.id
                elif isinstance(target, ast.Attribute):
                    name = target.attr
                else:
                    name = ""
                if name:
                    self.included.add(name)
                    for kw in node.keywords:
                        if kw.arg != "prefix":
                            continue
                        if isinstance(kw.value, ast.Constant):
                            self.include_prefix[name] = str(kw.value.value)
                        else:
                            # A prefix we cannot evaluate (settings.API_V1_STR)
                            # means every path under it is unknown. Say so
                            # rather than reporting a path that is wrong.
                            self.unresolved_prefix.add(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append((node, self.path))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]


def _body_from_signature(
    func: ast.FunctionDef | ast.AsyncFunctionDef, models: dict[str, tuple[Field, ...]]
) -> tuple[str, tuple[Field, ...]]:
    """Decide the request encoding and body fields from handler parameters."""
    args = list(func.args.args) + list(func.args.kwonlyargs)
    defaults: dict[str, ast.AST] = {}
    pos = func.args.args
    for name, d in zip([a.arg for a in pos[len(pos) - len(func.args.defaults):]], func.args.defaults):
        defaults[name] = d
    for a, d in zip(func.args.kwonlyargs, func.args.kw_defaults):
        if d is not None:
            defaults[a.arg] = d

    form_fields: list[Field] = []
    encoding = ""
    for a in args:
        ann = _ann_name(a.annotation)
        marker = _call_func_name(defaults.get(a.arg)) if a.arg in defaults else ""
        typ, optional = _normalise_type(a.annotation)
        required = not optional
        if a.arg in defaults and marker not in ("File", "Form", "Body"):
            required = False

        if ann in ("UploadFile",) or marker == "File":
            encoding = MULTIPART
            form_fields.append(Field(a.arg, "file", required))
        elif marker == "Form":
            if encoding != MULTIPART:
                encoding = URLENCODED
            form_fields.append(Field(a.arg, typ, required))
        elif ann in models:
            return JSON_ENC, models[ann]
        elif marker == "Body":
            return JSON_ENC, (Field(a.arg, typ, required),)

    if form_fields:
        return encoding or URLENCODED, tuple(form_fields)
    return "none", ()


def collect(path: Path, root: Path, src: str | None = None) -> tuple[_Collector, str] | None:
    """Parse a file once and keep the collector.

    Callers need three things from a FastAPI module (its router mounts, its
    routes, and its env reads) and each was previously a separate parse of the
    same bytes. One parse, reused, is the whole optimisation.
    """
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (SyntaxError, OSError, ValueError):
        return None
    rel = str(path.relative_to(root)).replace("\\", "/")
    col = _Collector(rel)
    col.visit(tree)
    col.tree = tree
    return col, rel


_parse = collect


def resolve_aliases(included: set[str], aliases: dict[str, str]) -> set[str]:
    """Expand an include set with the names those includes actually refer to."""
    return included | {aliases[name] for name in included if name in aliases}


def file_includes(
    path: Path, root: Path, src: str | None = None
) -> tuple[set[str], dict[str, str]]:
    """Routers included anywhere in this file, for the project-wide mount pass.

    A router is normally defined in one module and mounted in another, so
    mounting cannot be decided from a single file.
    """
    parsed = collect(path, root, src)
    if parsed is None:
        return set(), {}
    col, _ = parsed
    return col.included, col.include_prefix


def extract_file(
    path: Path,
    root: Path,
    included: set[str] | None = None,
    include_prefix: dict[str, str] | None = None,
    src: str | None = None,
) -> list[Surface]:
    parsed = collect(path, root, src)
    if parsed is None:
        return []
    col, rel = parsed
    return surfaces_from(col, rel, included, include_prefix)


def surfaces_from(
    col: "_Collector",
    rel: str,
    included: set[str] | None = None,
    include_prefix: dict[str, str] | None = None,
) -> list[Surface]:
    """Resolve routes from an already-parsed collector. No I/O, no parsing."""
    if included:
        col.included |= included
    if include_prefix:
        merged = dict(include_prefix)
        merged.update(col.include_prefix)
        col.include_prefix = merged

    surfaces: list[Surface] = []
    for func, _ in col.functions:
        for dec in func.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            if not isinstance(f, ast.Attribute) or f.attr not in HTTP_METHODS:
                continue
            owner = _ann_name(f.value)
            if owner not in col.routers:
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant):
                continue

            route = str(dec.args[0].value)
            # Mount prefix comes first, then the router's own prefix, then the
            # decorator path: include_router(r, prefix="/api") + APIRouter(
            # prefix="/users") + @r.get("/{id}") is /api/users/{id}.
            prefix = col.include_prefix.get(owner, "") + col.routers.get(owner, "")
            full = normalise_path(prefix + route)

            encoding, fields = _body_from_signature(func, col.models)

            resp: tuple[Field, ...] = ()
            for kw in dec.keywords:
                if kw.arg == "response_model":
                    resp = col.models.get(_ann_name(kw.value), ())

            mounted = owner in col.apps or owner in col.included
            unresolved = owner in getattr(col, "unresolved_prefix", set())

            surfaces.append(
                Surface(
                    side=PRODUCER,
                    method=f.attr.upper(),
                    path=full,
                    loc=Loc(rel, func.lineno),
                    encoding=encoding,
                    fields=fields,
                    response_fields=resp,
                    mounted=mounted,
                    external=unresolved,
                )
            )
    return surfaces
