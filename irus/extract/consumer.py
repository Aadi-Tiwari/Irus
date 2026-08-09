"""Consumer side: what the browser code actually sends.

Narrow on purpose. PRD-B section 7 names cross-language payload matching as the
top risk and prescribes the response: literal object bodies and `FormData` only,
with the limit stated rather than silently overclaimed. Anything this module
cannot read confidently is emitted as `unknown`, and the comparator refuses to
raise a finding to high confidence on an `unknown`.

No TypeScript type resolution happens here. A brace-matching scanner reads the
call site literally: what URL, what method, what keys, what encoding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_FETCH = re.compile(r"\bfetch\s*\(")
_AXIOS = re.compile(r"\baxios\s*\.\s*(get|post|put|patch|delete)\s*\(")
_FORMDATA_NEW = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*new\s+FormData\s*\(\s*\)")
_APPEND = re.compile(r"\b(\w+)\s*\.\s*append\s*\(\s*[\"'`]([^\"'`]+)[\"'`]\s*,")
_KEY = re.compile(r"^\s*(?:[\"'`]([^\"'`]+)[\"'`]|([A-Za-z_$][\w$]*))\s*:")


@dataclass
class Call:
    method: str
    url: str
    file: str
    line: int
    encoding: str = "json"          # json | multipart | urlencoded | unknown
    fields: dict[str, str] = field(default_factory=dict)   # name -> inferred type
    body_form: str = "none"         # json_stringify | formdata | literal | none | unknown
    url_confident: bool = True      # False when built from an unresolved template

    @property
    def seam(self) -> str:
        return f"{self.method} {self.url}"


# ------------------------------------------------------------------ scanning


def _strip_comments(text: str) -> str:
    """Blank out comments while preserving offsets, so line numbers computed
    later still point at the real source line."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    out[i] = " "
                    i += 1
                continue
            if text[i + 1] == "*":
                while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                    if text[i] != "\n":
                        out[i] = " "
                    i += 1
                for j in range(i, min(i + 2, n)):
                    out[j] = " "
                i += 2
                continue
        i += 1
    return "".join(out)


