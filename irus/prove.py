"""A-R8 to A-R12: prove a suspected mismatch by executing it.

Schema comparison and generated request probes are separate evidence tiers.
An application rejecting a placeholder request does not establish the cause.
Network probes target loopback and refuse redirects. In-process imports and
handlers can still perform arbitrary I/O, including external requests. Store
fingerprints detect selected local file changes after execution; they cannot
roll them back. Use a disposable application and disposable data.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .model import HIGH, JSON_ENC, MULTIPART, NONE_ENC, UNKNOWN_ENC, Finding, Loc, Surface

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

TIER_SCHEMA = "schema"
TIER_TEST_CLIENT = "test_client"
TIER_HTTP = "http"

PLACEHOLDER: dict[str, Any] = {
    "str": "x",
    "int": 1,
    "float": 1.0,
    "bool": True,
    "list": [],
    "dict": {},
    "bytes": "x",
    "file": "x",
    "unknown": "x",
}


@dataclass
class Proof:
    seam: str
    tier: str
    passed: bool | None
    detail: str
    status: int | None = None
    errors: list[str] = field(default_factory=list)
    producer_loc: Loc | None = None
    consumer_loc: Loc | None = None

    @property
    def result(self) -> str:
        return "unavailable" if self.passed is None else "pass" if self.passed else "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "seam": self.seam, "tier": self.tier, "result": self.result,
            "status": self.status, "detail": self.detail, "errors": self.errors,
            "producer_loc": str(self.producer_loc) if self.producer_loc else None,
            "consumer_loc": str(self.consumer_loc) if self.consumer_loc else None,
        }

    def to_finding(self) -> Finding:
        if self.passed is not False:
            raise ValueError("Only a failed proof is a finding")
        return Finding(
            kind="schema_proof" if self.tier == TIER_SCHEMA else "execution_proof",
            seam=self.seam,
            detail=self.detail,
            confidence=HIGH,
            producer_loc=self.producer_loc,
            consumer_loc=self.consumer_loc,
            subject=self.tier,
        )


class UnsafeRequest(RuntimeError):
    """Raised when a request would violate A-R10 or A-R11."""


class ConsentRequired(UnsafeRequest):
    """B-R12: nobody gets their code executed by surprise.

    Adopted from the Part B branch. A command-line flag is consent for one run;
    a recorded consent file is consent the user gave once, knowingly, and can
    revoke by deleting a file.
    """


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


def assert_transport(method: str, transport: str) -> None:
    """B-R9 and B-R10 in one rail. `transport` is 'test_client' or 'wire'."""
    method = method.upper()
    if transport != "wire":
        return
    if method in MUTATING:
        raise UnsafeRequest(
            f"refusing to send a real {method} over the network (A-R11). "
            "Mutating requests go through the in-process test client or not at all."
        )
    if method not in SAFE_METHODS:
        raise UnsafeRequest(f"{method} is not permitted over the wire (A-R11)")


# --------------------------------------------------------------------- guards
def assert_local(url: str) -> None:
    """A-R10: nothing ever leaves this machine."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.netloc:
        return  # a bare path is served locally by definition
    host = (parsed.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise UnsafeRequest(f"refusing to send to non-local host {host!r}")


def assert_not_mutating_over_network(method: str) -> None:
    """A-R11: a mutating method never travels over the wire."""
    if method.upper() in MUTATING:
        raise UnsafeRequest(
            f"refusing to send {method.upper()} over the network; "
            "mutating methods go through the in-process test client or not at all"
        )


# ------------------------------------------------------------ tier 1: schema
def synthesise(consumer: Surface) -> tuple[str, dict[str, Any]]:
    """Build the concrete body this client would actually send."""
    payload: dict[str, Any] = {}
    for f in consumer.fields:
        if f.name == "...":
            continue
        payload[f.name] = PLACEHOLDER.get(f.type, "x")
    encoding = consumer.encoding
    if encoding == UNKNOWN_ENC and payload:
        encoding = JSON_ENC
    return encoding, payload


def validate_against(producer: Surface, encoding: str, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if producer.encoding not in (UNKNOWN_ENC, NONE_ENC) and encoding not in (UNKNOWN_ENC,):
        if producer.encoding != encoding:
            errors.append(f"encoding {encoding} but the handler declares {producer.encoding}")
    for f in producer.fields:
        if f.required and f.name not in payload:
            errors.append(f"missing required field `{f.name}` ({f.type})")
    declared = {f.name: f.type for f in producer.fields}
    for name, value in payload.items():
        want = declared.get(name)
        if want is None:
            errors.append(f"field `{name}` is not declared by the handler")
            continue
        if want == "unknown":
            continue
        got = _runtime_type(value)
        if got != want and not (want == "float" and got == "int"):
            errors.append(f"field `{name}` is {got}, handler declares {want}")
    return errors


def _runtime_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "unknown"


def prove_schema(producer: Surface, consumer: Surface) -> Proof:
    """A-R8: construct the request, validate it, never send it."""
    encoding, payload = synthesise(consumer)
    errors = validate_against(producer, encoding, payload)
    if consumer.method != producer.method:
        errors.insert(0, f"client method {consumer.method} differs from handler method {producer.method}")
    if errors:
        return Proof(
            seam=consumer.seam,
            tier=TIER_SCHEMA,
            passed=False,
            detail="the request this client builds is rejected by the handler's schema: "
            + "; ".join(errors),
            errors=errors,
            producer_loc=producer.loc,
            consumer_loc=consumer.loc,
        )
    return Proof(
        seam=consumer.seam,
        tier=TIER_SCHEMA,
        passed=True,
        detail="the request this client builds satisfies the handler's schema",
        producer_loc=producer.loc,
        consumer_loc=consumer.loc,
    )


# ------------------------------------------------------- tier 2: test client
def _store_fingerprint(root: Path) -> str:
    """B-R11: fingerprint every local store so a mutation cannot go unnoticed."""
    h = hashlib.sha256()
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        for f in sorted(root.rglob(pattern)):
            if any(p in {"node_modules", ".git", ".venv"} for p in f.parts):
                continue
            try:
                h.update(f.name.encode())
                h.update(str(f.stat().st_size).encode())
                h.update(hashlib.sha256(f.read_bytes()).digest())
            except OSError:
                continue
    return h.hexdigest()


def load_app(root: Path, spec: str) -> Any:
    """Import `module:attr` with the repository on the path."""
    module_name, _, attr = spec.partition(":")
    if not attr:
        attr = "app"
    root_str = str(root)
    added = root_str not in sys.path
    if added:
        sys.path.insert(0, root_str)
    try:
        module = importlib.import_module(module_name)
        return getattr(module, attr)
    finally:
        if added and root_str in sys.path:
            sys.path.remove(root_str)


def prove_test_client(
    root: Path, app: Any, producer: Surface, consumer: Surface
) -> Proof:
    """A-R9: run the real handler in-process, then verify nothing was written."""
    # Starlette owns the implementation; fastapi.testclient only re-exports it.
    # Importing it directly keeps this tier working against any ASGI app and
    # survives a broken FastAPI install.
    try:
        from starlette.testclient import TestClient
    except Exception:  # pragma: no cover
        try:
            from fastapi.testclient import TestClient  # type: ignore[no-redef]
        except Exception as exc:
            return Proof(
                seam=producer.seam,
                tier=TIER_TEST_CLIENT,
                passed=None,
                detail=f"test client unavailable, proof skipped ({exc})",
                producer_loc=producer.loc,
                consumer_loc=consumer.loc,
            )

    encoding, payload = synthesise(consumer)
    before = _store_fingerprint(root)

    # Deliberately NOT used as a context manager. Entering the client runs the
    # app's lifespan startup, and startup handlers routinely open connections,
    # run migrations and warm caches. Those are exactly the side effects proof
    # must not cause, so the handler is called without them.
    path = consumer.path.replace("{}", "1")
    client = None
    response = None
    failure = None
    try:
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        if encoding == MULTIPART:
            types = {f.name: f.type for f in consumer.fields}
            files = {k: (k if types.get(k) == "file" else None, str(v)) for k, v in payload.items()}
            response = client.request(consumer.method, path, files=files or None)
        elif encoding == JSON_ENC:
            response = client.request(consumer.method, path, json=payload or None)
        else:
            response = client.request(consumer.method, path, data=payload or None)
    except Exception as exc:
        failure = str(exc)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                failure = str(exc)

    after = _store_fingerprint(root)
    if before != after:
        return Proof(
            seam=producer.seam,
            tier=TIER_TEST_CLIENT,
            passed=False,
            status=response.status_code if response is not None else None,
            detail=(
                "ABORTED: the local store changed during proof. The handler is not "
                "transactional under the test client, so execution proof is unsafe here"
            ),
            producer_loc=producer.loc,
            consumer_loc=consumer.loc,
        )

    if failure is not None:
        return Proof(
            seam=producer.seam,
            tier=TIER_TEST_CLIENT,
            passed=None,
            detail=f"could not drive the app in-process, proof skipped ({failure})",
            producer_loc=producer.loc,
            consumer_loc=consumer.loc,
        )
    ok = None if 300 <= response.status_code < 400 else 200 <= response.status_code < 300
    return Proof(
        seam=producer.seam,
        tier=TIER_TEST_CLIENT,
        passed=ok,
        status=response.status_code,
        detail=(
            f"handler redirected ({response.status_code}); execution check did not follow it"
            if ok is None else
            f"handler answered {response.status_code} to the request this client builds"
            if not ok
            else f"handler accepted the request ({response.status_code})"
        ),
        producer_loc=producer.loc,
        consumer_loc=consumer.loc,
    )


# -------------------------------------------------------------- tier 3: http
class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UnsafeRequest("Execution checks do not follow HTTP redirects")


def prove_http(base_url: str, producer: Surface) -> Proof:
    """A-R12: real HTTP, and only for methods that cannot change anything."""
    assert_local(base_url)
    assert_transport(producer.method, "wire")
    url = base_url.rstrip("/") + producer.path.replace("{}", "1")
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise UnsafeRequest("Execution checks require a local HTTP URL without credentials")
    if parsed.hostname == "localhost":
        url = parsed._replace(netloc="127.0.0.1" + (f":{parsed.port}" if parsed.port else "")).geturl()
    request = urllib.request.Request(url, method=producer.method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())
    try:
        with opener.open(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (OSError, UnsafeRequest) as exc:
        return Proof(producer.seam, TIER_HTTP, None, f"server not reachable or redirect refused ({exc})", producer_loc=producer.loc)
    return Proof(
        seam=producer.seam,
        tier=TIER_HTTP,
        passed=None if 300 <= status < 400 else 200 <= status < 300,
        status=status,
        detail=f"{producer.method} {producer.path} answered {status}",
        producer_loc=producer.loc,
    )


# ------------------------------------------------------------------ driver
def prove_all(
    root: Path,
    producers: list[Surface],
    consumers: list[Surface],
    findings: list[Finding],
    app_spec: str | None = None,
    base_url: str | None = None,
) -> list[Proof]:
    """Prove only the seams stage 1 already flagged. Nothing else is touched.

    `base_url` enables tier 3, which issues a real request against a server the
    caller is already running. It is restricted to GET, HEAD and OPTIONS, so a
    seam whose method can change state is never proven this way.
    """
    app = None
    proofs: list[Proof] = []
    if app_spec:
        try:
            app = load_app(root, app_spec)
        except Exception as exc:
            proofs.append(Proof(app_spec, TIER_TEST_CLIENT, None, f"could not import the application ({exc})"))

    if base_url:
        assert_local(base_url)  # fail before any request is built, not after

    checked = set()
    for finding in findings:
        if finding.confidence != HIGH or finding.seam.split(" ", 1)[0] not in SAFE_METHODS | MUTATING:
            continue
        callers = [c for c in consumers if c.seam == finding.seam and
                   (finding.consumer_loc is None or c.loc == finding.consumer_loc)]
        consumer = callers[0] if len(callers) == 1 else None
        handlers = [p for p in producers if p.loc == finding.producer_loc and
                    (consumer is None or p.path == consumer.path)]
        if not handlers:
            handlers = [p for p in producers if p.seam == finding.seam]
        producer = handlers[0] if len(handlers) == 1 else None
        pair = (finding.seam, producer, consumer)
        if pair in checked:
            continue
        checked.add(pair)
        if producer is None or (consumer is None and not base_url):
            proofs.append(Proof(finding.seam, TIER_SCHEMA, None,
                                "could not identify one producer and the flagged caller for this check",
                                producer_loc=finding.producer_loc, consumer_loc=finding.consumer_loc))
            continue
        if consumer is not None:
            proofs.append(prove_schema(producer, consumer))
            if app is not None:
                proof = prove_test_client(root, app, producer, consumer)
                proof.seam = consumer.seam
                proofs.append(proof)
        request = replace(producer, method=consumer.method, path=consumer.path) if consumer else producer
        if base_url and request.method in SAFE_METHODS:
            proofs.append(prove_http(base_url, request))
    return proofs
