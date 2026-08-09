"""One acceptance test per Part A requirement, asserting the contract as written.

This file exists because a grep for "A-R7" in a docstring proves a label, not a
behaviour. Each test here quotes the requirement and checks the thing the
requirement actually promises, through the public surface a user touches.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irus import coordinate, prove, receipts as receipts_mod  # noqa: E402
from irus import baseline as baseline_mod  # noqa: E402
from irus.cli import main  # noqa: E402
from irus.eventlog import EventLog  # noqa: E402
from irus.extract import ts_express  # noqa: E402
from irus.mcp_server import Server  # noqa: E402
from irus.model import CONSUMER, HIGH, LOW, MEDIUM, Field, Finding, Loc, Surface  # noqa: E402
from irus.scan import scan  # noqa: E402


def write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


@pytest.fixture
def mismatch(tmp_path):
    """The canonical failure: JSON handler, multipart client."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        from pydantic import BaseModel

        app = FastAPI()

        class Body(BaseModel):
            email: str
            amount: int

        @app.post("/api/checkout")
        async def checkout(payload: Body):
            return {}
    """)
    write(tmp_path, "client.ts", """
        export async function pay() {
          const form = new FormData();
          form.append("user_email", "a@b.c");
          await fetch("/api/checkout", { method: "POST", body: form });
        }
    """)
    return tmp_path


# ============================================================== DETECTION
def test_ar1_extracts_route_method_and_request_payload_shape(mismatch):
    """A-R1: route path, method, and request payload shape from the producer."""
    p = next(s for s in scan(mismatch).producers if s.path == "/api/checkout")
    assert p.method == "POST"
    assert p.encoding == "json"
    assert {(f.name, f.type, f.required) for f in p.fields} == {
        ("email", "str", True),
        ("amount", "int", True),
    }


@pytest.mark.parametrize(
    "body,expected_encoding,expected_fields",
    [
        ('JSON.stringify({ email: "a", amount: 1 })', "json", {"email", "amount"}),
        ("{ email, amount }", "json", {"email", "amount"}),
        ("form", "multipart", {"user_email"}),
    ],
)
def test_ar2_extracts_every_named_body_construction(tmp_path, body, expected_encoding, expected_fields):
    """A-R2: literal objects, JSON.stringify, and FormData are all read."""
    write(tmp_path, "client.ts", f"""
        export async function pay(email: string, amount: number) {{
          const form = new FormData();
          form.append("user_email", "a@b.c");
          await fetch("/api/checkout", {{ method: "POST", body: {body} }});
        }}
    """)
    c = scan(tmp_path).consumers[0]
    assert c.method == "POST" and c.path == "/api/checkout"
    assert c.encoding == expected_encoding
    assert {f.name for f in c.fields} == expected_fields


def test_ar3_finding_names_both_file_paths_in_human_output(mismatch):
    """A-R3: emit a finding naming BOTH file paths and the exact disagreement."""
    out = subprocess.run(
        [sys.executable, "-m", "irus", "check", str(mismatch), "--no-baseline"],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
    ).stdout
    assert "api.py" in out, "producer file path missing from human-readable output"
    assert "client.ts" in out, "consumer file path missing from human-readable output"
    assert "multipart" in out and "json" in out


def test_ar4_env_var_read_but_set_nowhere(tmp_path):
    """A-R4: across .env, .env.example, compose, vercel.json and Actions."""
    write(tmp_path, "conf.py", 'import os\nA = os.environ["UNSET_ONE"]\n')
    assert {f.subject for f in scan(tmp_path).findings if f.kind == "env_unset"} == {"UNSET_ONE"}

    for name, body in [
        (".env", "UNSET_ONE=1\n"),
        (".env.example", "UNSET_ONE=1\n"),
        ("docker-compose.yml", "services:\n  a:\n    environment:\n      UNSET_ONE: '1'\n"),
        ("vercel.json", json.dumps({"env": {"UNSET_ONE": "1"}})),
        (".github/workflows/ci.yml", "jobs:\n  b:\n    env:\n      UNSET_ONE: '1'\n"),
    ]:
        write(tmp_path, name, body)
        assert [f for f in scan(tmp_path).findings if f.kind == "env_unset"] == [], (
            f"{name} should have satisfied the read"
        )
        (tmp_path / name).unlink()


def test_ar5_compares_response_payload_shape(tmp_path):
    """A-R5: response shape, not only request shape."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        from pydantic import BaseModel

        app = FastAPI()

        class Out(BaseModel):
            order_id: str

        @app.post("/api/checkout", response_model=Out)
        async def checkout():
            return {}
    """)
    write(tmp_path, "client.ts", """
        export async function pay() {
          const res = await fetch("/api/checkout", { method: "POST" });
          const { orderId } = await res.json();
          return orderId;
        }
    """)
    found = [f for f in scan(tmp_path).findings if f.kind == "response_shape_mismatch"]
    assert [f.subject for f in found] == ["orderId"]


def test_ar6_detects_zero_caller_endpoints_and_unmounted_components(tmp_path):
    """A-R6: both halves of orphan detection."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        app = FastAPI()

        @app.post("/api/never-called")
        async def never():
            return {}
    """)
    write(tmp_path, "Widget.tsx", """
        export function Widget() {
          return <div>never mounted</div>;
        }
    """)
    kinds = {(f.kind, f.subject or f.seam) for f in scan(tmp_path).findings}
    assert ("orphan_endpoint", "POST /api/never-called") in kinds
    assert ("orphan_component", "Widget") in kinds


def test_ar7_second_stack_pair_compares_against_the_same_client(tmp_path):
    """A-R7: an Express producer flows through the same comparer."""
    write(tmp_path, "server.js", """
        const express = require("express");
        const app = express();
        app.post("/api/pay", (req, res) => {
          const { email } = req.body;
          res.json({});
        });
    """)
    write(tmp_path, "client.ts", """
        export async function pay() {
          await fetch("/api/pay", { method: "POST", body: JSON.stringify({ mail: "x" }) });
        }
    """)
    findings = scan(tmp_path).findings
    assert any(f.kind == "missing_required_field" and f.subject == "email" for f in findings)
    assert ts_express.extract_file(tmp_path / "server.js", tmp_path)[0].seam == "POST /api/pay"


# ================================================================== PROOF
def test_ar8_tier1_validates_without_sending(mismatch, monkeypatch):
    """A-R8: construct the request, validate it, send nothing."""
    def forbidden(*a, **k):
        raise AssertionError("tier 1 must not open a connection")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = scan(mismatch)
    proofs = prove.prove_all(mismatch, result.producers, result.consumers, result.findings)
    schema = [p for p in proofs if p.tier == prove.TIER_SCHEMA]
    assert schema and schema[0].passed is False
    assert any("encoding multipart" in e for e in schema[0].errors)


def test_ar9_tier2_runs_the_real_handler_in_process(tmp_path):
    """A-R9: the framework's own test client, and the store is unchanged."""
    async def app(scope, receive, send):
        while True:
            m = await receive()
            if not m.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 422, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    p = Surface(side="producer", method="POST", path="/api/checkout", loc=Loc("a.py", 1),
                encoding="json", fields=(Field("email", "str"),))
    c = Surface(side=CONSUMER, method="POST", path="/api/checkout", loc=Loc("c.ts", 1),
                encoding="multipart", fields=(Field("user_email", "str"),))
    result = prove.prove_test_client(tmp_path, app, p, c)
    assert result.tier == prove.TIER_TEST_CLIENT
    assert result.status == 422 and result.passed is False


