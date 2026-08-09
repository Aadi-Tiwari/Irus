"""A-R2: extract consumer surfaces from TypeScript and JavaScript.

Dependency-free by design. A real TS parser would resolve types better, but it
would also mean a Node toolchain in the verification path, and every finding
this produces has to survive with no network and no install step.

The tradeoff is stated rather than hidden: this reads *literal* request
construction. A body assembled through a helper it cannot follow is reported as
`unknown`, and an unknown never produces a high-confidence mismatch.
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

OPEN = {"(": ")", "{": "}", "[": "]"}
CLOSE = {v: k for k, v in OPEN.items()}


def mask(src: str) -> str:
    """Blank out string, template and comment *contents*, preserving offsets.

    Structural scanning then cannot be fooled by a brace inside a string.
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                out[i] = " "
                i += 1
            for _ in range(2):
                if i < n:
                    out[i] = " "
                    i += 1
            continue
        if c in "\"'`":
            quote = c
            i += 1
            depth = 0
            while i < n:
                ch = src[i]
                if ch == "\\":
                    out[i] = " "
                    if i + 1 < n:
                        out[i + 1] = " "
                    i += 2
                    continue
                if quote == "`" and ch == "$" and i + 1 < n and src[i + 1] == "{":
                    depth += 1
                    out[i] = " "
                    out[i + 1] = " "
                    i += 2
                    continue
                if quote == "`" and ch == "}" and depth:
                    depth -= 1
                    out[i] = " "
                    i += 1
                    continue
                if ch == quote and depth == 0:
                    i += 1
                    break
                out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)


def match_bracket(masked: str, start: int) -> int:
    """Index just past the bracket group opening at `start`, or -1."""
    if masked[start] not in OPEN:
        return -1
    stack = [masked[start]]
    i = start + 1
    while i < len(masked) and stack:
        c = masked[i]
        if c in OPEN:
            stack.append(c)
        elif c in CLOSE:
            if stack and stack[-1] == CLOSE[c]:
                stack.pop()
            else:
                return -1
        i += 1
    return i if not stack else -1


def split_top(src: str, masked: str, sep: str = ",") -> list[tuple[int, int]]:
    """Spans of top-level separator-delimited parts."""
    parts: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for i, c in enumerate(masked):
        if c in OPEN:
            depth += 1
        elif c in CLOSE:
            depth -= 1
        elif c == sep and depth == 0:
            parts.append((start, i))
            start = i + 1
    parts.append((start, len(src)))
    return [(a, b) for a, b in parts if src[a:b].strip()]


_TEMPLATE_SUB = re.compile(r"\$\{[^}]*\}")


def literal_string(text: str) -> str | None:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    if len(t) >= 2 and t[0] == "`" and t[-1] == "`":
        return _TEMPLATE_SUB.sub("{}", t[1:-1])
    return None


def value_type(text: str) -> str:
    t = text.strip()
    if not t:
        return "unknown"
    if literal_string(t) is not None:
        return "str"
    if re.fullmatch(r"-?\d+", t):
        return "int"
    if re.fullmatch(r"-?\d*\.\d+", t):
        return "float"
    if t in ("true", "false"):
        return "bool"
    if t.startswith("{"):
        return "dict"
    if t.startswith("["):
        return "list"
    return "unknown"


def object_fields(src: str, masked: str, start: int) -> tuple[Field, ...] | None:
    """Parse a `{ a: 1, b, ...c }` literal into fields. None if not an object."""
    if start >= len(src) or masked[start] != "{":
        return None
    end = match_bracket(masked, start)
    if end < 0:
        return None
    inner_s, inner_m = src[start + 1 : end - 1], masked[start + 1 : end - 1]
    fields: list[Field] = []
    for a, b in split_top(inner_s, inner_m):
        part_s, part_m = inner_s[a:b], inner_m[a:b]
        if part_s.strip().startswith("..."):
            # A spread means we cannot know the full field set.
            fields.append(Field("...", "unknown", required=False))
            continue
        colon = part_m.find(":")
        if colon == -1:
            name = part_s.strip().strip("'\"")
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                fields.append(Field(name, "unknown"))
            continue
        key = part_s[:colon].strip().strip("'\"")
        val = part_s[colon + 1 :]
        if re.fullmatch(r"[A-Za-z_$][\w$]*", key):
            fields.append(Field(key, value_type(val)))
    return tuple(fields)