def _balanced(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    """Return the substring between the delimiter pair beginning at `start`,
    plus the index just past the closer. String literals are skipped so a
    brace inside a string cannot unbalance the scan."""
    depth = 0
    i, n = start, len(text)
    begin = -1
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    break
                i += 1
            i += 1
            continue
        if ch == opener:
            if depth == 0:
                begin = i + 1
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[begin:i], i + 1
        i += 1
    return "", n


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    parts, depth, current, i, n = [], 0, [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            quote = ch
            current.append(ch)
            i += 1
            while i < n:
                current.append(text[i])
                if text[i] == "\\":
                    i += 1
                    if i < n:
                        current.append(text[i])
                    i += 1
                    continue
                if text[i] == quote:
                    break
                i += 1
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _object_keys(body: str) -> dict[str, str]:
    """Top-level keys of an object literal, with a lossy value type."""
    out: dict[str, str] = {}
    for entry in _split_top_level(body):
        match = _KEY.match(entry)
        if not match:
            # Spread (`...props`) or a computed key: we cannot enumerate it,
            # so record that fact instead of pretending the object is complete.
            if entry.startswith("..."):
                out["..."] = "spread"
            continue
        key = match.group(1) or match.group(2)
        value = entry[match.end():].strip()
        out[key] = _value_type(value)
    return out


def _value_type(value: str) -> str:
    value = value.strip()
    if not value:
        return "unknown"
    if value[0] in "\"'`":
        return "str"
    if value in ("true", "false"):
        return "bool"
    if re.fullmatch(r"-?\d+", value):
        return "int"
    if re.fullmatch(r"-?\d*\.\d+", value):
        return "float"
    if value.startswith("String(") or ".toString()" in value:
        return "str"
    if value.startswith("Number(") or value.startswith("parseFloat("):
        return "float"
    if value.startswith("parseInt("):
        return "int"
    if value.startswith("["):
        return "list"
    if value.startswith("{"):
        return "dict"
    return "unknown"


def _unwrap_url(raw: str) -> tuple[str, bool]:
    """Pull a comparable path out of the first fetch argument.

    A template literal keeps its literal prefix and marks itself unconfident,
    which downgrades any finding built on it rather than matching the wrong
    route.
    """
    raw = raw.strip()
    if raw[:1] in "\"'" and raw[-1:] == raw[:1]:
        return _path_only(raw[1:-1]), True
    if raw.startswith("`"):
        inner = raw[1:-1] if raw.endswith("`") else raw[1:]
        if "${" in inner:
            prefix = inner.split("${", 1)[0]
            return _path_only(prefix.rstrip("/")), False
        return _path_only(inner), True
    return raw, False


def _path_only(url: str) -> str:
    """Strip origin and query so `http://localhost:8000/api/x?y=1` compares
    against a declared route path."""
    url = url.split("?", 1)[0]
    for scheme in ("http://", "https://"):
        if url.startswith(scheme):
            rest = url[len(scheme):]
            slash = rest.find("/")
            return rest[slash:] if slash >= 0 else "/"
    return url


# -------------------------------------------------------------------- public


def scan_file(path: Path, root: Path) -> list[Call]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    clean = _strip_comments(source)
    rel = str(path.relative_to(root))

    # FormData variables and their appended keys, collected file-wide. Values
    # appended to a FormData are strings on the wire, always — which is the
    # whole reason a numeric field sent this way disagrees with an `int`.
    formdata_keys: dict[str, dict[str, str]] = {
        m.group(1): {} for m in _FORMDATA_NEW.finditer(clean)
    }
    for m in _APPEND.finditer(clean):
        var, key = m.group(1), m.group(2)
        if var in formdata_keys:
            formdata_keys[var][key] = "str"

    calls: list[Call] = []
    for match in _FETCH.finditer(clean):
        args_text, _ = _balanced(clean, match.end() - 1, "(", ")")
        args = _split_top_level(args_text)
        if not args:
            continue
        url, confident = _unwrap_url(args[0])
        call = Call(
            method="GET",
            url=url,
            file=rel,
            line=clean.count("\n", 0, match.start()) + 1,
            url_confident=confident,
        )
        if len(args) > 1:
            _read_options(call, args[1], clean, formdata_keys)
        calls.append(call)

    for match in _AXIOS.finditer(clean):
        args_text, _ = _balanced(clean, match.end() - 1, "(", ")")
        args = _split_top_level(args_text)
        if not args:
            continue
        url, confident = _unwrap_url(args[0])
        call = Call(
            method=match.group(1).upper(),
            url=url,
            file=rel,
            line=clean.count("\n", 0, match.start()) + 1,
            url_confident=confident,
        )
        if len(args) > 1 and args[1].startswith("{"):
            inner, _ = _balanced(args[1], 0, "{", "}")
            call.fields = _object_keys(inner)
            call.body_form = "literal"
        calls.append(call)

    return calls


def _read_options(call: Call, options: str, clean: str, formdata_keys: dict[str, dict[str, str]]) -> None:
    if not options.startswith("{"):
        call.body_form = "unknown"
        return
    inner, _ = _balanced(options, 0, "{", "}")
    for entry in _split_top_level(inner):
        match = _KEY.match(entry)
        if not match:
            continue
        key = (match.group(1) or match.group(2) or "").lower()
        value = entry[match.end():].strip()
        if key == "method":
            method, _ok = _unwrap_url(value)
            call.method = method.strip().upper() or "GET"
        elif key == "headers":
            if "multipart/form-data" in value:
                call.encoding = "multipart"
            elif "application/x-www-form-urlencoded" in value:
                call.encoding = "urlencoded"
        elif key == "body":
            _read_body(call, value, formdata_keys)


def _read_body(call: Call, value: str, formdata_keys: dict[str, dict[str, str]]) -> None:
    value = value.strip()
    if value.startswith("JSON.stringify("):
        arg, _ = _balanced(value, len("JSON.stringify") , "(", ")")
        arg = arg.strip()
        if arg.startswith("{"):
            obj, _ = _balanced(arg, 0, "{", "}")
            call.fields = _object_keys(obj)
            call.body_form = "json_stringify"
            call.encoding = "json"
        else:
            # `JSON.stringify(payload)` where payload is a variable. We do not
            # follow it — that is type inference, which is out of scope.
            call.body_form = "unknown"
            call.encoding = "json"
        return
    if value in formdata_keys:
        call.fields = dict(formdata_keys[value])
        call.body_form = "formdata"
        # A FormData body makes the request multipart regardless of what the
        # headers say; the browser sets the boundary itself.
        call.encoding = "multipart"
        return
    if value.startswith("new FormData("):
        call.body_form = "formdata"
        call.encoding = "multipart"
        return
    if value.startswith("{"):
        obj, _ = _balanced(value, 0, "{", "}")
        call.fields = _object_keys(obj)
        call.body_form = "literal"
        return
    call.body_form = "unknown"


def extract(files: list[Path], root: Path) -> list[Call]:
    calls: list[Call] = []
    for path in sorted(files):
        calls.extend(scan_file(path, root))
    return sorted(calls, key=lambda c: (c.url, c.method, c.file, c.line))