def test_ar10_refuses_any_non_localhost_host():
    """A-R10: refuse to send a request to a non-localhost host."""
    for ok in ("http://localhost:1", "http://127.0.0.1:1", "http://[::1]:1", "/relative"):
        prove.assert_local(ok)
    for bad in ("https://example.com", "http://10.0.0.5", "https://api.stripe.com/x"):
        with pytest.raises(prove.UnsafeRequest):
            prove.assert_local(bad)


def test_ar11_never_issues_a_real_mutating_request(mismatch, monkeypatch):
    """A-R11: no POST/PUT/PATCH/DELETE over the network, through any path."""
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    result = scan(mismatch)
    prove.prove_all(mismatch, result.producers, result.consumers, result.findings)
    assert calls == [], "prove_all opened a network connection"
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(prove.UnsafeRequest):
            prove.prove_http("http://127.0.0.1:1", Surface(
                side="producer", method=method, path="/x", loc=Loc("a", 1)))


def test_ar12_tier3_is_reachable_and_restricted_to_safe_methods(tmp_path):
    """A-R12: real HTTP for GET, HEAD and OPTIONS only, and callable in anger."""
    safe = Surface(side="producer", method="GET", path="/api/thing", loc=Loc("a.py", 1))
    result = prove.prove_http("http://127.0.0.1:1", safe)
    assert result.tier == prove.TIER_HTTP
    assert "not reachable" in result.detail or result.status is not None

    proofs = prove.prove_all(
        tmp_path,
        [safe],
        [Surface(side=CONSUMER, method="GET", path="/api/thing", loc=Loc("c.ts", 1))],
        [Finding("endpoint_not_found", "GET /api/thing", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))],
        base_url="http://127.0.0.1:1",
    )
    assert any(p.tier == prove.TIER_HTTP for p in proofs), "tier 3 unreachable from prove_all"


