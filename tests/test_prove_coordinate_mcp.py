"""Regression suite for A-R8 to A-R12, A-R19, A-R20, A-R22, A-R23 to A-R25.

Same rule as the other suite: never weaken an assertion to make a test pass.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irus import coordinate, prove  # noqa: E402
from irus.mcp_server import Server  # noqa: E402
from irus.model import CONSUMER, HIGH, JSON_ENC, MEDIUM, MULTIPART, PRODUCER, Loc  # noqa: E402
from irus.model import Field, Finding, Loc, Surface  # noqa: E402


def producer(**kw) -> Surface:
    base = dict(
        side=PRODUCER,
        method="POST",
        path="/api/checkout",
        loc=Loc("api.py", 1),
        encoding=JSON_ENC,
        fields=(Field("email", "str"), Field("amount", "int")),
    )
    base.update(kw)
    return Surface(**base)


def consumer(**kw) -> Surface:
    base = dict(
        side=CONSUMER,
        method="POST",
        path="/api/checkout",
        loc=Loc("client.ts", 1),
        encoding=MULTIPART,
        fields=(Field("user_email", "str"), Field("total", "str")),
    )
    base.update(kw)
    return Surface(**base)


# ------------------------------------------------------- A-R8 schema tier
def test_schema_tier_rejects_the_request_the_client_actually_builds():
    proof = prove.prove_schema(producer(), consumer())
    assert proof.passed is False
    joined = " ".join(proof.errors)
    assert "encoding multipart" in joined
    assert "missing required field `email`" in joined
    assert "missing required field `amount`" in joined


def test_schema_tier_passes_when_the_two_sides_agree():
    ok = consumer(encoding=JSON_ENC, fields=(Field("email", "str"), Field("amount", "int")))
    assert prove.prove_schema(producer(), ok).passed is True


def test_schema_tier_accepts_an_int_where_a_float_is_declared():
    p = producer(fields=(Field("amount", "float"),))
    c = consumer(encoding=JSON_ENC, fields=(Field("amount", "int"),))
    assert prove.prove_schema(p, c).passed is True


def test_synthesise_skips_the_spread_marker():
    c = consumer(fields=(Field("email", "str"), Field("...", "unknown", required=False)))
    _, payload = prove.synthesise(c)
    assert "..." not in payload


# --------------------------------------------------- A-R10, A-R11 guards
def test_refuses_to_send_anywhere_but_localhost():
    prove.assert_local("http://127.0.0.1:8000")
    prove.assert_local("http://localhost:3000/api")
    prove.assert_local("/api/relative")
    with pytest.raises(prove.UnsafeRequest):
        prove.assert_local("https://api.stripe.com/v1/charges")


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_refuses_every_mutating_method_over_the_network(method):
    with pytest.raises(prove.UnsafeRequest):
        prove.assert_not_mutating_over_network(method)


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_allows_methods_that_cannot_change_anything(method):
    prove.assert_not_mutating_over_network(method)


def test_http_tier_refuses_a_mutating_route_outright():
    with pytest.raises(prove.UnsafeRequest):
        prove.prove_http("http://127.0.0.1:8000", producer())


def test_http_tier_refuses_a_remote_host_before_looking_at_the_method():
    with pytest.raises(prove.UnsafeRequest):
        prove.prove_http("https://example.com", producer(method="GET"))


# ------------------------------------------------- A-R9 in-process client
def asgi_app(on_request=None):
    """A minimal ASGI app: 422 unless the body is JSON with email and amount."""

    async def app(scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        if on_request is not None:
            on_request(body)
        try:
            payload = json.loads(body or b"{}")
            ok = isinstance(payload, dict) and {"email", "amount"} <= set(payload)
        except json.JSONDecodeError:
            ok = False
        status = 200 if ok else 422
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"{}"})

    return app


def test_test_client_tier_reports_the_status_the_app_actually_returned(tmp_path):
    result = prove.prove_test_client(tmp_path, asgi_app(), producer(), consumer())
    assert result.tier == prove.TIER_TEST_CLIENT
    assert result.status == 422
    assert result.passed is False


def test_test_client_tier_passes_when_the_app_accepts_the_request(tmp_path):
    good = consumer(encoding=JSON_ENC, fields=(Field("email", "str"), Field("amount", "int")))
    result = prove.prove_test_client(tmp_path, asgi_app(), producer(), good)
    assert result.status == 200 and result.passed is True


def test_test_client_tier_aborts_loudly_if_the_store_changed(tmp_path):
    """B-R11: a write during proof means proof is unsafe here, not that it passed."""
    db = tmp_path / "app.db"
    conn = sqlite3.connect(db)
    conn.execute("create table t (v text)")
    conn.commit()
    conn.close()

    def writes(_body):
        c = sqlite3.connect(db)
        c.execute("insert into t values ('side effect')")
        c.commit()
        c.close()

    good = consumer(encoding=JSON_ENC, fields=(Field("email", "str"), Field("amount", "int")))
    result = prove.prove_test_client(tmp_path, asgi_app(writes), producer(), good)
    assert result.passed is False
    assert "ABORTED" in result.detail


def test_store_fingerprint_changes_only_when_the_store_changes(tmp_path):
    db = tmp_path / "app.db"
    db.write_bytes(b"one")
    first = prove._store_fingerprint(tmp_path)
    assert prove._store_fingerprint(tmp_path) == first
    db.write_bytes(b"two")
    assert prove._store_fingerprint(tmp_path) != first


# ----------------------------------------------- A-R12 execution is opt-in
def test_execution_never_runs_without_the_flag(tmp_path, monkeypatch):
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("execution must not run without --prove")

    monkeypatch.setattr(prove, "prove_test_client", boom)
    monkeypatch.setattr(prove, "prove_schema", boom)
    from irus.cli import main

    main(["check", str(tmp_path)])
    assert called["n"] == 0


def test_prove_all_only_touches_seams_stage_one_flagged(tmp_path):
    p, c = producer(), consumer()
    other = producer(path="/api/untouched")
    findings = [Finding("encoding_mismatch", p.seam, "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))]
    proofs = prove.prove_all(tmp_path, [p, other], [c], findings)
    assert {pr.seam for pr in proofs} == {"POST /api/checkout"}


def test_prove_all_ignores_medium_confidence_findings(tmp_path):
    p, c = producer(), consumer()
    findings = [Finding("unexpected_field", p.seam, "client sends multipart, server expects json", confidence=MEDIUM, producer_loc=Loc("api.py", 1))]
    assert prove.prove_all(tmp_path, [p], [c], findings) == []


# --------------------------------- A-R23, A-R24 authority and assignment
def test_producer_is_authoritative_by_default():
    f = Finding("encoding_mismatch", "POST /api/x", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))
    assert coordinate.authority_for(f) == coordinate.PRODUCER_AUTHORITATIVE
    assert coordinate.owner_of(f) == CONSUMER


def test_authority_is_overridable_per_seam():
    f = Finding("encoding_mismatch", "POST /api/x", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))
    overrides = {"POST /api/x": coordinate.CONSUMER_AUTHORITATIVE}
    assert coordinate.owner_of(f, overrides) == PRODUCER


def test_exactly_one_owner_per_seam_per_round():
    """A-R24: two findings on one seam must not be handed to two owners."""
    findings = [
        Finding("encoding_mismatch", "POST /api/x", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1)),
        Finding("missing_required_field", "POST /api/x", "client sends multipart, server expects json", subject="email", confidence=HIGH, producer_loc=Loc("api.py", 1)),
        Finding("missing_required_field", "POST /api/y", "client sends multipart, server expects json", subject="id", confidence=HIGH, producer_loc=Loc("api.py", 1)),
    ]
    assignments = coordinate.assign(findings)
    assert len(assignments) == 2
    assert [a.seam for a in assignments] == ["POST /api/x", "POST /api/y"]
    assert len(assignments[0].findings) == 2
    assert len({a.owner for a in assignments}) == 1


def test_medium_findings_are_never_assigned():
    findings = [Finding("unexpected_field", "POST /api/x", "client sends multipart, server expects json", confidence=MEDIUM, producer_loc=Loc("api.py", 1))]
    assert coordinate.assign(findings) == []


# ------------------------------------------------------------ A-R25 ratchet
def make_finding(n: int) -> Finding:
    return Finding("encoding_mismatch", f"POST /api/{n}", "client sends multipart, server expects json", confidence=HIGH, producer_loc=Loc("api.py", 1))


def test_ratchet_refuses_a_round_that_does_not_strictly_reduce_failures():
    """The oscillation case: both sides 'fix' toward each other forever."""
    state = {"findings": [make_finding(1)], "flips": 0}

    def check():
        return list(state["findings"])

    def fix(_assignments):
        state["flips"] += 1
        state["findings"] = [make_finding(2 if state["flips"] % 2 else 1)]

    result = coordinate.run_loop(check, fix, max_rounds=10)
    assert len(result.rounds) == 1
    assert result.rounds[0].accepted is False
    assert "not a strict decrease" in result.rounds[0].reason
    assert state["flips"] == 1, "the loop must stop, not keep flipping"


def test_ratchet_refuses_a_round_that_makes_things_worse():
    state = {"findings": [make_finding(1)]}

    def check():
        return list(state["findings"])

    def fix(_a):
        state["findings"] = [make_finding(1), make_finding(2), make_finding(3)]

    result = coordinate.run_loop(check, fix, max_rounds=5)
    assert result.rounds[0].accepted is False
    assert result.rounds[0].before == 1 and result.rounds[0].after == 3


def test_ratchet_accepts_progress_and_converges():
    state = {"findings": [make_finding(i) for i in range(3)]}

    def check():
        return list(state["findings"])

    def fix(_a):
        state["findings"] = state["findings"][:-1]

    result = coordinate.run_loop(check, fix, max_rounds=10)
    assert result.converged is True
    assert result.final == 0
    assert all(r.accepted for r in result.rounds)
    assert [r.before for r in result.rounds] == [3, 2, 1]


def test_ratchet_reverts_a_rejected_round_when_it_can():
    state = {"findings": [make_finding(1)], "reverted": False}

    def check():
        return list(state["findings"])

    def fix(_a):
        state["findings"] = [make_finding(1), make_finding(2)]

    def revert():
        state["reverted"] = True
        state["findings"] = [make_finding(1)]

    result = coordinate.run_loop(check, fix, revert=revert, max_rounds=5)
    assert state["reverted"] is True
    assert result.final == 1


def test_loop_stops_at_max_rounds_even_if_progress_continues():
    state = {"n": 100}

    def check():
        return [make_finding(i) for i in range(state["n"])]

    def fix(_a):
        state["n"] -= 1

    result = coordinate.run_loop(check, fix, max_rounds=3)
    assert len(result.rounds) == 3


# ------------------------------------------------------------- A-R22 MCP
@pytest.fixture
def mcp(tmp_path):
    (tmp_path / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "from pydantic import BaseModel\n"
        "app = FastAPI()\n"
        "class B(BaseModel):\n"
        "    email: str\n"
        "@app.post('/api/thing')\n"
        "async def thing(payload: B):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    (tmp_path / "client.ts").write_text(
        'export async function s() {\n'
        '  const f = new FormData();\n'
        '  f.append("mail", "x");\n'
        '  await fetch("/api/thing", { method: "POST", body: f });\n'
        "}\n",
        encoding="utf-8",
    )
    return Server(tmp_path)


def test_mcp_initialize_reports_tool_capability(mcp):
    reply = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert reply["result"]["serverInfo"]["name"] == "irus"
    assert "tools" in reply["result"]["capabilities"]


def test_mcp_lists_the_four_tools(mcp):
    reply = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in reply["result"]["tools"]}
    assert names == {"status", "next", "claim", "release"}


def test_mcp_status_returns_text_not_a_picture(mcp):
    reply = mcp.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "status", "arguments": {}},
    })
    content = reply["result"]["content"][0]
    assert content["type"] == "text"
    assert "POST /api/thing" in content["text"]


def test_mcp_next_claims_work_and_does_not_hand_it_out_twice(mcp):
    first = mcp.call("next", {"agent": "codex"})
    assert "claimed" in first
    second = mcp.call("next", {"agent": "claude"})
    assert second == "nothing unclaimed"


def test_mcp_claim_is_refused_when_another_agent_holds_it(mcp):
    mcp.call("claim", {"agent": "a", "target": "POST /api/thing"})
    assert "already claimed by a" in mcp.call("claim", {"agent": "b", "target": "POST /api/thing"})


def test_mcp_release_frees_the_claim(mcp):
    mcp.call("claim", {"agent": "a", "target": "POST /api/thing"})
    mcp.call("release", {"agent": "a", "target": "POST /api/thing"})
    assert "claimed" in mcp.call("claim", {"agent": "b", "target": "POST /api/thing"})


def test_mcp_unknown_method_is_an_error_not_a_crash(mcp):
    reply = mcp.handle({"jsonrpc": "2.0", "id": 9, "method": "nope"})
    assert reply["error"]["code"] == -32601


def test_mcp_notification_gets_no_reply(mcp):
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


# --------------------------------------------------- A-R19, A-R20 the page
PAGE = Path(__file__).resolve().parents[1] / "irus" / "page.html"


def test_page_exists_and_is_self_contained():
    """B-R5, B-R6: no CDN, no build step, works with the network off."""
    html = PAGE.read_text(encoding="utf-8")
    external = re.findall(r'(?:src|href)\s*=\s*["\'](https?:)?//', html)
    assert external == [], f"page reaches outside the machine: {external}"
    assert "<script" in html and "</script>" in html


def test_page_declares_the_validated_palette():
    html = PAGE.read_text(encoding="utf-8")
    for colour in ("#d03b3b", "#c98500", "#eda100", "#3987e5", "#2a78d6", "#898781"):
        assert colour in html, f"missing validated colour {colour}"


def test_page_defines_light_before_dark_so_neither_theme_is_unpainted():
    html = PAGE.read_text(encoding="utf-8")
    assert html.index(":root {") < html.index("prefers-color-scheme: dark")
    assert "--surface: #fcfcfb" in html and "--surface: #1a1a19" in html


def test_page_draws_absence_explicitly():
    """The dashed gap is the product; without it a missing edge is invisible."""
    html = PAGE.read_text(encoding="utf-8")
    assert "stroke-dasharray" in html
    assert "var(--broken)" in html


def test_server_serves_health_state_and_the_page(tmp_path, monkeypatch):
    import threading
    import urllib.request

    from irus import web

    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "rooms")
    monkeypatch.setattr(web, "_rooms", {})
    httpd = web.serve(port=0, host="127.0.0.1")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        health = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health").read())
        assert health["ok"] is True

        payload = json.dumps({"kind": "finding", "id": "f-1", "seam": "POST /x"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/ingest",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        assert json.loads(urllib.request.urlopen(request).read())["accepted"] == 1

        state = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/state").read())
        assert [e["kind"] for e in state["events"]] == ["finding"]

        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "<title>irus</title>" in page
    finally:
        httpd.shutdown()
