"""Stage 1: the sweep.

    B-R1   Stage 1 is a pure function of the working tree. Same input, same
           output, always. No model, no network, no clock, no randomness.
    B-R13  Full sweep on 500 source files in under 2 seconds.
    B-R15  Per-seam results are cached against a content hash of both sides.
    B-R19  Every finding names both file paths and the exact disagreement.

There is no model in this file and no import that could reach one. That is the
claim the demo makes out loud (B-R36), so it is worth keeping literally true.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .extract import consumer, env, producer
from .findings import Finding, Side
from .walk import source_files, split_sides

# Pydantic coerces a JSON string into an int in lax mode, so a str/int
# disagreement over JSON is a real smell but not a guaranteed failure. It is
# reported at medium and does not fail the gate. Over multipart it is moot,
# because the encoding disagreement fires first at high.
_COERCIBLE = {("str", "int"), ("str", "float"), ("int", "float"), ("str", "bool")}


@dataclass
class Sweep:
    findings: list[Finding] = field(default_factory=list)
    routes: list[producer.Route] = field(default_factory=list)
    calls: list[consumer.Call] = field(default_factory=list)
    files_scanned: int = 0
    duration_ms: float = 0.0
    cache_hits: int = 0

    def gating(self) -> list[Finding]:
        return [f for f in self.findings if f.gates()]


# ------------------------------------------------------------------- caching


class SeamCache:
    """B-R15: results keyed by a content hash of both sides, so a re-run only
    recomputes seams whose source actually changed. Kept in memory and
    optionally persisted; correctness never depends on it, which is why a cache
    miss and a cold start produce identical output."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        if path and path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {}

    @staticmethod
    def key(*sides: str) -> str:
        return hashlib.sha256("\x00".join(sides).encode("utf-8")).hexdigest()[:16]

    def get(self, key: str) -> Any | None:
        return self.data.get(key)

    def put(self, key: str, value: Any) -> None:
        self.data[key] = value

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, sort_keys=True), encoding="utf-8")


# ------------------------------------------------------------------ matching


def _route_pattern(path: str) -> re.Pattern:
    """`/api/orders/{id}` matches `/api/orders/42`."""
    escaped = re.escape(path)
    escaped = re.sub(r"\\\{[^/}]+\\\}", r"[^/]+", escaped)
    return re.compile(f"^{escaped}/?$")


def _match(call: consumer.Call, routes: list[producer.Route]) -> producer.Route | None:
    for route in routes:
        if route.method != call.method:
            continue
        if _route_pattern(route.path).match(call.url):
            return route
    return None


def _shape(route: producer.Route) -> dict[str, str]:
    return dict(route.model.fields) if route.model else {}


# ----------------------------------------------------------------- comparing


def _compare_payload(call: consumer.Call, route: producer.Route) -> Finding | None:
    """The headline check: does what the consumer sends satisfy what the
    producer declared? Returns at most one finding per seam, with the most
    decisive disagreement named."""
    expected = _shape(route)
    required = set(route.model.required) if route.model else set()
    sent = dict(call.fields)
    has_spread = sent.pop("...", None) is not None

    producer_side = Side(
        route.file,
        route.line,
        f"{route.encoding} body {json.dumps(expected, sort_keys=True)}" if expected else f"{route.encoding} body",
    )
    consumer_side = Side(
        call.file,
        call.line,
        f"{call.encoding} body with {sorted(sent) or 'no fields'}",
    )
    evidence = {
        "expected": expected,
        "required": sorted(required),
        "sent": sent,
        "producer_encoding": route.encoding,
        "consumer_encoding": call.encoding,
        "body_form": call.body_form,
    }

    def make(cls: str, confidence: str, detail: str) -> Finding:
        return Finding(
            seam=route.seam,
            cls=cls,
            confidence=confidence,
            detail=detail,
            producer=producer_side,
            consumer=consumer_side,
            evidence=evidence,
        )

    # 1. Encoding. A multipart body reaching a handler that declared a JSON
    #    model fails at parse time, before any field is looked at. This is the
    #    most decisive disagreement available to stage 1, so it is checked first.
    if call.body_form in ("json_stringify", "formdata", "literal") and route.method not in ("GET", "HEAD"):
        if call.encoding != route.encoding:
            return make(
                "payload_mismatch",
                "high",
                f"consumer sends {call.encoding} but producer declares {route.encoding}"
                + (f" ({route.model.name})" if route.model else ""),
            )

    # Below here we need to have actually read the consumer body. An unread
    # body is not evidence of anything.
    if call.body_form not in ("json_stringify", "formdata", "literal"):
        return None
    if not expected:
        return None

    missing = sorted(required - set(sent))
    unknown = sorted(set(sent) - set(expected))

    # 2. A required field the consumer never sends is a guaranteed 422.
    if missing and not has_spread:
        detail = (
            f"producer requires {missing} which the consumer never sends"
            + (f"; consumer sends {unknown} instead" if unknown else "")
        )
        return make("payload_mismatch", "high", detail)

    # 3. Same names, disagreeing types.
    conflicts = []
    for name, want in sorted(expected.items()):
        got = sent.get(name)
        if got in (None, "unknown"):
            continue
        if got != want and (got, want) not in _COERCIBLE and (want, got) not in _COERCIBLE:
            conflicts.append(f"{name}: producer {want}, consumer {got}")
        elif got != want:
            conflicts.append(f"{name}: producer {want}, consumer {got} (coercible)")
    if conflicts:
        coercible_only = all("(coercible)" in c for c in conflicts)
        return make(
            "payload_mismatch",
            "medium" if coercible_only else "high",
            "type disagreement — " + "; ".join(conflicts),
        )

    # 4. Fields the producer will ignore. Real, but rarely a break.
    if unknown and not has_spread:
        return make(
            "payload_mismatch",
            "low",
            f"consumer sends {unknown} which the producer's {route.model.name if route.model else 'model'} does not declare",
        )
    return None