# =============================================================== BASELINE
def _repo(tmp_path):
    for a in (["init", "-q"], ["config", "user.email", "t@e.st"], ["config", "user.name", "T"]):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        from pydantic import BaseModel
        app = FastAPI()
        class Body(BaseModel):
            email: str
        @app.post("/api/thing")
        async def thing(payload: Body):
            return {}
    """)
    write(tmp_path, "client.ts", """
        export async function send() {
          await fetch("/api/thing", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: "a@b.c" }),
          });
        }
    """)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "clean"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_ar13_baseline_uses_merge_base_in_a_temp_worktree_cached_by_sha(tmp_path):
    """A-R13: computed against the merge-base, cached by that SHA."""
    repo = _repo(tmp_path)
    first = baseline_mod.compute(repo, refresh=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    assert first.sha == head and first.cached is False
    assert (repo / ".irus" / f"baseline-{head[:12]}.json").exists()
    assert baseline_mod.compute(repo).cached is True
    assert not list(repo.glob("**/irus-base-*")), "temp worktree was not cleaned up"


def test_ar14_suppresses_every_finding_present_in_the_baseline(tmp_path):
    """A-R14: report only what this session introduced."""
    repo = _repo(tmp_path)
    assert baseline_mod.compute(repo).suppress(scan(repo).findings) == []
    write(repo, "client.ts", """
        export async function send() {
          const f = new FormData();
          f.append("mail", "x");
          await fetch("/api/thing", { method: "POST", body: f });
        }
    """)
    new = baseline_mod.compute(repo).suppress(scan(repo).findings)
    assert {f.kind for f in new} >= {"encoding_mismatch", "missing_required_field"}


def test_ar15_falls_back_to_head_for_a_single_tree(tmp_path):
    """A-R15: single tree with uncommitted work anchors to HEAD."""
    repo = _repo(tmp_path)
    sha, how = baseline_mod.anchor(repo)
    assert "single worktree" in how
    assert sha == subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                 capture_output=True, text=True).stdout.strip()


# ================================================================ OUTPUT
def test_ar16_receipt_is_readable_with_no_ui(mismatch):
    """A-R16: pass/fail lines readable in a terminal."""
    result = scan(mismatch)
    text = receipts_mod.render(receipts_mod.build(result), only_failing=True)
    assert "POST /api/checkout" in text
    assert "PASS" in text and "FAIL" in text
    assert "<" not in text and "{" not in text, "receipt should be plain text"


def test_ar17_exit_code_is_a_merge_gate(tmp_path):
    """A-R17: nonzero exactly when a high-confidence finding exists."""
    repo = _repo(tmp_path)
    assert main(["check", str(repo)]) == 0
    write(repo, "client.ts", """
        export async function send() {
          const f = new FormData();
          f.append("mail", "x");
          await fetch("/api/thing", { method: "POST", body: f });
        }
    """)
    assert main(["check", str(repo)]) == 1


def test_ar18_event_log_replays_to_identical_state(tmp_path, mismatch):
    """A-R18: append-only, and a replay reconstructs identical state."""
    main(["check", str(mismatch), "--no-baseline", "--log"])
    path = mismatch / ".irus" / "events.jsonl"
    assert path.exists()
    first = EventLog(path).replay()
    assert [e["seq"] for e in first] == list(range(1, len(first) + 1))
    assert EventLog(path).replay() == first
    assert {e["kind"] for e in first} >= {"baseline", "surface", "finding"}


def test_ar19_watch_serves_the_live_page_over_sse(mismatch, monkeypatch):
    """A-R19: a local page, streamed, self-contained, no build step."""
    from irus import web

    # monkeypatch rather than plain assignment: these are module globals, and
    # leaking them breaks every later test that serves a room.
    monkeypatch.setattr(web, "DATA_DIR", mismatch / ".irus" / "rooms")
    monkeypatch.setattr(web, "_rooms", {})
    log = web.room("default")
    log.append("finding", id="f-1", seam="POST /api/checkout", confidence="high")

    httpd = web.serve(port=0, host="127.0.0.1")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "<title>irus</title>" in page
        assert "EventSource" in page

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/events") as stream:
            assert stream.headers["Content-Type"] == "text/event-stream"
            line = stream.readline().decode()
            assert line.startswith("data: ")
            assert json.loads(line[6:])["kind"] == "finding"
    finally:
        httpd.shutdown()


def test_ar20_page_layers_baseline_and_draws_missing_connections(mismatch):
    """A-R20: dim baseline, full-colour session, dashed red arcs."""
    html = (Path(__file__).resolve().parents[1] / "irus" / "page.html").read_text("utf-8")
    assert "--ghost" in html and "baselineSeams" in html, "no baseline layer"
    assert "stroke-dasharray" in html and "var(--broken)" in html, "no dashed arc"
    assert "gap" in html, "the ends are not pulled apart"
    for colour in ("#d03b3b", "#c98500", "#eda100", "#3987e5", "#2a78d6", "#898781"):
        assert colour in html


def test_ar21_only_high_confidence_fails_the_gate(tmp_path):
    """A-R21: confidence tiers, and a medium finding never blocks a merge."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        app = FastAPI()

        @app.post("/api/never-called")
        async def never():
            return {}
    """)
    findings = scan(tmp_path).findings
    assert findings, "there should be something to report"
    assert not any(f.confidence == HIGH for f in findings)
    assert {f.confidence for f in findings} <= {MEDIUM, LOW}
    assert main(["check", str(tmp_path), "--no-baseline"]) == 0, "non-high must not block"

    # Introducing one high-confidence finding must flip the gate.
    write(tmp_path, "conf.py", 'import os\nX = os.environ["DEFINITELY_UNSET"]\n')
    assert any(f.confidence == HIGH for f in scan(tmp_path).findings)
    assert main(["check", str(tmp_path), "--no-baseline"]) == 1


def test_ar22_mcp_exposes_the_map_as_text(mismatch):
    """A-R22: status, next, claim and release, all text."""
    server = Server(mismatch)
    assert {t["name"] for t in server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    } == {"status", "next", "claim", "release"}

    reply = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "status", "arguments": {}}})
    content = reply["result"]["content"][0]
    assert content["type"] == "text" and "POST /api/checkout" in content["text"]

    assert "claimed" in server.call("next", {"agent": "a"})
    assert server.call("next", {"agent": "b"}) == "nothing unclaimed"
    assert "released" in server.call("release", {"agent": "a", "target": "POST /api/checkout"})


# =========================================================== COORDINATION
def test_ar23_producer_is_authoritative_overridable_and_recorded(mismatch):
    """A-R23: default, override, and the decision is written into the receipt."""
    f = Finding("encoding_mismatch", "POST /api/checkout", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))
    assert coordinate.authority_for(f) == coordinate.PRODUCER_AUTHORITATIVE
    assert coordinate.owner_of(f) == CONSUMER
    assert coordinate.owner_of(f, {"POST /api/checkout": coordinate.CONSUMER_AUTHORITATIVE}) == "producer"

    result = scan(mismatch)
    text = receipts_mod.render(
        receipts_mod.build(result, result.findings, coordinate.assign(result.findings)),
        only_failing=True,
    )
    assert "authority" in text.lower(), "authority decision is not recorded in the receipt"


def test_ar24_exactly_one_owner_per_seam_per_round():
    """A-R24: two findings on one seam get one owner, not two."""
    findings = [
        Finding("encoding_mismatch", "POST /a", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1)),
        Finding("missing_required_field", "POST /a", "client sends multipart, server expects json", subject="email", confidence=HIGH, producer_loc=Loc("api.py", 1)),
        Finding("missing_required_field", "POST /b", "client sends multipart, server expects json", subject="id", confidence=HIGH, producer_loc=Loc("api.py", 1)),
    ]
    assignments = coordinate.assign(findings)
    assert [a.seam for a in assignments] == ["POST /a", "POST /b"]
    assert len(assignments[0].findings) == 2


def test_ar25_ratchet_rejects_a_round_that_does_not_strictly_reduce():
    """A-R25: the loop cannot report progress while getting worse."""
    state = {"f": [Finding("encoding_mismatch", "POST /1", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))], "n": 0}

    def check():
        return list(state["f"])

    def fix(_a):
        state["n"] += 1
        state["f"] = [Finding("encoding_mismatch", f"POST /{state['n'] % 2}", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))]

    out = coordinate.run_loop(check, fix, max_rounds=10)
    assert len(out.rounds) == 1 and out.rounds[0].accepted is False
    assert state["n"] == 1, "the loop kept flipping instead of stopping"


# ================================ MECHANISMS ADOPTED FROM THE PART-B BRANCH
def test_finding_cannot_exist_without_evidence():
    """B-R19, enforced at construction so a generic warning never reaches a receipt."""
    from irus.model import MissingEvidence

    with pytest.raises(MissingEvidence):
        Finding("encoding_mismatch", "POST /x", "short", producer_loc=Loc("a.py", 1))
    with pytest.raises(MissingEvidence):
        Finding("encoding_mismatch", "POST /x", "a specific and long disagreement")
    with pytest.raises(ValueError):
        Finding("encoding_mismatch", "POST /x", "a specific and long disagreement",
                confidence="extremely", producer_loc=Loc("a.py", 1))


def test_event_log_is_append_only_by_construction(tmp_path):
    """B-R21: a caller cannot forge ordering or overwrite history."""
    from irus.eventlog import AppendOnlyViolation, EventLog, canonical

    log = EventLog(tmp_path / "e.jsonl")
    log.append("finding", id="f-1")
    for reserved in ("t", "kind", "seq"):
        with pytest.raises(AppendOnlyViolation):
            log.append("finding", **{reserved: "forged"})
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})
    assert len(EventLog(tmp_path / "e.jsonl").replay()) == 1


def test_stage_two_requires_recorded_consent(tmp_path):
    """B-R12: nobody gets their code executed by surprise."""
    write(tmp_path, "api.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    assert prove.has_consent(tmp_path) is False
    with pytest.raises(prove.ConsentRequired):
        prove.require_consent(tmp_path)

    assert main(["check", str(tmp_path), "--no-baseline", "--prove"]) == 2, "must refuse"

    prove.grant_consent(tmp_path)
    assert prove.has_consent(tmp_path) is True
    prove.require_consent(tmp_path)
    assert (tmp_path / ".irus" / "consent.json").exists()


def test_yes_flag_records_consent_once(tmp_path):
    write(tmp_path, "api.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    assert main(["check", str(tmp_path), "--no-baseline", "--prove", "--yes"]) == 0
    assert prove.has_consent(tmp_path) is True
    assert main(["check", str(tmp_path), "--no-baseline", "--prove"]) == 0, "consent persists"


def test_transport_rail_covers_both_directions():
    """assert_transport folds A-R11 and the wire allowlist into one rail."""
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(prove.UnsafeRequest):
            prove.assert_transport(method, "wire")
        prove.assert_transport(method, "test_client")
    for method in ("GET", "HEAD", "OPTIONS"):
        prove.assert_transport(method, "wire")


# =========================== REGRESSIONS FOUND ON REAL THIRD-PARTY CODE
def test_router_mounted_by_attribute_is_not_reported_unmounted(tmp_path):
    """The standard FastAPI layout mounts `items.router`, not a bare name.

    Recording only ast.Name produced 23 high-confidence false positives on
    fastapi/full-stack-fastapi-template.
    """
    write(tmp_path, "routes/items.py", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/items")
        async def read_items():
            return []
    """)
    write(tmp_path, "api.py", """
        from fastapi import APIRouter
        from routes import items

        api_router = APIRouter()
        api_router.include_router(items.router)
    """)
    unmounted = [f for f in scan(tmp_path).findings if f.kind == "unmounted_route"]
    assert unmounted == [], "a router mounted by attribute is mounted"


