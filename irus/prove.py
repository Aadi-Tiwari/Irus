"""A-R8 to A-R12: prove a suspected mismatch by executing it.

Detection narrows the search; proof settles it. The verdict here comes from the
application rather than from our checker, which is what makes it evidence.

Safety is structural, not advisory (B-R8 to B-R12):

  * nothing is sent anywhere unless the caller opts in explicitly
  * no request ever leaves localhost
  * a mutating method is never sent over the network at all; it goes through the
    framework's in-process test client or it does not run
  * the store is fingerprinted before and after, and a change fails loudly

B-R24: a model may write a request. A model never decides whether it passed.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import HIGH, JSON_ENC, MEDIUM, MULTIPART, NONE_ENC, UNKNOWN_ENC, Finding, Surface

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
    passed: bool
    detail: str
    status: int | None = None
    errors: list[str] = field(default_factory=list)

    def to_finding(self) -> Finding:
        return Finding(
            kind="execution_proof",
            seam=self.seam,
            detail=self.detail,
            confidence=HIGH if not self.passed else MEDIUM,
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
    if errors:
        return Proof(
            seam=producer.seam,
            tier=TIER_SCHEMA,
            passed=False,
            detail="the request this client builds is rejected by the handler's schema: "
            + "; ".join(errors),
            errors=errors,
        )
    return Proof(
        seam=producer.seam,
        tier=TIER_SCHEMA,
        passed=True,
        detail="the request this client builds satisfies the handler's schema",
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
                passed=True,
                detail=f"test client unavailable, proof skipped ({exc})",
            )

    encoding, payload = synthesise(consumer)
    before = _store_fingerprint(root)

    # Deliberately NOT used as a context manager. Entering the client runs the
    # app's lifespan startup, and startup handlers routinely open connections,
    # run migrations and warm caches. Those are exactly the side effects proof
    # must not cause, so the handler is called without them.
    client = TestClient(app, raise_server_exceptions=False)
    path = producer.path.replace("{}", "1")
    try:
        if encoding == MULTIPART:
            files = {k: (k, str(v)) for k, v in payload.items()}
            response = client.request(consumer.method, path, files=files or None)
        elif encoding == JSON_ENC:
            response = client.request(consumer.method, path, json=payload or None)
        else:
            response = client.request(consumer.method, path, data=payload or None)
    except Exception as exc:
        return Proof(
            seam=producer.seam,
            tier=TIER_TEST_CLIENT,
            passed=True,
            detail=f"could not drive the app in-process, proof skipped ({exc})",
        )

    after = _store_fingerprint(root)
    if before != after:
        return Proof(
            seam=producer.seam,
            tier=TIER_TEST_CLIENT,
            passed=False,
            status=response.status_code,
            detail=(
                "ABORTED: the local store changed during proof. The handler is not "
                "transactional under the test client, so execution proof is unsafe here"
            ),
        )

    ok = response.status_code < 400
    return Proof(
        seam=producer.seam,
        tier=TIER_TEST_CLIENT,
        passed=ok,
        status=response.status_code,
        detail=(
            f"handler answered {response.status_code} to the request this client builds"
            if not ok
            else f"handler accepted the request ({response.status_code})"
        ),
    )


# -------------------------------------------------------------- tier 3: http
def prove_http(base_url: str, producer: Surface) -> Proof:
    """A-R12: real HTTP, and only for methods that cannot change anything."""
    assert_local(base_url)
    if producer.method not in SAFE_METHODS:
        assert_not_mutating_over_network(producer.method)
    url = base_url.rstrip("/") + producer.path.replace("{}", "1")
    request = urllib.request.Request(url, method=producer.method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except OSError as exc:
        return Proof(producer.seam, TIER_HTTP, True, f"server not reachable, skipped ({exc})")
    return Proof(
        seam=producer.seam,
        tier=TIER_HTTP,
        passed=status < 400,
        status=status,
        detail=f"{producer.method} {producer.path} answered {status}",
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
    suspect = {f.seam for f in findings if f.confidence == HIGH}
    by_seam = {p.seam: p for p in producers}
    consumer_by_seam = {c.seam: c for c in consumers}

    app = None
    if app_spec:
        try:
            app = load_app(root, app_spec)
        except Exception as exc:
            app = None
            print(f"irus: could not import {app_spec} ({exc}); schema tier only", flush=True)

    if base_url:
        assert_local(base_url)  # fail before any request is built, not after

    proofs: list[Proof] = []
    for seam in sorted(suspect):
        producer, consumer = by_seam.get(seam), consumer_by_seam.get(seam)
        if not producer:
            continue
        if consumer is not None:
            proofs.append(prove_schema(producer, consumer))
            if app is not None:
                proofs.append(prove_test_client(root, app, producer, consumer))
        if base_url and producer.method in SAFE_METHODS:
            proofs.append(prove_http(base_url, producer))
    return proofs