def _compare(routes: list[producer.Route], calls: list[consumer.Call], cache: SeamCache) -> list[Finding]:
    out: list[Finding] = []
    called_seams: set[str] = set()

    for call in calls:
        route = _match(call, routes)
        if route is None:
            # No route declares this URL. Only high-confidence when we read the
            # URL literally *and* the repository does declare routes at all —
            # a frontend-only checkout has no producer to disagree with.
            if not routes:
                continue
            confidence = "high" if call.url_confident and call.url.startswith("/api") else "low"
            out.append(
                Finding(
                    seam=call.seam,
                    cls="no_route",
                    confidence=confidence,
                    detail=f"consumer calls {call.method} {call.url}; no route in this tree declares it",
                    producer=None,
                    consumer=Side(call.file, call.line, f"{call.method} {call.url}"),
                    evidence={"url_confident": call.url_confident, "sent": call.fields},
                )
            )
            continue

        called_seams.add(route.seam)
        key = cache.key(
            route.seam,
            json.dumps(_shape(route), sort_keys=True),
            route.encoding,
            json.dumps(call.fields, sort_keys=True),
            call.encoding,
            call.body_form,
        )
        cached = cache.get(key)
        if cached is not None:
            if cached:  # a cached finding, rehydrated
                out.append(_finding_from_cache(cached))
            continue
        finding = _compare_payload(call, route)
        cache.put(key, finding.to_event() if finding else None)
        if finding:
            out.append(finding)

    # Zero-caller endpoints (A-R6). Medium at best: a route can be legitimately
    # called by something outside this tree, which is exactly the /health case
    # the ledger is meant to expose.
    #
    # And a correction found by running this against real repositories (B-R27):
    # if not one consumer call in the whole tree resolved to any route, we did
    # not read the consumer side — we cannot see through an axios wrapper or a
    # template-built URL. "No caller" then means "we found no callers of
    # anything", which is a statement about our extractor, not about the code.
    # Every such finding drops to low so it cannot gate, and the detail says why.
    read_consumer_side = bool(called_seams)
    for route in routes:
        if route.seam in called_seams:
            continue
        if route.method in ("GET", "HEAD", "OPTIONS"):
            continue  # probes, health checks, and browser navigation live here
        out.append(
            Finding(
                seam=route.seam,
                cls="orphan_endpoint",
                confidence="medium" if read_consumer_side else "low",
                detail=(
                    f"route {route.seam} is declared but no call in this tree targets it"
                    if read_consumer_side
                    else f"route {route.seam} has no caller, but no call anywhere in this "
                         f"tree resolved to any route — the consumer side was not readable, "
                         f"so this is weak evidence"
                ),
                producer=Side(route.file, route.line, f"{route.method} {route.path}"),
                consumer=None,
                evidence={"handler": route.handler},
            )
        )
    return out


def _finding_from_cache(event: dict[str, Any]) -> Finding:
    return Finding(
        seam=event["seam"],
        cls=event["class"],
        confidence=event["confidence"],
        detail=event["detail"],
        producer=Side(**event["producer"]) if event.get("producer") else None,
        consumer=Side(**event["consumer"]) if event.get("consumer") else None,
        evidence=event.get("evidence", {}),
    )


def _env_findings(files: list[Path], root: Path) -> list[Finding]:
    all_reads = env.reads(files, root)
    provided, sources = env.writers(root, files)
    out: list[Finding] = []
    seen: set[str] = set()
    for read in all_reads:
        if read.name in provided or read.name in seen:
            continue
        if read.severity == "defaulted":
            continue  # a fallback exists; unset is not a failure
        seen.add(read.name)
        out.append(
            Finding(
                seam=f"env {read.name}",
                cls="env_unset",
                confidence="high" if read.severity == "hard" else "medium",
                detail=(
                    f"{read.name} is read at {read.file}:{read.line} but set in no "
                    f".env, compose file, vercel.json, or workflow in this tree"
                ),
                producer=None,
                consumer=Side(read.file, read.line, f"reads {read.name} ({read.severity})"),
                evidence={"severity": read.severity, "known_sources": sorted(set(sources.values()))},
            )
        )
    return out


# -------------------------------------------------------------------- public


def sweep(root: str | Path, *, cache: SeamCache | None = None) -> Sweep:
    """One full pass. Pure with respect to the tree (B-R1): the only impure
    thing recorded is `duration_ms`, which is measurement and is deliberately
    excluded from every comparison and every digest."""
    root = Path(root).resolve()
    started = time.perf_counter()
    cache = cache if cache is not None else SeamCache()

    files = source_files(root)
    py_files, web_files = split_sides(files)

    routes = producer.extract(py_files, root)
    calls = consumer.extract(web_files, root)

    findings = _compare(routes, calls, cache)
    findings.extend(_env_findings(files, root))
    findings.sort(key=lambda f: f.sort_key())

    return Sweep(
        findings=findings,
        routes=routes,
        calls=calls,
        files_scanned=len(files),
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def digest(findings: list[Finding]) -> str:
    """Canonical fingerprint of a finding set, used to assert determinism."""
    material = json.dumps([f.to_event() for f in findings], sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
