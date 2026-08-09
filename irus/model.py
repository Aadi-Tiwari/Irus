"""Core data types. Everything else is derived from these."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

PRODUCER = "producer"
CONSUMER = "consumer"

# A-R21: confidence tiers. Only HIGH fails the merge gate, so a speculative
# finding can be surfaced without ever blocking a merge on a guess.
HIGH, MEDIUM, LOW = "high", "medium", "low"

# Encodings a request body can use. "unknown" never produces a high-confidence
# mismatch, because we could not read it rather than because it disagrees.
JSON_ENC, MULTIPART, URLENCODED, NONE_ENC, UNKNOWN_ENC = (
    "json",
    "multipart",
    "urlencoded",
    "none",
    "unknown",
)


@dataclass(frozen=True)
class Loc:
    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class Field:
    name: str
    type: str = "unknown"
    required: bool = True


_PARAM = re.compile(r"\{[^}/]*\}|\$\{[^}]*\}|:[A-Za-z_][A-Za-z0-9_]*")


def normalise_path(path: str) -> str:
    """Collapse every path parameter spelling to a single placeholder.

    FastAPI writes /users/{id}, Express writes /users/:id, a template literal
    writes /users/${id}. All three name the same route.
    """
    path = path.strip()
    if "?" in path:
        path = path.split("?", 1)[0]
    path = _PARAM.sub("{}", path)
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


@dataclass(frozen=True)
class Surface:
    """One side of a boundary, as declared in code."""

    side: str
    method: str
    path: str
    loc: Loc
    encoding: str = UNKNOWN_ENC
    fields: tuple[Field, ...] = ()
    response_fields: tuple[Field, ...] = ()
    mounted: bool = True
    external: bool = False

    @property
    def seam(self) -> str:
        return f"{self.method} {self.path}"

    def field_names(self) -> set[str]:
        return {f.name for f in self.fields}


@dataclass(frozen=True)
class EnvRead:
    name: str
    loc: Loc
    has_default: bool = False


@dataclass(frozen=True)
class Component:
    name: str
    loc: Loc
    exported: bool = True
    default_export: bool = False


class MissingEvidence(Exception):
    """A finding was built without a concrete site or without a specific
    disagreement.

    Adopted from the Part B branch, and it is a better idea than checking this
    downstream: B-R19 is enforced at construction, so a generic warning with no
    file attached cannot reach a receipt at all.
    """


@dataclass
class Finding:
    kind: str
    seam: str
    detail: str
    confidence: str = HIGH
    producer_loc: Loc | None = None
    consumer_loc: Loc | None = None
    subject: str = ""
    key: str = ""

    def __post_init__(self) -> None:
        if self.confidence not in (HIGH, MEDIUM, LOW):
            raise ValueError(f"unknown confidence tier: {self.confidence!r}")
        if not self.detail or len(self.detail) < 12:
            raise MissingEvidence(
                f"{self.seam}: detail is not a specific disagreement (B-R19)"
            )
        if self.producer_loc is None and self.consumer_loc is None:
            raise MissingEvidence(
                f"{self.seam}: a finding must name at least one concrete site (B-R19)"
            )
        if not self.key:
            self.key = self._key()

    def _key(self) -> str:
        """Stable identity for baseline subtraction.

        Deliberately excludes line numbers and free text, because those move
        when unrelated code is edited, and a finding whose identity changes on
        every edit can never be suppressed by a baseline. `subject` separates
        two findings of the same kind on the same seam, such as two different
        missing fields.
        """
        raw = f"{self.kind}\x00{self.seam}\x00{self.subject}"
        return "f-" + hashlib.sha1(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("producer_loc", "consumer_loc"):
            if d[k] is not None:
                d[k] = str(Loc(**d[k]))
        return d


@dataclass
class ReceiptLine:
    label: str
    passed: bool
    note: str = ""


@dataclass
class Receipt:
    seam: str
    lines: list[ReceiptLine] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(line.passed for line in self.lines)

    def render(self) -> str:
        out = [self.seam]
        width = max((len(l.label) for l in self.lines), default=0)
        for l in self.lines:
            status = "PASS" if l.passed else "FAIL"
            note = f"   {l.note}" if l.note else ""
            out.append(f"  {l.label.ljust(width)}  {status}{note}")
        return "\n".join(out)


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, default=str)
