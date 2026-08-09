"""A-R7: a second producer stack pair, Express on Node.

Proves the extractor interface is not welded to FastAPI. Same Surface output,
so compare.py needs no knowledge of which stack produced a side.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import JSON_ENC, MULTIPART, PRODUCER, Field, Loc, Surface, normalise_path
from .ts_fetch import _IDENT, literal_string, mask, match_bracket, split_top

METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "all")

_ROUTE = re.compile(rf"\b({_IDENT})\.({'|'.join(METHODS)})\s*\(")
_ROUTER_DECL = re.compile(
    rf"(?:const|let|var)\s+({_IDENT})\s*=\s*(?:express\.Router|Router)\s*\("
)
_APP_DECL = re.compile(rf"(?:const|let|var)\s+({_IDENT})\s*=\s*express\s*\(")
_USE = re.compile(rf"\b{_IDENT}\.use\s*\(")
_DESTRUCTURE = re.compile(r"(?:const|let|var)\s*\{([^}]*)\}\s*=\s*req\.body")
_MEMBER = re.compile(r"\breq\.body\.([A-Za-z_$][\w$]*)")


def _line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def _mounts(src: str, masked: str) -> dict[str, str]:
    """Router variable -> mount prefix, from app.use('/api', router)."""
    out: dict[str, str] = {}
    for m in _USE.finditer(masked):
        open_paren = m.end() - 1
        close = match_bracket(masked, open_paren)
        if close < 0:
            continue
        inner_s = src[open_paren + 1 : close - 1]
        inner_m = masked[open_paren + 1 : close - 1]
        spans = split_top(inner_s, inner_m)
        if len(spans) < 2:
            continue
        a, b = spans[0]
        prefix = literal_string(inner_s[a:b])
        if prefix is None:
            continue
        c, d = spans[1]
        target = inner_s[c:d].strip()
        if re.fullmatch(_IDENT, target):
            out[target] = prefix
    return out


def _body_fields(handler_src: str) -> tuple[Field, ...]:
    names: list[str] = []
    for m in _DESTRUCTURE.finditer(handler_src):
        for part in m.group(1).split(","):
            name = part.split(":")[0].strip()
            if re.fullmatch(_IDENT, name):
                names.append(name)
    for m in _MEMBER.finditer(handler_src):
        names.append(m.group(1))
    seen: list[Field] = []
    for n in dict.fromkeys(names):
        seen.append(Field(n, "unknown"))
    return tuple(seen)


def extract_file(
    path: Path, root: Path, src: str | None = None, masked: str | None = None
) -> list[Surface]:
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if "express" not in src and "Router(" not in src:
        return []
    if masked is None:
        masked = mask(src)

    rel = str(path.relative_to(root)).replace("\\", "/")
    routers = {m.group(1) for m in _ROUTER_DECL.finditer(masked)}
    apps = {m.group(1) for m in _APP_DECL.finditer(masked)}
    mounts = _mounts(src, masked)
    multipart = "multer" in src

    surfaces: list[Surface] = []
    for m in _ROUTE.finditer(masked):
        owner, method = m.group(1), m.group(2)
        if owner not in routers and owner not in apps:
            continue
        open_paren = m.end() - 1
        close = match_bracket(masked, open_paren)
        if close < 0:
            continue
        inner_s = src[open_paren + 1 : close - 1]
        inner_m = masked[open_paren + 1 : close - 1]
        spans = split_top(inner_s, inner_m)
        if not spans:
            continue
        a, b = spans[0]
        route = literal_string(inner_s[a:b])
        if route is None:
            continue

        handler = inner_s[spans[-1][0] : spans[-1][1]] if len(spans) > 1 else ""
        fields = _body_fields(handler)
        encoding = "none"
        if method in ("post", "put", "patch"):
            encoding = MULTIPART if multipart else JSON_ENC

        prefix = mounts.get(owner, "")
        mounted = owner in apps or owner in mounts

        surfaces.append(
            Surface(
                side=PRODUCER,
                method=method.upper(),
                path=normalise_path(prefix + route),
                loc=Loc(rel, _line_of(src, m.start())),
                encoding=encoding,
                fields=fields,
                mounted=mounted,
            )
        )
    return surfaces
