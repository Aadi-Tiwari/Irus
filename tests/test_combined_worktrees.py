import json
from pathlib import Path
import subprocess

import pytest

from irus import cli
from irus.report import check
from irus.workspace import CompositionError, compose
from irus.intent import load as load_brief
from irus.mcp_server import Server


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.STDOUT)


@pytest.fixture
def worktrees(tmp_path):
    root = tmp_path / "backend"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text(".irus/\n", encoding="utf-8")
    (root / "obsolete.py").write_text("value = 1\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "-c", "user.name=Irus test", "-c", "user.email=irus@example.invalid", "commit", "-qm", "fixture base")
    client = tmp_path / "frontend"
    git(root, "worktree", "add", "-qb", "client", str(client))
    (root / "api.py").write_text('''from fastapi import FastAPI
from pydantic import BaseModel
app = FastAPI()
class Checkout(BaseModel):
    email: str
    amount: int
@app.post("/api/checkout")
def checkout(payload: Checkout): return {}
''', encoding="utf-8")
    (client / "client.ts").write_text('''const body = new FormData();
body.append("user_email", "a@example.invalid");
body.append("total", "10");
fetch("/api/checkout", {method: "POST", body});
''', encoding="utf-8")
    return root, client


def contents(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_combined_mismatch_repair_and_source_provenance(worktrees, capsys):
    backend, frontend = worktrees
    before = [contents(tree) for tree in worktrees]
    args = ["check", str(backend), "--with", str(frontend), "--json"]
    assert cli.main(args) == 1
    report = json.loads(capsys.readouterr().out)
    mismatch = next(f for f in report["findings"] if f["kind"] == "encoding_mismatch")
    assert mismatch["producer_sources"] == [str(backend / "api.py") + ":8"]
    assert mismatch["consumer_sources"][0].startswith(str(frontend / "client.ts") + ":")
    assert [contents(tree) for tree in worktrees] == before
    (frontend / "client.ts").write_text('fetch("/api/checkout", {method: "POST", body: JSON.stringify({email: "a@example.invalid", amount: 10})});', encoding="utf-8")
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []


def test_conflicting_edits_fail_without_touching_worktrees(worktrees, capsys):
    backend, frontend = worktrees
    for tree, value in [(backend, "2"), (frontend, "3")]:
        (tree / "obsolete.py").write_text("value = " + value, encoding="utf-8")
    before = [contents(tree) for tree in worktrees]
    assert cli.main(["check", str(backend), "--with", str(frontend), "--json"]) == 2
    assert "Conflicting versions of obsolete.py" in json.loads(capsys.readouterr().out)["error"]
    assert [contents(tree) for tree in worktrees] == before


def test_deletions_and_identical_edits_are_composed(worktrees):
    backend, frontend = worktrees
    (backend / "obsolete.py").unlink()
    for tree in worktrees:
        (tree / "shared.ts").write_text("export const value = 1;", encoding="utf-8")
    report = check(backend, worktrees=[frontend])
    assert report.sources["obsolete.py"] == [str(backend / "obsolete.py")]
    assert report.sources["shared.ts"] == [str(backend / "shared.ts"), str(frontend / "shared.ts")]


def test_unrelated_repositories_cannot_be_composed(worktrees, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    with pytest.raises(CompositionError, match="same Git repository"):
        check(worktrees[0], worktrees=[other])


def test_brief_acknowledgement_and_combined_repair(worktrees):
    backend, frontend = worktrees
    brief = backend / "IRUS.md"
    brief.write_text("Build checkout. Accept JSON email and amount. Keep payments out of scope.", encoding="utf-8")
    server = Server(backend)
    revision = load_brief(backend).revision
    assert revision in server.call("brief", {})
    with pytest.raises(ValueError, match="brief_revision"):
        server.call("next", {"agent": "frontend", "worktrees": [str(frontend)]})
    claimed = server.call("next", {"agent": "frontend", "worktrees": [str(frontend)], "brief_revision": revision})
    assert "claimed POST /api/checkout" in claimed
    args = {"agent": "frontend", "target": "POST /api/checkout", "brief_revision": revision}
    assert "still failing" in server.call("complete", args)
    assert "POST /api/checkout" in server.claims()
    with pytest.raises(ValueError, match="owner"):
        server.call("release", {"agent": "backend", "target": "POST /api/checkout"})
    (frontend / "client.ts").write_text('fetch("/api/checkout", {method: "POST", body: JSON.stringify({email: "a@example.invalid", amount: 10})});', encoding="utf-8")
    brief.write_text(brief.read_text(encoding="utf-8") + "\nShow an order receipt.", encoding="utf-8")
    with pytest.raises(ValueError, match="brief_revision"):
        server.call("complete", args)
    args["brief_revision"] = load_brief(backend).revision
    assert "static contract rechecked" in server.call("complete", args)
    assert server.claims() == {}


def test_completion_does_not_accept_a_deleted_caller(worktrees):
    backend, frontend = worktrees
    server = Server(backend)
    server.call("next", {"agent": "frontend", "worktrees": [str(frontend)]})
    (frontend / "client.ts").unlink()
    text = server.call("complete", {"agent": "frontend", "target": "POST /api/checkout"})
    assert "completed" not in text
    assert "POST /api/checkout" in server.claims()


def test_mcp_status_matches_cli_filtering(worktrees, capsys):
    backend, frontend = worktrees
    args = ["check", str(backend), "--with", str(frontend), "--json"]
    assert cli.main(args) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    text = Server(backend).call("status", {"worktrees": [str(frontend)]})
    assert f"{len(findings)} finding(s)" in text
    for finding in findings:
        assert finding["detail"] in text
        for source in finding["consumer_sources"] + finding["producer_sources"]:
            assert source in text


def test_empty_brief_is_an_error_and_stdio_can_read_it(tmp_path):
    (tmp_path / "IRUS.md").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        check(tmp_path)
    (tmp_path / "IRUS.md").write_text("Integration checking is the core.", encoding="utf-8")
    import sys
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "brief", "arguments": {}}}
    process = subprocess.run([sys.executable, "-m", "irus.mcp_server", str(tmp_path)], input=json.dumps(request) + "\n", text=True, capture_output=True)
    assert process.returncode == 0
    assert load_brief(tmp_path).revision in json.loads(process.stdout)["result"]["content"][0]["text"]


def test_renamed_file_is_removed_from_combined_snapshot(worktrees):
    backend, frontend = worktrees
    git(backend, "mv", "obsolete.py", "renamed.py")
    with compose([backend, frontend]) as workspace:
        workspace.apply_changes()
        assert not (workspace.root / "obsolete.py").exists()
        assert (workspace.root / "renamed.py").read_text() == "value = 1\n"


def test_independent_mcp_clients_share_claim_ownership(tmp_path):
    first, second = Server(tmp_path), Server(tmp_path)
    assert first.call("claim", {"agent": "a", "target": "POST /checkout"}) == "claimed POST /checkout"
    assert second.call("claim", {"agent": "b", "target": "POST /checkout"}) == "already claimed by a"
    with pytest.raises(ValueError, match="owner"):
        second.call("release", {"agent": "b", "target": "POST /checkout"})
    first.call("release", {"agent": "a", "target": "POST /checkout"})
    assert second.call("claim", {"agent": "b", "target": "POST /checkout"}) == "claimed POST /checkout"
    assert first.claims() == second.claims() == {"POST /checkout": "b"}


def test_combined_claims_do_not_require_a_gitignore_entry(worktrees):
    backend, frontend = worktrees
    (backend / ".gitignore").unlink()
    server = Server(backend)
    assert "claimed POST /api/checkout" in server.call("next", {"agent": "a", "worktrees": [str(frontend)]})
    assert "still failing" in server.call("complete", {"agent": "a", "target": "POST /api/checkout"})


def test_concurrent_processes_cannot_both_claim(tmp_path):
    import sys
    script = '''from irus.mcp_server import Server
import sys
try:
    print(Server(sys.argv[1]).call("claim", {"agent": sys.argv[2], "target": "POST /checkout"}))
except ValueError as exc:
    print(exc)
'''
    clients = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path), name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for name in ["a", "b"]]
    replies = [client.communicate(timeout=20) for client in clients]
    assert all(client.returncode == 0 for client in clients), replies
    assert sum(out.strip() == "claimed POST /checkout" for out, _ in replies) == 1
    assert len(Server(tmp_path).claims()) == 1
