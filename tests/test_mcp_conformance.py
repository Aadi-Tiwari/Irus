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

from irus.join import JoinError as JoinErrorAlias  # noqa: E402


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


# ============================================ joining someone else's session
def test_join_reads_a_room_without_a_token(tmp_path, monkeypatch):
    """Watching a session needs nothing but the URL; only writes need the token."""
    import threading
    from irus import join as join_mod, web

    # monkeypatch, not assignment: these are module globals and leaking them
    # breaks every later test that serves a room.
    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "rooms")
    monkeypatch.setattr(web, "_rooms", {})
    monkeypatch.setattr(web, "TOKEN", "s3cret")
    room = web.room("default")
    room.append("surface", id="PUT /profile", side="producer")
    room.append("finding", id="f-1", seam="PUT /profile", confidence="high",
                detail="server requires marketing_emails", **{"class": "missing_required_field"})

    httpd = web.serve(port=0, host="127.0.0.1")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        guest = join_mod.Room(url=url)               # no token at all
        assert guest.health()["ok"] is True
        events = guest.state()
        summary = join_mod.summarise(events)
        assert "1 high confidence" in summary
        assert "PUT /profile" in summary

        # A write without the token is refused with a message that says what to do.
        with pytest.raises(join_mod.JoinError) as exc:
            guest.send("claim", agent="codex", target="PUT /profile")
        assert "token" in str(exc.value)

        # With it, the claim lands and the host sees who holds what.
        writer = join_mod.Room(url=url, token="s3cret")
        writer.send("claim", agent="codex", target="PUT /profile")
        assert "PUT /profile by codex" in join_mod.summarise(guest.state())
    finally:
        httpd.shutdown()


def test_join_reports_an_unreachable_host_clearly(tmp_path):
    from irus import join as join_mod

    guest = join_mod.Room(url="http://127.0.0.1:9")
    with pytest.raises(join_mod.JoinError) as exc:
        guest.health()
    assert "cannot reach" in str(exc.value)


def test_join_accepts_a_bare_host_and_port(tmp_path):
    """People paste `10.0.0.5:8902`, not a full URL."""
    from irus import join as join_mod

    guest = join_mod.Room(url="10.0.0.5:8902", room="team")
    assert guest._endpoint("/state") == "http://10.0.0.5:8902/state?room=team"


# ================================ editing the host's files, and its guards
@pytest.fixture
def shared_host(tmp_path, monkeypatch):
    """A host sharing a small repo, plus a guest Room pointed at it."""
    import threading
    from irus import join as join_mod, web

    repo = tmp_path / "host-repo"
    write(repo, "api.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(repo, "client.ts", "export const x = 1;\n")
    write(repo, ".env", "SECRET=hunter2\n")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    write(tmp_path, "outside.txt", "not yours\n")

    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "rooms")
    monkeypatch.setattr(web, "_rooms", {})
    monkeypatch.setattr(web, "TOKEN", "tok")
    monkeypatch.setattr(web, "SHARE_ROOT", repo)

    httpd = web.serve(port=0, host="127.0.0.1")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield repo, join_mod.Room(url=url, token="tok"), join_mod.Room(url=url)
    finally:
        httpd.shutdown()


def test_guest_can_list_read_and_edit_the_hosts_files(shared_host):
    """The whole point: a guest changes the host's file, on the host's disk."""
    repo, guest, _ = shared_host

    names = {f["path"] for f in guest.files()}
    assert "api.py" in names and "client.ts" in names

    assert "FastAPI" in guest.read_file("api.py")

    guest.write_file("api.py", "from fastapi import FastAPI\napp = FastAPI(title='edited')\n")
    assert "edited" in (repo / "api.py").read_text(encoding="utf-8"), "host file unchanged"
    assert "edited" in guest.read_file("api.py")


def test_a_guest_without_the_token_gets_nothing(shared_host):
    """Source is not findings: reads need the token too."""
    _, _, anonymous = shared_host
    for call in (lambda: anonymous.files(),
                 lambda: anonymous.read_file("api.py"),
                 lambda: anonymous.write_file("api.py", "x")):
        with pytest.raises(JoinErrorAlias):
            call()


def test_file_sharing_is_off_unless_the_host_opts_in(tmp_path, monkeypatch):
    """A room must not expose a filesystem just because it was started."""
    import threading
    from irus import join as join_mod, web

    monkeypatch.setattr(web, "DATA_DIR", tmp_path / "rooms")
    monkeypatch.setattr(web, "_rooms", {})
    monkeypatch.setattr(web, "TOKEN", "tok")
    monkeypatch.setattr(web, "SHARE_ROOT", None)      # the default

    httpd = web.serve(port=0, host="127.0.0.1")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        guest = join_mod.Room(url=f"http://127.0.0.1:{httpd.server_address[1]}", token="tok")
        with pytest.raises(join_mod.JoinError) as exc:
            guest.files()
        assert "not sharing files" in str(exc.value)
    finally:
        httpd.shutdown()


