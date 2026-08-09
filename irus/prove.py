"""Stage 2: proof by execution, and the rails that make it safe.

    B-R8   Refuse to send any request to a host that is not localhost.
    B-R9   Never issue a real POST, PUT, PATCH, or DELETE over the network.
    B-R10  Mutating requests go through the framework's in-process test client
           inside a transaction that rolls back, or they do not run.
    B-R11  Verify after every stage-2 run that the database row count is
           unchanged, and fail loudly if it is not.
    B-R12  Stage 2 is opt-in by flag on first use.

Every rail here is a raised exception, not a logged warning. A safety rule that
can be stepped over by ignoring output is not a rule. The ordering matters too:
consent is checked before the URL, the URL before the method, the method before
anything is constructed — so the earliest possible refusal is the one you get.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .findings import Finding

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Tier 3 (A-R12, P2) would allow these over real HTTP. Not enabled here.
SAFE_OVER_WIRE = frozenset({"GET", "HEAD", "OPTIONS"})


class SafetyViolation(Exception):
    """A stage-2 rail was hit. Always fatal to the run in progress."""


class ConsentRequired(SafetyViolation):
    """B-R12: nobody gets their code executed by surprise."""


# ---------------------------------------------------------------- the rails


def assert_local(url: str) -> None:
    """B-R8. Applied to any URL stage 2 might touch, including one that only
    appears in a finding's evidence."""
    parsed = urlparse(url if "//" in url else f"//{url}", scheme="http")
    host = (parsed.hostname or "").lower()
    if not host:
        return  # a bare path like /api/checkout never leaves the process
    if host not in LOCAL_HOSTS:
        raise SafetyViolation(
            f"refusing to touch non-localhost host {host!r} (B-R8). "
            f"Stage 2 runs against your machine or it does not run."
        )


def assert_transport(method: str, transport: str) -> None:
    """B-R9 and B-R10. `transport` is 'test_client' or 'wire'."""
    method = method.upper()
    if transport == "wire" and method in MUTATING:
        raise SafetyViolation(
            f"refusing to send a real {method} over the network (B-R9). "
            f"Mutating requests go through the in-process test client or not at all."
        )
    if transport == "wire" and method not in SAFE_OVER_WIRE:
        raise SafetyViolation(f"{method} is not permitted over the wire (B-R9)")


# -------------------------------------------------------------------- consent


CONSENT_FILE = Path(".irus") / "consent.json"


def has_consent(root: str | Path) -> bool:
    path = Path(root) / CONSENT_FILE
    if not path.is_file():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("stage2"))
    except (json.JSONDecodeError, OSError):
        return False


def grant_consent(root: str | Path) -> None:
    path = Path(root) / CONSENT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "stage2": True,
                "note": "Stage 2 executes code from this repository through an "
                        "in-process test client. Delete this file to revoke.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def require_consent(root: str | Path) -> None:
    if not has_consent(root):
        raise ConsentRequired(
            "stage 2 executes your code and is opt-in on first use (B-R12). "
            "Re-run with --prove --yes to record consent."
        )


# --------------------------------------------------------------------- proof


@dataclass
class ProofResult:
    finding_id: str
    method: str            # "schema" (tier 1) | "test_client" (tier 2)
    result: str            # "pass" | "fail" | "skipped" | "refused"
    status: int | None = None
    detail: str = ""
    rows_before: int | None = None
    rows_after: int | None = None

    def to_event(self) -> dict[str, Any]:
        event = {
            "id": self.finding_id,
            "method": self.method,
            "result": self.result,
            "status": self.status,
            "detail": self.detail,
        }
        if self.rows_before is not None:
            event["rows"] = {"before": self.rows_before, "after": self.rows_after}
        return event


def build_request(finding: Finding) -> dict[str, Any]:
    """Materialise the request the consumer would actually send. Constructed
    and returned; never sent by this function (A-R8)."""
    evidence = finding.evidence
    method, _, path = finding.seam.partition(" ")
    assert_local(path)
    encoding = evidence.get("consumer_encoding", "json")
    sent = evidence.get("sent", {})
    # Placeholder values matching the type the consumer was observed to send.
    samples = {"str": "x", "int": 1, "float": 1.0, "bool": True, "list": [], "dict": {}, "unknown": "x"}
    body = {name: samples.get(kind, "x") for name, kind in sorted(sent.items()) if name != "..."}
    return {"method": method, "path": path, "encoding": encoding, "body": body}