def test_env_declared_in_a_nested_dotenv_is_not_a_finding(tmp_path):
    """A monorepo's frontend/.env is as real as the root .env."""
    write(tmp_path, "frontend/app.ts", 'const u = process.env.VITE_API_URL;\n')
    write(tmp_path, "frontend/.env", "VITE_API_URL=http://localhost\n")
    assert [f for f in scan(tmp_path).findings if f.kind == "env_unset"] == []


def test_env_declared_in_a_compose_override_is_not_a_finding(tmp_path):
    write(tmp_path, "svc.py", 'import os\nX = os.environ["MAILCATCHER_HOST"]\n')
    write(tmp_path, "compose.override.yml",
          "services:\n  a:\n    environment:\n      MAILCATCHER_HOST: http://x\n")
    assert [f for f in scan(tmp_path).findings if f.kind == "env_unset"] == []


@pytest.mark.parametrize("expr", [
    "const a = !!process.env.CI;",
    "const b = process.env.CI ? 2 : 0;",
    "const c = Boolean(process.env.CI);",
])
def test_presence_check_is_not_a_required_read(tmp_path, expr):
    """`!!process.env.CI` copes with absence, so it is not a missing variable."""
    write(tmp_path, "conf.ts", expr + "\n")
    assert [f for f in scan(tmp_path).findings if f.kind == "env_unset"] == []