@pytest.mark.parametrize("escape", [
    "../outside.txt",
    "../../outside.txt",
    "subdir/../../outside.txt",
    "C:/Windows/System32/drivers/etc/hosts",
    "/etc/passwd",
])
def test_paths_cannot_escape_the_shared_repository(shared_host, escape):
    """Traversal is checked on the resolved path, not the string."""
    _, guest, _ = shared_host
    with pytest.raises(JoinErrorAlias):
        guest.read_file(escape)
    with pytest.raises(JoinErrorAlias):
        guest.write_file(escape, "owned")


def test_secrets_and_dependencies_are_never_shared(shared_host):
    """.env and node_modules are not on the menu even with a valid token."""
    _, guest, _ = shared_host
    names = {f["path"] for f in guest.files()}
    assert ".env" not in names
    assert not any(n.startswith("node_modules") for n in names)
    with pytest.raises(JoinErrorAlias):
        guest.read_file(".env")


def test_the_outside_file_was_never_touched(shared_host):
    """After every traversal attempt above, prove nothing outside changed."""
    repo, guest, _ = shared_host
    outside = repo.parent / "outside.txt"
    try:
        guest.write_file("../outside.txt", "owned")
    except Exception:
        pass
    assert outside.read_text(encoding="utf-8") == "not yours\n"


# ================================================ the join code and the menu
def test_a_join_code_round_trips():
    from irus import party

    code = party.encode("10.10.8.145", 8930, "irus-demo")
    invite = party.decode(code)
    assert invite.url == "http://10.10.8.145:8930"
    assert invite.token == "irus-demo"


def test_a_join_code_survives_being_pasted():
    """No characters a chat client will linkify, wrap or strip."""
    from irus import party

    code = party.encode("100.110.227.38", 8940, party.new_token())
    assert code.isascii() and " " not in code
    assert not any(c in code for c in "/+:@#?&")


def test_a_url_with_the_token_after_a_hash_also_works():
    from irus import party

    invite = party.decode("http://10.0.0.5:8902#tok123")
    assert invite.url == "http://10.0.0.5:8902" and invite.token == "tok123"


@pytest.mark.parametrize("junk", ["not-a-code", "", "http://nohost", "!!!!"])
def test_rubbish_is_refused_rather_than_half_understood(junk):
    from irus import party

    with pytest.raises(party.BadCode):
        party.decode(junk)


def test_a_generated_token_is_not_guessable():
    from irus import party

    tokens = {party.new_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 16 for t in tokens)


def test_host_prefers_an_address_that_crosses_networks(monkeypatch):
    """Venue and campus wifi isolate clients, so a LAN address is the one that
    silently fails on demo day. Tailscale wins when it is present."""
    from irus import party

    monkeypatch.setattr(party, "best_address", party.best_address)
    import socket

    def fake(*_a, **_k):
        return [(None, None, None, None, (ip, 0))
                for ip in ("10.10.8.145", "10.5.0.2", "100.110.227.38")]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    assert party.best_address() == "100.110.227.38"


def test_the_vpn_adapter_is_not_offered_when_nothing_better_exists(monkeypatch):
    from irus import party
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (None, None, None, None, (ip, 0)) for ip in ("10.5.0.2", "10.10.8.145")
    ])
    assert party.best_address() == "10.10.8.145"


def test_pull_then_edit_then_push_is_the_editing_workflow(shared_host, tmp_path):
    """Editing one file at a time through --cat and --put is not how anyone
    works. Pull the project, open it in your own editor or agent, push back."""
    repo, guest, _ = shared_host
    local = tmp_path / "theirs"

    pulled = guest.pull(local)
    assert "api.py" in pulled
    assert (local / "api.py").is_file(), "the host's file is not on my disk"

    (local / "api.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI(title='edited by the guest')\n",
        encoding="utf-8",
    )
    sent = guest.push(local)

    assert sent == ["api.py"], f"only the changed file should go back, got {sent}"
    assert "edited by the guest" in (repo / "api.py").read_text(encoding="utf-8")


def test_push_with_no_edits_sends_nothing(shared_host, tmp_path):
    """A pull-then-push round trip with no changes must be a no-op, or the
    host's log fills with writes that carry no information."""
    _, guest, _ = shared_host
    local = tmp_path / "theirs"
    guest.pull(local)
    assert guest.push(local) == []


def test_pull_never_writes_outside_the_target_directory(shared_host, tmp_path):
    """Every path comes from the host, so a hostile host must not be able to
    scatter files across the guest's disk."""
    repo, guest, _ = shared_host
    local = tmp_path / "theirs"
    guest.pull(local)
    for path in local.rglob("*"):
        assert local.resolve() in path.resolve().parents or path.resolve() == local.resolve()