def tier1(finding: Finding) -> ProofResult:
    """Tier 1 (A-R8): validate the constructed request against the *declared*
    schema without sending it.

    This stays a pure function — it does not import the target application, so
    it cannot execute the repository's code. The tradeoff is that the verdict
    comes from our reading of the schema rather than from the app, which is
    exactly why tier 2 exists.
    """
    if finding.cls != "payload_mismatch":
        return ProofResult(finding.id, "schema", "skipped", detail=f"{finding.cls} is not executable at tier 1")

    request = build_request(finding)
    evidence = finding.evidence
    expected: dict[str, str] = evidence.get("expected", {})
    required = set(evidence.get("required", []))
    producer_encoding = evidence.get("producer_encoding", "json")

    errors: list[str] = []
    if request["encoding"] != producer_encoding:
        errors.append(
            f"body: expected {producer_encoding}, received {request['encoding']}"
        )
    for name in sorted(required - set(request["body"])):
        errors.append(f"{name}: field required")
    for name, value in sorted(request["body"].items()):
        want = expected.get(name)
        if want is None:
            continue
        got = type(value).__name__
        got = {"str": "str", "int": "int", "float": "float", "bool": "bool"}.get(got, got)
        if want != got and not (want in ("int", "float") and got == "str"):
            errors.append(f"{name}: expected {want}, received {got}")

    if errors:
        return ProofResult(
            finding.id, "schema", "fail", status=422,
            detail="; ".join(errors),
        )
    return ProofResult(finding.id, "schema", "pass", status=200, detail="request satisfies the declared schema")


def tier2(
    finding: Finding,
    *,
    root: str | Path,
    client_factory: Callable[[], Any],
    row_counter: Callable[[], int] | None,
    transaction: Callable[[], Any] | None = None,
) -> ProofResult:
    """Tier 2 (A-R9): send through the framework's own test client, inside a
    transaction that rolls back. The application decides, not Irus.

    `client_factory` returns something with a `.request(method, url, ...)` —
    a `fastapi.testclient.TestClient` satisfies this. `transaction` is a context
    manager that must roll back on exit. `row_counter` is mandatory: without a
    way to check B-R11 afterwards, the honest move is to refuse the run rather
    than to run it unverified.
    """
    require_consent(root)

    request = build_request(finding)
    assert_local(request["path"])
    assert_transport(request["method"], "test_client")

    if row_counter is None:
        return ProofResult(
            finding.id, "test_client", "refused",
            detail="no row counter configured, so B-R11 cannot be verified after the run; "
                   "refusing tier 2 rather than executing unverified",
        )
    if request["method"] in MUTATING and transaction is None:
        return ProofResult(
            finding.id, "test_client", "refused",
            detail=f"{request['method']} requires a rolling-back transaction (B-R10); none was provided",
        )

    rows_before = row_counter()
    client = client_factory()

    def send() -> Any:
        if request["encoding"] == "multipart":
            return client.request(request["method"], request["path"], files={
                k: (None, str(v)) for k, v in request["body"].items()
            })
        return client.request(request["method"], request["path"], json=request["body"])

    if transaction is not None:
        with transaction():
            response = send()
    else:
        response = send()

    rows_after = row_counter()
    status = getattr(response, "status_code", None)

    if rows_after != rows_before:
        # B-R11: loud, and the finding's verdict is discarded — a proof run
        # that mutated the database has invalidated itself.
        raise SafetyViolation(
            f"stage 2 changed the database: {rows_before} rows before, {rows_after} after (B-R11). "
            f"The transaction did not roll back. Verdict discarded."
        )

    body_text = ""
    try:
        body_text = json.dumps(response.json())[:400]
    except Exception:
        body_text = str(getattr(response, "text", ""))[:400]

    result = "fail" if status is not None and status >= 400 else "pass"
    return ProofResult(
        finding.id, "test_client", result, status=status,
        detail=body_text, rows_before=rows_before, rows_after=rows_after,
    )


def prove(findings: list[Finding], *, root: str | Path) -> list[ProofResult]:
    """Tier 1 across a finding set. Tier 2 is driven by the harness that knows
    how to build the app, so it is not called from here."""
    return [tier1(f) for f in findings]
