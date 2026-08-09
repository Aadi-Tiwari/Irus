"""Producer side: what the FastAPI server declares it accepts.

Stage 1 is a pure function of the working tree (B-R1), so this module uses the
stdlib `ast` module and nothing else. No imports of the target code are
executed — importing user code to inspect it would run it, which is exactly the
line stage 1 exists on the safe side of.

Scope is deliberately narrow (PRD-B section 7, first risk): decorated FastAPI
routes and Pydantic models declared with annotated class attributes. Anything
outside that is reported as `unknown` rather than guessed at.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


@dataclass
class Model:
    name: str
    path: str
    line: int
    fields: dict[str, str] = field(default_factory=dict)   # name -> type
    required: set[str] = field(default_factory=set)


@dataclass
class Route:
    method: str
    path: str
    handler: str
    file: str
    line: int
    model_name: str | None = None
    model: Model | None = None
    # "json" unless the handler takes File/Form parameters, which is how a
    # FastAPI endpoint says it wants multipart instead.
    encoding: str = "json"

    @property
    def seam(self) -> str:
        return f"{self.method} {self.path}"


def _annotation_name(node: ast.AST | None) -> str:
    """Render an annotation to a short type name. Deliberately lossy: we only
    need enough to say 'this side wants int, that side sends str'."""
    if node is None:
        return "unknown"
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return "None" if node.value is None else type(node.value).__name__
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        base = _annotation_name(node.value)
        inner = node.slice
        if base in ("Optional",):
            return _annotation_name(inner)
        if base in ("list", "List"):
            return "list"
        if base in ("dict", "Dict"):
            return "dict"
        return base
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # `str | None` — the modern Optional. Report the non-None half.
        left = _annotation_name(node.left)
        right = _annotation_name(node.right)
        return left if right == "None" else right
    return "unknown"


def _is_optional(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Subscript) and _annotation_name(node.value) == "Optional":
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return "None" in (_annotation_name(node.left), _annotation_name(node.right))
    return False


def _base_names(cls: ast.ClassDef) -> set[str]:
    out = set()
    for base in cls.bases:
        if isinstance(base, ast.Name):
            out.add(base.id)
        elif isinstance(base, ast.Attribute):
            out.add(base.attr)
    return out


def _string_arg(call: ast.Call, index: int = 0) -> str | None:
    if len(call.args) > index and isinstance(call.args[index], ast.Constant):
        value = call.args[index].value
        if isinstance(value, str):
            return value
    return None


def _keyword_string(call: ast.Call, name: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


class _FileScan(ast.NodeVisitor):
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self.models: dict[str, Model] = {}
        self.routes: list[Route] = []
        # Router variable -> path prefix. `APIRouter(prefix="/api")` changes
        # the real URL, and missing it would manufacture a false mismatch on
        # every route in the file.
        self.prefixes: dict[str, str] = {}

    # ---- models

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if _base_names(node) & {"BaseModel"}:
            model = Model(name=node.name, path=self.rel_path, line=node.lineno)
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    fname = stmt.target.id
                    model.fields[fname] = _annotation_name(stmt.annotation)
                    # Required means: no default value and not Optional.
                    if stmt.value is None and not _is_optional(stmt.annotation):
                        model.required.add(fname)
            self.models[node.name] = model
        self.generic_visit(node)

    # ---- router prefixes

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            fn = node.value.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if fname == "APIRouter":
                prefix = _keyword_string(node.value, "prefix") or ""
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.prefixes[target.id] = prefix
        self.generic_visit(node)

    # ---- routes

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            method = dec.func.attr.lower()
            if method not in HTTP_METHODS:
                continue
            route_path = _string_arg(dec)
            if route_path is None:
                continue
            # A route path is always rooted. Without this, `@mock.patch("x.y.Z")`
            # reads as a PATCH route on "x.y.Z" — which it did, across every
            # test file of the first real repository this was pointed at, and
            # then poisoned every downstream no-route finding. Found by running
            # the ledger, fixed here rather than filtered downstream (B-R27).
            if not route_path.startswith("/"):
                continue
            owner = dec.func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else ""
            full_path = self.prefixes.get(owner_name, "") + route_path

            route = Route(
                method=method.upper(),
                path=full_path,
                handler=node.name,
                file=self.rel_path,
                line=node.lineno,
            )
            self._attach_body(route, node)
            self.routes.append(route)

    visit_FunctionDef = _handle_function          # type: ignore[assignment]
    visit_AsyncFunctionDef = _handle_function     # type: ignore[assignment]

    def _attach_body(self, route: Route, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Find the parameter that carries the request body, and notice when
        the handler is asking for form/multipart instead of JSON."""
        args = list(node.args.args) + list(node.args.kwonlyargs)
        for arg in args:
            ann = arg.annotation
            if ann is None:
                continue
            # File(...) / Form(...) defaults mean multipart, not JSON.
            name = _annotation_name(ann)
            if name in ("UploadFile",):
                route.encoding = "multipart"
            if name in self.models or name not in ("Request", "Response", "BackgroundTasks"):
                if name in self.models or name[:1].isupper():
                    route.model_name = name
        # Form(...) as a default marks every parameter as form-encoded.
        defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d]
        for default in defaults:
            if isinstance(default, ast.Call):
                fn = default.func
                fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if fname in ("Form", "File"):
                    route.encoding = "multipart"


def scan_file(path: Path, root: Path) -> tuple[list[Route], dict[str, Model]]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        # An unparseable file is not a finding. Stage 1 reports disagreements
        # it can prove, never "I could not read this".
        return [], {}
    scan = _FileScan(str(path.relative_to(root)))
    scan.visit(tree)
    return scan.routes, scan.models


def extract(files: list[Path], root: Path) -> list[Route]:
    """All routes across the given Python files, with models resolved.

    Sorted by seam so the output order is a function of content, not of the
    order the filesystem happened to hand us the files (B-R1).
    """
    all_routes: list[Route] = []
    all_models: dict[str, Model] = {}
    for path in sorted(files):
        routes, models = scan_file(path, root)
        all_routes.extend(routes)
        for name, model in models.items():
            all_models.setdefault(name, model)
    for route in all_routes:
        if route.model_name:
            route.model = all_models.get(route.model_name)
            if route.model is None:
                # Named a type we never saw declared. Leave `model` None so the
                # comparator downgrades confidence rather than inventing a shape.
                route.model_name = route.model_name
    return sorted(all_routes, key=lambda r: (r.path, r.method, r.file))