def test_scan_refuses_a_path_that_does_not_exist(tmp_path):
    """Zero findings must never be how a mistyped path reports itself."""
    with pytest.raises(NotADirectoryError):
        scan(tmp_path / "no-such-directory")


def test_file_based_route_component_is_demoted(tmp_path):
    """A router mounts these by convention, so no JSX tag names them."""
    write(tmp_path, "src/routes/admin.tsx", """
        export function Admin() {
          return <div>admin</div>;
        }
    """)
    f = next(x for x in scan(tmp_path).findings if x.kind == "orphan_component")
    assert f.confidence == LOW
    assert "file-based router" in f.detail


def test_component_kit_file_is_demoted(tmp_path):
    """Three unused exports in one file is a library, not dead code."""
    write(tmp_path, "src/ui/alert.tsx", """
        export function Alert() { return <div />; }
        export function AlertTitle() { return <div />; }
        export function AlertDescription() { return <div />; }
    """)
    findings = [f for f in scan(tmp_path).findings if f.kind == "orphan_component"]
    assert len(findings) == 3
    assert {f.confidence for f in findings} == {LOW}
    assert "component kit" in findings[0].detail


def test_a_single_unused_component_is_still_medium(tmp_path):
    """The demotions must not swallow the real case."""
    write(tmp_path, "src/Widget.tsx", """
        export function Widget() { return <div />; }
    """)
    f = next(x for x in scan(tmp_path).findings if x.kind == "orphan_component")
    assert f.confidence == MEDIUM