_IDENT = r"[A-Za-z_$][\w$]*"
_FORMDATA = re.compile(rf"(?:const|let|var)\s+({_IDENT})\s*=\s*new\s+FormData\s*\(")
_URLPARAMS = re.compile(rf"(?:const|let|var)\s+({_IDENT})\s*=\s*new\s+URLSearchParams\s*\(")
_CALLS = re.compile(rf"\b(?:fetch|axios(?:\.({_IDENT}))?)\s*\(")


def _formdata_fields(src: str, masked: str, var: str) -> tuple[Field, ...]:
    out: list[Field] = []
    for m in re.finditer(rf"\b{re.escape(var)}\.append\s*\(", masked):
        end = match_bracket(masked, m.end() - 1)
        if end < 0:
            continue
        inner_s = src[m.end() : end - 1]
        inner_m = masked[m.end() : end - 1]
        parts = split_top(inner_s, inner_m)
        if not parts:
            continue
        a, b = parts[0]
        key = literal_string(inner_s[a:b])
        if key:
            typ = "unknown"
            if len(parts) > 1:
                c, d = parts[1]
                typ = value_type(inner_s[c:d])
            out.append(Field(key, typ))
    return tuple(out)


def _assigned_object(src: str, masked: str, var: str) -> tuple[Field, ...] | None:
    m = re.search(rf"(?:const|let|var)\s+{re.escape(var)}\s*(?::[^=]+)?=\s*", masked)
    if not m:
        return None
    return object_fields(src, masked, m.end())


def _line_of(src: str, idx: int) -> int:
    return src.count("\n", 0, idx) + 1


def extract_file(
    path: Path, root: Path, src: str | None = None, masked: str | None = None
) -> list[Surface]:
    try:
        if src is None:
            src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if masked is None:
        masked = mask(src)
    rel = str(path.relative_to(root)).replace("\\", "/")
    surfaces: list[Surface] = []

    formdata_vars = {m.group(1) for m in _FORMDATA.finditer(masked)}
    urlparam_vars = {m.group(1) for m in _URLPARAMS.finditer(masked)}
    responses = _response_destructures(src, masked)
    call_starts = [m.start() for m in _CALLS.finditer(masked)]

    for call in _CALLS.finditer(masked):
        axios_method = call.group(1)
        open_paren = call.end() - 1
        close = match_bracket(masked, open_paren)
        if close < 0:
            continue
        args_s, args_m = src[open_paren + 1 : close - 1], masked[open_paren + 1 : close - 1]
        spans = split_top(args_s, args_m)
        if not spans:
            continue

        a, b = spans[0]
        url = literal_string(args_s[a:b])
        if url is None or "://" in url:
            continue  # unresolvable or absolute external URL

        method = (axios_method or "get").upper()
        encoding = UNKNOWN_ENC
        fields: tuple[Field, ...] = ()

        if axios_method in (None, "request") and len(spans) >= 2:
            # fetch(url, {...}) and axios(url, {...}) share an options object.
            c, d = spans[1]
            opt_start = args_m.find("{", c)
            if opt_start != -1 and opt_start < d:
                method, encoding, fields = _read_options(
                    args_s, args_m, opt_start, src, masked, formdata_vars, urlparam_vars
                )
            if axios_method is None and method == "GET" and "method" not in args_s[c:d]:
                method = "GET"
        elif axios_method:
            method = axios_method.upper()
            if axios_method in ("post", "put", "patch") and len(spans) >= 2:
                c, d = spans[1]
                encoding, fields = _read_body(
                    args_s[c:d], args_m[c:d], src, masked, formdata_vars, urlparam_vars
                )
            elif axios_method in ("post", "put", "patch"):
                encoding, fields = "none", ()
            else:
                encoding, fields = "none", ()

        nxt = next((c for c in call_starts if c > call.start()), len(src))
        resp = tuple(
            f for idx, f in responses if call.start() < idx < nxt
        )

        surfaces.append(
            Surface(
                side=CONSUMER,
                method=method,
                path=normalise_path(url),
                loc=Loc(rel, _line_of(src, call.start())),
                encoding=encoding,
                fields=fields,
                response_fields=resp,
            )
        )
    return surfaces


