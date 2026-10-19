import builtins
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from irus import cli, prove
from irus.compare import compare
from irus.model import CONSUMER, PRODUCER, Field, Loc, Surface


def test_failed_schema_proof_preserves_locations():
    server = Surface(PRODUCER, "POST", "/pay", Loc("api.py", 4), encoding="json", fields=(Field("email", "str"),))
    client = Surface(CONSUMER, "POST", "/pay", Loc("client.ts", 8), encoding="json", fields=(Field("mail", "str"),))
    finding = prove.prove_schema(server, client).to_finding()
    assert finding.kind == "schema_proof"
    assert finding.producer_loc == server.loc
    assert finding.consumer_loc == client.loc


def test_missing_test_client_is_unavailable(tmp_path, monkeypatch):
    original = builtins.__import__

    def without_client(name, *args, **kwargs):
        if name in {"starlette.testclient", "fastapi.testclient"}:
            raise ImportError("dependency absent")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_client)
    server = Surface(PRODUCER, "GET", "/test", Loc("api.py", 1))
    client = Surface(CONSUMER, "GET", "/test", Loc("client.ts", 1))
    assert prove.prove_test_client(tmp_path, object(), server, client).passed is None


def test_http_redirect_is_not_followed():
    visited = []

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            visited.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://external.invalid/private")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        surface = Surface(PRODUCER, "GET", "/test", Loc("api.py", 1))
        checked = prove.prove_http(f"http://127.0.0.1:{server.server_port}", surface)
        assert checked.passed is None
        assert "redirect" in checked.detail.lower()
        assert visited == ["/test"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_cli_json_scan_repair_and_unavailable_execution(tmp_path, capsys):
    (tmp_path / "api.py").write_text('''from fastapi import FastAPI
from pydantic import BaseModel
app = FastAPI()
class Body(BaseModel):
    email: str
@app.post("/pay")
def pay(payload: Body):
    return {}
''', encoding="utf-8")
    client = tmp_path / "client.ts"
    client.write_text('fetch("/pay", {method: "POST", body: JSON.stringify({mail: "a"})});', encoding="utf-8")
    args = ["check", str(tmp_path), "--no-baseline", "--json", "--prove", "--yes"]
    assert cli.main(args) == 1
    broken = json.loads(capsys.readouterr().out)
    assert any(p["result"] == "fail" for p in broken["proofs"])
    assert any(f["producer_loc"] and f["consumer_loc"] for f in broken["findings"])
    assert cli.main(args + ["--app", "no_such_audit_module:app"]) == 2
    unavailable = json.loads(capsys.readouterr().out)
    assert any(p["result"] == "unavailable" for p in unavailable["proofs"])
    client.write_text('fetch("/pay", {method: "POST", body: JSON.stringify({email: "a"})});', encoding="utf-8")
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["findings"] == []


def test_test_client_redirect_does_not_prove_original_handler(tmp_path):
    visited = []

    async def app(scope, receive, send):
        visited.append(scope["path"])
        redirect = scope["path"] == "/test"
        await send({"type": "http.response.start", "status": 307 if redirect else 200,
                    "headers": [(b"location", b"/other")] if redirect else []})
        await send({"type": "http.response.body", "body": b""})

    server = Surface(PRODUCER, "GET", "/test", Loc("api.py", 1))
    client = Surface(CONSUMER, "GET", "/test", Loc("client.ts", 1))
    checked = prove.prove_test_client(tmp_path, app, server, client)
    assert checked.passed is None
    assert checked.status == 307
    assert visited == ["/test"]


def test_store_change_is_reported_even_if_test_client_raises(tmp_path, monkeypatch):
    import starlette.testclient

    class BrokenClient:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            (tmp_path / "app.db").write_bytes(b"changed")
            raise RuntimeError("request interrupted")

        def close(self):
            pass

    monkeypatch.setattr(starlette.testclient, "TestClient", BrokenClient)
    server = Surface(PRODUCER, "GET", "/test", Loc("api.py", 1))
    client = Surface(CONSUMER, "GET", "/test", Loc("client.ts", 1))
    checked = prove.prove_test_client(tmp_path, object(), server, client)
    assert checked.passed is False
    assert "ABORTED" in checked.detail


def test_proof_checks_the_flagged_caller_instead_of_the_last_caller(tmp_path):
    server = Surface(PRODUCER, "POST", "/pay", Loc("api.py", 4), encoding="json", fields=(Field("email", "str"),))
    bad = Surface(CONSUMER, "POST", "/pay", Loc("bad.ts", 1), encoding="json", fields=(Field("mail", "str"),))
    good = Surface(CONSUMER, "POST", "/pay", Loc("good.ts", 1), encoding="json", fields=(Field("email", "str"),))
    proofs = prove.prove_all(tmp_path, [server], [bad, good], compare([server], [bad, good]))
    assert proofs
    assert all(p.consumer_loc == bad.loc and p.passed is False for p in proofs)


def test_method_disagreement_is_not_silently_skipped(tmp_path):
    server = Surface(PRODUCER, "GET", "/pay", Loc("api.py", 4))
    client = Surface(CONSUMER, "POST", "/pay", Loc("client.ts", 1))
    proofs = prove.prove_all(tmp_path, [server], [client], compare([server], [client]))
    assert proofs
    assert proofs[0].seam == client.seam
    assert proofs[0].passed is False
    assert "method" in proofs[0].detail