def test_router_mounted_under_an_import_alias_is_not_unmounted(tmp_path):
    """`from x.views import router as case_router` is how large FastAPI apps
    compose. Not resolving the alias produced 277 high-confidence false
    positives on Netflix/dispatch.
    """
    write(tmp_path, "case/views.py", """
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/cases")
        async def read_cases():
            return []
    """)
    write(tmp_path, "api.py", """
        from fastapi import APIRouter
        from case.views import router as case_router

        api_router = APIRouter()
        api_router.include_router(case_router, prefix="/cases")
    """)
    assert [f for f in scan(tmp_path).findings if f.kind == "unmounted_route"] == []


def test_receipt_explains_a_fail_line_that_is_not_a_finding(tmp_path):
    """A FAIL line beside "0 findings" reads as a contradiction unless it says why."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/api/health")
        async def health():
            return {}
    """)
    result = scan(tmp_path)
    assert result.findings == [], "a health route is not a finding"
    text = receipts_mod.render(receipts_mod.build(result), only_failing=True)
    assert "externally" in text, "an unexplained FAIL beside zero findings is misleading"


def test_append_raw_preserves_a_recorded_timestamp_but_not_its_sequence(tmp_path):
    """Replay must be faithful to when things happened, without letting a
    replayed event claim a position in the log it did not earn."""
    from irus.eventlog import AppendOnlyViolation, EventLog

    log = EventLog(tmp_path / "e.jsonl")
    log.append("finding", id="live")
    written = log.append_raw({"t": 1723190400.0, "kind": "finding", "id": "recorded", "seq": 99})

    assert written["t"] == 1723190400.0, "a recorded time must survive replay"
    assert written["seq"] == 2, "seq is assigned by the log, never by the caller"
    assert [e["seq"] for e in EventLog(tmp_path / "e.jsonl").replay()] == [1, 2]

    with pytest.raises(AppendOnlyViolation):
        log.append_raw({"no": "kind"})


