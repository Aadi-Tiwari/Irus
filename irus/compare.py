"""A-R3 and A-R5: compare the two sides of a boundary.

The whole point of the tool lives here, so the false-positive discipline lives
here too. Two rules govern every check:

  1. An `unknown` never produces a high-confidence finding. If the scanner
     could not read a body, that is our limitation, not the code's defect.
  2. A spread (`...rest`) means the field set is unknowable, so missing-field
     checks are suppressed for that seam rather than guessed at.
"""

from __future__ import annotations

from collections import defaultdict

from .model import (
    HIGH,
    normalise_path,
    JSON_ENC,
    LOW,
    MEDIUM,
    NONE_ENC,
    UNKNOWN_ENC,
    Finding,
    Surface,
)

BODY_METHODS = {"POST", "PUT", "PATCH"}

# Paths whose callers legitimately live outside the repository.
EXTERNAL_HINTS = (
    "/health",
    "/healthz",
    "/readyz",
    "/livez",
    "/metrics",
    "/webhook",
    "/webhooks",
    "/callback",
    "/oauth",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/robots.txt",
    "/favicon.ico",
)


def looks_external(path: str) -> bool:
    """Whether a route's real callers plausibly live outside the repository.

    Matches on whole path segments anywhere in the path, not just at the start,
    because these routes are usually mounted under a prefix: /api/health and
    /api/webhooks/stripe are both externally called.
    """
    p = path.lower()
    if "/_" in p:
        return True
    for hint in EXTERNAL_HINTS:
        i = p.find(hint)
        while i != -1:
            end = i + len(hint)
            if end == len(p) or p[end] == "/":
                return True
            i = p.find(hint, i + 1)
    return False


def _known(encoding: str) -> bool:
    return encoding not in (UNKNOWN_ENC, "")


def _has_spread(surface: Surface) -> bool:
    return any(f.name == "..." for f in surface.fields)


def compare(producers: list[Surface], consumers: list[Surface]) -> list[Finding]:
    findings: list[Finding] = []

    by_seam: dict[str, list[Surface]] = defaultdict(list)
    for p in producers:
        by_seam[p.seam].append(p)
    by_path: dict[str, list[Surface]] = defaultdict(list)
    for p in producers:
        by_path[p.path].append(p)

    # A route declared on a router nobody mounts is dead on arrival.
    for p in producers:
        if not p.mounted:
            findings.append(
                Finding(
                    kind="unmounted_route",
                    seam=p.seam,
                    detail="route is declared on a router that is never included on an app",
                    confidence=HIGH,
                    producer_loc=p.loc,
                )
            )

    for c in consumers:
        matches = by_seam.get(c.seam, [])
        if not matches:
            same_path = by_path.get(c.path, [])
            if same_path:
                methods = sorted({s.method for s in same_path})
                findings.append(
                    Finding(
                        kind="method_mismatch",
                        seam=c.seam,
                        detail=(
                            f"client sends {c.method}, server declares "
                            f"{' and '.join(methods)} on this path"
                        ),
                        confidence=HIGH,
                        producer_loc=same_path[0].loc,
                        consumer_loc=c.loc,
                    )
                )
            elif producers:
                # Only meaningful when a backend exists in this repository at
                # all; otherwise every call is trivially "not found".
                findings.append(
                    Finding(
                        kind="endpoint_not_found",
                        seam=c.seam,
                        detail="client calls a route no server in this repository declares",
                        confidence=MEDIUM,
                        consumer_loc=c.loc,
                    )
                )
            continue

        p = matches[0]
        findings.extend(_compare_pair(p, c))

    return findings