_RESP = re.compile(
    r"(?:const|let|var)\s*\{([^}]*)\}\s*(?::[^=]+)?=\s*(?:await\s+)?"
    r"[A-Za-z_$][\w$]*\.json\s*\("
)


def _response_destructures(src: str, masked: str) -> list[tuple[int, Field]]:
    """A-R5: fields the client reads back out of the response body."""
    out: list[tuple[int, Field]] = []
    for m in _RESP.finditer(masked):
        for part in src[m.start(1) : m.end(1)].split(","):
            name = part.split(":")[0].strip()
            if re.fullmatch(_IDENT, name):
                out.append((m.start(), Field(name, "unknown")))
    return out


def _read_options(
    args_s: str,
    args_m: str,
    start: int,
    src: str,
    masked: str,
    formdata_vars: set[str],
    urlparam_vars: set[str],
) -> tuple[str, str, tuple[Field, ...]]:
    end = match_bracket(args_m, start)
    if end < 0:
        return "GET", UNKNOWN_ENC, ()
    inner_s, inner_m = args_s[start + 1 : end - 1], args_m[start + 1 : end - 1]

    method, encoding, fields = "GET", "none", ()
    header_enc = ""
    for a, b in split_top(inner_s, inner_m):
        part_s, part_m = inner_s[a:b], inner_m[a:b]
        colon = part_m.find(":")
        if colon == -1:
            continue
        key = part_s[:colon].strip().strip("'\"")
        val_s, val_m = part_s[colon + 1 :], part_m[colon + 1 :]
        if key == "method":
            lit = literal_string(val_s)
            if lit:
                method = lit.upper()
        elif key == "headers":
            header_enc = _content_type(val_s, val_m)
        elif key == "body":
            encoding, fields = _read_body(
                val_s, val_m, src, masked, formdata_vars, urlparam_vars
            )
    if header_enc and encoding in ("none", UNKNOWN_ENC, JSON_ENC):
        # An explicit Content-Type wins: it is what the server actually sees.
        encoding = header_enc
    return method, encoding, fields


def _content_type(val_s: str, val_m: str) -> str:
    brace = val_m.find("{")
    if brace == -1:
        return ""
    end = match_bracket(val_m, brace)
    if end < 0:
        return ""
    text = val_s[brace:end].lower()
    if "multipart/form-data" in text:
        return MULTIPART
    if "application/x-www-form-urlencoded" in text:
        return URLENCODED
    if "application/json" in text:
        return JSON_ENC
    return ""


def _read_body(
    val_s: str,
    val_m: str,
    src: str,
    masked: str,
    formdata_vars: set[str],
    urlparam_vars: set[str],
) -> tuple[str, tuple[Field, ...]]:
    text = val_s.strip()
    stripped_m = val_m.strip()

    if stripped_m.startswith("JSON.stringify"):
        p = val_m.find("(", val_m.find("JSON.stringify"))
        end = match_bracket(val_m, p)
        if end < 0:
            return JSON_ENC, ()
        inner_s, inner_m = val_s[p + 1 : end - 1], val_m[p + 1 : end - 1]
        brace = inner_m.find("{")
        if brace != -1:
            return JSON_ENC, object_fields(inner_s, inner_m, brace) or ()
        ident = inner_s.strip()
        if re.fullmatch(_IDENT, ident):
            return JSON_ENC, _assigned_object(src, masked, ident) or ()
        return JSON_ENC, ()

    if "new FormData" in text:
        return MULTIPART, ()
    if "new URLSearchParams" in text:
        brace = val_m.find("{")
        if brace != -1:
            return URLENCODED, object_fields(val_s, val_m, brace) or ()
        return URLENCODED, ()

    ident = text
    if re.fullmatch(_IDENT, ident):
        if ident in formdata_vars:
            return MULTIPART, _formdata_fields(src, masked, ident)
        if ident in urlparam_vars:
            return URLENCODED, ()
        obj = _assigned_object(src, masked, ident)
        if obj is not None:
            return JSON_ENC, obj
        return UNKNOWN_ENC, ()

    brace = val_m.find("{")
    if brace != -1 and not val_s[:brace].strip():
        return JSON_ENC, object_fields(val_s, val_m, brace) or ()
    return UNKNOWN_ENC, ()