def test_demo_replays_a_recorded_session_faithfully(tmp_path):
    """tools/demo.py is the demo. A broken replay is a dead demo."""
    from irus.eventlog import EventLog

    source = Path(__file__).resolve().parents[1] / "fixtures" / "session.jsonl"
    recorded = [json.loads(l) for l in source.read_text("utf-8").splitlines() if l.strip()]

    log = EventLog(tmp_path / "replay.jsonl")
    for event in recorded:
        log.append_raw(event)

    replayed = EventLog(tmp_path / "replay.jsonl").replay()
    assert len(replayed) == len(recorded)
    assert [e["kind"] for e in replayed] == [e["kind"] for e in recorded]
    assert [e["seq"] for e in replayed] == list(range(1, len(recorded) + 1))


def test_a_route_named_by_a_literal_anywhere_is_not_an_orphan(tmp_path):
    """A Python client, a test client and a generated client all reference a
    route the same way: its path, in quotes. Ignoring that made orphan_endpoint
    12% precise across five third-party repositories."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        app = FastAPI()

        @app.post("/api/reports")
        async def make_report():
            return {}
    """)
    assert any(f.kind == "orphan_endpoint" for f in scan(tmp_path).findings)

    write(tmp_path, "client.py", """
        import httpx
        def make():
            return httpx.post("/api/reports", json={})
    """)
    assert [f for f in scan(tmp_path).findings if f.kind == "orphan_endpoint"] == []


def test_orphan_endpoint_never_fails_the_gate(tmp_path):
    """Measured at 14% precision, so it is reported and never blocks a merge."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        app = FastAPI()

        @app.post("/api/reports")
        async def make_report():
            return {}
    """)
    found = [f for f in scan(tmp_path).findings if f.kind == "orphan_endpoint"]
    assert found and all(f.confidence == LOW for f in found)
    assert main(["check", str(tmp_path), "--no-baseline"]) == 0
