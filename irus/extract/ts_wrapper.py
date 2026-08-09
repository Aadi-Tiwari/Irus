"""Resolve one hop of indirection through a project-local fetch wrapper.

Found by Gate B, on code two real agents wrote without being told what to
produce. Neither wrote an inline `fetch`. The frontend agent wrote a shared
helper:

    export async function sendJson<T>(method, path, body) {
      const response = await fetch(url(path), { method, headers: {...},
                                                body: JSON.stringify(body) });
      ...
    }

and then every feature called *that*:

    sendJson<Profile>("PUT", "/profile", request)

The contract lives entirely in the call site, and a scanner that only reads
`fetch(` sees a wrapper with a variable path and reports nothing at all. Irus
missed a real mismatch on real agent output for exactly this reason.

One hop is deliberate. Following an arbitrary chain means building a call graph
and an interprocedural analysis, and every extra hop multiplies the chance of
attributing a body to the wrong request. One hop covers the shape agents
actually produce, and anything deeper is reported as unknown, which never
becomes a high-confidence finding.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model import (
    CONSUMER,
    JSON_ENC,
    MULTIPART,
    UNKNOWN_ENC,
    URLENCODED,
    Field,
    Loc,
    Surface,
    normalise_path,
)
from .ts_fetch import (
    _IDENT,
    literal_string,
    mask,
    match_bracket,
    object_fields,
    split_top,
    value_type,
)

METHOD_LITERAL = re.compile(r'["\'`](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)["\'`]', re.I)


class Wrapper:
    """A project function whose body issues a fetch, described by parameter."""

    def __init__(self, name: str, params: list[str], encoding: str,
                 method_param: int | None, path_param: int | None,
                 body_param: int | None, fixed_method: str | None) -> None:
        self.name = name
        self.params = params
        self.encoding = encoding
        self.method_param = method_param
        self.path_param = path_param
        self.body_param = body_param
        self.fixed_method = fixed_method


_FUNC = re.compile(
    rf"export\s+(?:async\s+)?function\s+({_IDENT})\s*(?:<[^>]*>)?\s*\("
)


def _params_of(src: str, masked: str, open_paren: int) -> tuple[list[str], int]:
    close = match_bracket(masked, open_paren)
    if close < 0:
        return [], open_paren
    inner_s, inner_m = src[open_paren + 1 : close - 1], masked[open_paren + 1 : close - 1]
    names: list[str] = []
    for a, b in split_top(inner_s, inner_m):
        raw = inner_s[a:b].strip()
        name = raw.split(":")[0].split("=")[0].strip()
        if re.fullmatch(_IDENT, name):
            names.append(name)
    return names, close


def find_wrappers(src: str, masked: str) -> dict[str, Wrapper]:
    """Exported functions that call fetch using their own parameters."""
    out: dict[str, Wrapper] = {}
    for m in _FUNC.finditer(masked):
        name = m.group(1)
        params, close = _params_of(src, masked, m.end() - 1)
        if not params:
            continue
        brace = masked.find("{", close)
        if brace == -1:
            continue
        end = match_bracket(masked, brace)
        if end < 0:
            continue
        body_s, body_m = src[brace:end], masked[brace:end]
        if "fetch" not in body_s:
            continue

        encoding = UNKNOWN_ENC
        if "JSON.stringify" in body_s or "application/json" in body_s:
            encoding = JSON_ENC
        if "FormData" in body_s or "multipart/form-data" in body_s:
            encoding = MULTIPART
        if "URLSearchParams" in body_s or "x-www-form-urlencoded" in body_s:
            encoding = URLENCODED

        # Which parameter reaches which part of the request.
        def used_as(pattern: str) -> int | None:
            for index, param in enumerate(params):
                if re.search(pattern.replace("PARAM", re.escape(param)), body_s):
                    return index
            return None

        # The path is whatever the fetch call is actually handed as its first
        # argument. Guessing it from a lookahead matched `body` inside
        # `JSON.stringify(body)` and silently attributed the wrong parameter.
        path_param = None
        call = re.search(r"fetch\s*\(", body_m)
        if call:
            fetch_open = call.end() - 1
            fetch_close = match_bracket(body_m, fetch_open)
            if fetch_close > 0:
                fetch_args_s = body_s[fetch_open + 1 : fetch_close - 1]
                fetch_args_m = body_m[fetch_open + 1 : fetch_close - 1]
                fetch_spans = split_top(fetch_args_s, fetch_args_m)
                if fetch_spans:
                    lo, hi = fetch_spans[0]
                    first_arg = fetch_args_s[lo:hi]
                    for index, param in enumerate(params):
                        if re.search(rf"\b{re.escape(param)}\b", first_arg):
                            path_param = index
                            break

        method_param = used_as(r"method\s*:\s*PARAM\b")
        if method_param is None and "method" in params:
            # ES6 shorthand: `fetch(url, { method, headers })` passes the
            # variable `method` as the property `method`. Real agent code is
            # written that way, and matching only `method: method` turned every
            # PUT and POST into a GET.
            if re.search(r"\{[^{}]*\bmethod\b\s*[,}]", body_s):
                method_param = params.index("method")
        body_param = used_as(r"JSON\.stringify\(\s*PARAM\s*\)") or used_as(r"body\s*:\s*PARAM\b")

        fixed = None
        literal = METHOD_LITERAL.search(body_s)
        if method_param is None and literal:
            fixed = literal.group(1).upper()
        elif method_param is None and re.search(r'method\s*:\s*["\']GET', body_s):
            fixed = "GET"
        if method_param is None and fixed is None:
            fixed = "GET"

        out[name] = Wrapper(name, params, encoding, method_param, path_param,
                            body_param, fixed)
    return out


def _line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def extract_calls(
    path: Path, root: Path, wrappers: dict[str, Wrapper],
    src: str | None = None, masked: str | None = None,
) -> list[Surface]:
    """Consumer surfaces from calls to a known wrapper."""
    if not wrappers:
        return []
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if masked is None:
        masked = mask(src)
    rel = str(path.relative_to(root)).replace("\\", "/")

    names = "|".join(re.escape(n) for n in wrappers)
    pattern = re.compile(rf"\b({names})\s*(?:<[^>()]*>)?\s*\(")

    out: list[Surface] = []
    for m in pattern.finditer(masked):
        wrapper = wrappers[m.group(1)]
        open_paren = masked.find("(", m.end() - 1)
        if open_paren == -1:
            continue
        close = match_bracket(masked, open_paren)
        if close < 0:
            continue
        args_s = src[open_paren + 1 : close - 1]
        args_m = masked[open_paren + 1 : close - 1]
        spans = split_top(args_s, args_m)
        if not spans:
            continue

        def arg(index: int | None) -> tuple[str, str] | None:
            if index is None or index >= len(spans):
                return None
            a, b = spans[index]
            return args_s[a:b], args_m[a:b]

        url_arg = arg(wrapper.path_param)
        if url_arg is None:
            continue
        url = literal_string(url_arg[0].strip())
        if url is None or "://" in url:
            continue

        method = wrapper.fixed_method or "GET"
        method_arg = arg(wrapper.method_param)
        if method_arg is not None:
            literal = literal_string(method_arg[0].strip())
            if literal:
                method = literal.upper()

        fields: tuple[Field, ...] = ()
        body_arg = arg(wrapper.body_param)
        if body_arg is not None:
            body_s, body_m = body_arg
            brace = body_m.find("{")
            if brace != -1 and not body_s[:brace].strip():
                fields = object_fields(body_s, body_m, brace) or ()
            else:
                ident = body_s.strip()
                if re.fullmatch(_IDENT, ident):
                    fields = _interface_fields(src, masked, ident) or ()

        out.append(Surface(
            side=CONSUMER,
            method=method,
            path=normalise_path(url),
            loc=Loc(rel, _line_of(src, m.start())),
            encoding=wrapper.encoding,
            fields=fields,
        ))
    return out


_PARAM_TYPE = re.compile(rf"\b(?:PARAM)\s*:\s*({_IDENT})")


def _interface_fields(src: str, masked: str, ident: str) -> tuple[Field, ...] | None:
    """Fields of the TypeScript interface a wrapper argument is typed with.

    Agents type their request objects. `request: UpdateProfileRequest` names the
    contract precisely, and reading the interface is how the field names become
    visible at all when the object is built elsewhere.
    """
    typed = _PARAM_TYPE.pattern.replace("PARAM", re.escape(ident))
    m = re.search(typed, src)
    if not m:
        return None
    name = m.group(1)
    decl = re.search(rf"interface\s+{re.escape(name)}\s*\{{", masked)
    if not decl:
        return None
    brace = masked.find("{", decl.start())
    end = match_bracket(masked, brace)
    if end < 0:
        return None
    body = src[brace + 1 : end - 1]
    fields: list[Field] = []
    for line in body.splitlines():
        entry = line.strip().rstrip(";,")
        if not entry or entry.startswith("//"):
            continue
        if ":" not in entry:
            continue
        key, _, typename = entry.partition(":")
        key = key.strip().rstrip("?")
        if not re.fullmatch(_IDENT, key):
            continue
        t = typename.strip()
        kind = ("str" if t.startswith("string") else
                "int" if t.startswith("number") else
                "bool" if t.startswith("boolean") else "unknown")
        fields.append(Field(key, kind, required="?" not in entry.split(":")[0]))
    return tuple(fields) or None