def _compare_pair(p: Surface, c: Surface) -> list[Finding]:
    out: list[Finding] = []
    if c.method not in BODY_METHODS:
        return out

    if _known(p.encoding) and _known(c.encoding) and p.encoding != c.encoding:
        if not (p.encoding == NONE_ENC and c.encoding == NONE_ENC):
            out.append(
                Finding(
                    kind="encoding_mismatch",
                    seam=p.seam,
                    detail=f"client sends {c.encoding}, server expects {p.encoding}",
                    confidence=HIGH,
                    producer_loc=p.loc,
                    consumer_loc=c.loc,
                )
            )

    # A-R5: response shape is checked before the request-body gate below.
    # A handler can declare a response model and take no request body at all,
    # and gating the response check behind request fields silently skipped it.
    out.extend(_compare_response(p, c))

    # Field comparison needs both sides legible.
    if not p.fields or (not c.fields and c.encoding in (UNKNOWN_ENC, NONE_ENC)):
        return out

    consumer_names = c.field_names()
    producer_names = p.field_names()
    spread = _has_spread(c)

    if not spread:
        for f in p.fields:
            if f.required and f.name not in consumer_names:
                out.append(
                    Finding(
                        kind="missing_required_field",
                        seam=p.seam,
                        subject=f.name,
                        detail=(
                            f"server requires `{f.name}` ({f.type}); client sends "
                            f"{sorted(consumer_names) or 'nothing'}"
                        ),
                        confidence=HIGH,
                        producer_loc=p.loc,
                        consumer_loc=c.loc,
                    )
                )

    for f in c.fields:
        if f.name == "...":
            continue
        if f.name not in producer_names:
            out.append(
                Finding(
                    kind="unexpected_field",
                    seam=p.seam,
                    subject=f.name,
                    detail=f"client sends `{f.name}`; server declares no such field",
                    confidence=MEDIUM,
                    producer_loc=p.loc,
                    consumer_loc=c.loc,
                )
            )

    ptypes = {f.name: f.type for f in p.fields}
    for f in c.fields:
        want = ptypes.get(f.name)
        if not want or want == "unknown" or f.type == "unknown":
            continue
        if want != f.type and not (want == "float" and f.type == "int"):
            out.append(
                Finding(
                    kind="field_type_mismatch",
                    seam=p.seam,
                    subject=f.name,
                    detail=f"`{f.name}`: client sends {f.type}, server expects {want}",
                    confidence=HIGH,
                    producer_loc=p.loc,
                    consumer_loc=c.loc,
                )
            )

    return out


def _compare_response(p: Surface, c: Surface) -> list[Finding]:
    """A-R5: response shape, when the client destructures what it got back."""
    if not (p.response_fields and c.response_fields):
        return []
    declared = {f.name for f in p.response_fields}
    return [
        Finding(
            kind="response_shape_mismatch",
            seam=p.seam,
            subject=f.name,
            detail=(
                f"client reads `{f.name}` from the response; server's "
                f"response model declares {sorted(declared)}"
            ),
            confidence=MEDIUM,
            producer_loc=p.loc,
            consumer_loc=c.loc,
        )
        for f in c.response_fields
        if f.name not in declared
    ]


def orphan_endpoints(
    producers: list[Surface],
    consumers: list[Surface],
    path_refs: list | None = None,
) -> list[Finding]:
    """Part of A-R6.

    Deliberately capped at medium confidence: an endpoint's real callers very
    often live outside the repository, which is why knip refuses to flag route
    files at all. Claiming high here would manufacture false positives.

    `path_refs` are path-shaped string literals from anywhere in the tree. They
    are weak evidence and that is the point: a Python client, a test using a
    framework test client, and a generated API client all reference a route
    without producing a parsed consumer surface. Measured across five
    third-party repositories, ignoring them made this check 12% precise. A
    route something in the repository names by literal is not an orphan.
    """
    called = {c.seam for c in consumers}
    called_paths = {c.path for c in consumers}

    # Every file that names each path, not just the first one seen. Keeping
    # only the first meant the declaring file always won the race (files are
    # walked in sorted order) and a real caller was discarded.
    referenced: dict[str, set[str]] = {}
    for ref in path_refs or []:
        referenced.setdefault(normalise_path(ref.path), set()).add(ref.file)

    out: list[Finding] = []
    for p in producers:
        if p.seam in called or p.path in called_paths:
            continue
        if looks_external(p.path):
            continue
        # Named anywhere else in the tree, in any language.
        if referenced.get(p.path, set()) - {p.loc.file}:
            continue
        out.append(
            Finding(
                kind="orphan_endpoint",
                seam=p.seam,
                detail=(
                    "no client in this repository calls this route, and its path "
                    "appears in no string literal here either"
                ),
                # Always low. Measured across five third-party repositories this
                # check runs at 14% precision even after path-literal evidence is
                # taken into account, because a route composed from a prefix at
                # mount time is referenced by a fragment rather than by its full
                # path. It is reported because a genuinely dead endpoint is worth
                # seeing, and it is never allowed to fail a merge gate.
                #
                # It is deliberately NOT tuned to match how tools/adjudicate.py
                # judges it. Fitting the checker to its own judge would drive the
                # published precision toward 100% and measure nothing at all.
                confidence=LOW,
                producer_loc=p.loc,
            )
        )
    return out
