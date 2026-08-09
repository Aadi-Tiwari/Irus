"""Does the MCP server actually work as a server, from anywhere?

Not "do the functions return the right thing" (test_prove_coordinate_mcp.py
already covers that) but "would a real client speaking JSON-RPC over stdio be
able to drive it". Those are different questions and the second one is the one
that decides whether it can be registered in someone's config.

Every test here launches the server as a subprocess and speaks the protocol to
it, exactly as a client would.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


@pytest.fixture
def project(tmp_path):
    """A tiny project with a genuine mismatch for the server to report."""
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
            body: JSON.stringify({ mail: "a@b.c" }),
          });
        }
    """)
    return tmp_path


def speak(requests: list[dict], root: Path, cwd: Path | None = None) -> tuple[list[dict], str]:
    """Drive the server over stdio. Returns (responses, raw stdout)."""
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    proc = subprocess.run(
        [sys.executable, "-m", "irus.mcp_server", str(root)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(cwd or REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    out: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out, proc.stdout


# ------------------------------------------------------------- the handshake
def test_initialize_returns_a_valid_result(project):
    replies, _ = speak([{
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "probe", "version": "1"}},
    }], project)
    assert len(replies) == 1
    r = replies[0]
    assert r["jsonrpc"] == "2.0" and r["id"] == 1
    result = r["result"]
    assert "protocolVersion" in result
    assert "capabilities" in result and "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] and result["serverInfo"]["version"]


def test_full_handshake_then_list_then_call(project):
    """The exact sequence a real client performs on startup."""
    replies, _ = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "probe", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "status", "arguments": {}}},
    ], project)

    # The notification must not draw a reply; three requests, three replies.
    assert [r["id"] for r in replies] == [1, 2, 3]
    tools = replies[1]["result"]["tools"]
    assert {t["name"] for t in tools} == {"status", "next", "claim", "release"}
    for t in tools:
        assert t["description"], f"{t['name']} has no description"
        assert t["inputSchema"]["type"] == "object", f"{t['name']} schema is not an object"
    text = replies[2]["result"]["content"][0]["text"]
    assert "POST /api/thing" in text


def test_stdout_carries_nothing_but_json_rpc(project):
    """stdio transport dies if anything else is printed to stdout."""
    _, raw = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "status", "arguments": {}}},
    ], project)
    for line in raw.splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)  # raises if anything non-JSON reached stdout
        assert obj.get("jsonrpc") == "2.0"


# ----------------------------------------------------------- works anywhere
def test_runs_from_an_unrelated_working_directory(project, tmp_path):
    """A client launches the server with its own cwd, not the project's."""
    elsewhere = tmp_path.parent
    replies, _ = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "status", "arguments": {}}},
    ], project, cwd=elsewhere)
    assert "POST /api/thing" in replies[1]["result"]["content"][0]["text"]


def test_path_argument_overrides_the_launch_directory(project, tmp_path):
    """`status` accepts an explicit path, so one server can serve any repo."""
    other = tmp_path.parent / "other-project"
    other.mkdir(exist_ok=True)
    write(other, "api.py", """
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/api/elsewhere")
        async def elsewhere():
            return {}
    """)
    replies, _ = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "status", "arguments": {"path": str(other)}}},
    ], project)
    text = replies[1]["result"]["content"][0]["text"]
    assert "/api/elsewhere" in text
    assert "POST /api/thing" not in text, "the path argument was ignored"


# --------------------------------------------------------------- robustness
def test_unknown_method_is_a_jsonrpc_error_not_a_crash(project):
    replies, _ = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
    ], project)
    assert replies[1]["error"]["code"] == -32601
    assert [r["id"] for r in replies] == [1, 2, 3], "server stopped after an error"


def test_malformed_line_does_not_kill_the_session(project):
    payload = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
        + "this is not json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "irus.mcp_server", str(project)],
        input=payload, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180, cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    ids = [json.loads(l)["id"] for l in proc.stdout.splitlines() if l.strip()]
    assert ids == [1, 2], "a malformed line ended the session"


def test_unknown_tool_is_an_error_response(project):
    replies, _ = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "does_not_exist", "arguments": {}}},
    ], project)
    assert "error" in replies[1] or replies[1]["result"].get("isError")


def test_a_tool_failure_is_reported_not_raised(project, tmp_path):
    """Pointing status at a missing directory must not kill the server."""
    replies, _ = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "status", "arguments": {"path": str(tmp_path / "nope")}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
    ], project)
    assert replies[1]["result"]["isError"] is True
    assert [r["id"] for r in replies] == [1, 2, 3], "server died on a tool failure"


# --------------------------------------------------- negotiation and keepalive
@pytest.mark.parametrize("asked", ["2025-06-18", "2025-03-26", "2024-11-05"])
def test_supported_protocol_version_is_echoed_back(project, asked):
    """A client pinned to an older revision must not be handed a newer one."""
    replies, _ = speak([{
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": asked, "capabilities": {},
                   "clientInfo": {"name": "probe", "version": "1"}},
    }], project)
    assert replies[0]["result"]["protocolVersion"] == asked


def test_unknown_protocol_version_falls_back_to_ours(project):
    replies, _ = speak([{
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"},
    }], project)
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"


def test_ping_is_answered(project):
    """Clients ping for keepalive; answering -32601 makes a live server look dead."""
    replies, _ = speak([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
    ], project)
    assert "error" not in replies[1], "ping was rejected"
    assert replies[1]["result"] == {}
    assert [r["id"] for r in replies] == [1, 2, 3]


def test_capabilities_declare_tools_explicitly(project):
    replies, _ = speak([{"jsonrpc": "2.0", "id": 1, "method": "initialize"}], project)
    caps = replies[0]["result"]["capabilities"]
    assert caps["tools"] == {"listChanged": False}
