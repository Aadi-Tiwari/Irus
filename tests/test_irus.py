"""Regression suite for the Part A requirements.

Rule for this file, taken from PRD-B B-R27: never weaken an assertion to make a
test pass. If a check is wrong, fix the check and say so.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import socket

import pytest

from irus import join, party

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irus import baseline as baseline_mod  # noqa: E402
from irus import receipts as receipts_mod  # noqa: E402
from irus.eventlog import EventLog  # noqa: E402
from irus.extract import ts_express, ts_fetch  # noqa: E402
from irus.model import HIGH, Finding, normalise_path, Loc  # noqa: E402
from irus.scan import scan  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "shop"


def write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


# --------------------------------------------------------------- extraction
def test_fixture_finding_set_is_exactly_as_labelled():
    """A-R1..A-R6 together. Hand-labelled: any change here is a real change."""
    result = scan(FIXTURE)
    got = sorted((f.confidence, f.kind, f.seam, f.subject) for f in result.findings)
    expected = sorted(
        [
            ("high", "encoding_mismatch", "POST /api/checkout", ""),
            ("high", "env_unset", "env DATABASE_URL", "DATABASE_URL"),
            ("high", "missing_required_field", "POST /api/checkout", "amount"),
            ("high", "missing_required_field", "POST /api/checkout", "email"),
            ("medium", "orphan_component", "component Legacy", "Legacy"),
            ("low", "orphan_endpoint", "POST /api/admin/purge", ""),
            ("medium", "response_shape_mismatch", "POST /api/checkout", "orderId"),
            ("medium", "unexpected_field", "POST /api/checkout", "total"),
            ("medium", "unexpected_field", "POST /api/checkout", "user_email"),
        ]
    )
    assert got == expected


def test_optional_field_is_not_required(tmp_path):
    """`str | None = None` must not become a missing_required_field."""
    result = scan(FIXTURE)
    subjects = {f.subject for f in result.findings if f.kind == "missing_required_field"}
    assert "note" not in subjects


def test_health_route_is_not_an_orphan():
    """External callers live outside the repo; /api/health must stay quiet."""
    result = scan(FIXTURE)
    orphans = {f.seam for f in result.findings if f.kind == "orphan_endpoint"}
    assert "GET /api/health" not in orphans


def test_default_export_is_never_an_orphan_component():
    """An importer renames a default export, so name matching cannot prove disuse."""
    result = scan(FIXTURE)
    names = {f.subject for f in result.findings if f.kind == "orphan_component"}
    assert "App" not in names


def test_clean_tree_produces_no_findings(tmp_path):
    """B-R20: a repo whose two sides agree is silent."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        from pydantic import BaseModel

        app = FastAPI()

        class Body(BaseModel):
            email: str

        @app.post("/api/thing")
        async def thing(payload: Body):
            return {"ok": True}
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
    assert scan(tmp_path).findings == []


# ------------------------------------------------------- false-positive rules
def test_unknown_body_never_yields_a_high_finding(tmp_path):
    """Rule 1: an unreadable body is our limitation, not the code's defect."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        from pydantic import BaseModel

        app = FastAPI()

        class Body(BaseModel):
            email: str
            amount: int

        @app.post("/api/thing")
        async def thing(payload: Body):
            return {}
    """)
    write(tmp_path, "client.ts", """
        export async function send(payload: unknown) {
          await fetch("/api/thing", { method: "POST", body: buildIt(payload) });
        }
    """)
    assert [f for f in scan(tmp_path).findings if f.confidence == HIGH] == []


def test_spread_suppresses_missing_field_checks(tmp_path):
    """Rule 2: `...rest` makes the field set unknowable, so do not guess."""
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        from pydantic import BaseModel

        app = FastAPI()

        class Body(BaseModel):
            email: str
            amount: int

        @app.post("/api/thing")
        async def thing(payload: Body):
            return {}
    """)
    write(tmp_path, "client.ts", """
        export async function send(rest: object) {
          await fetch("/api/thing", {
            method: "POST",
            body: JSON.stringify({ email: "a@b.c", ...rest }),
          });
        }
    """)
    kinds = {f.kind for f in scan(tmp_path).findings}
    assert "missing_required_field" not in kinds


def test_env_read_with_default_is_not_a_finding(tmp_path):
    write(tmp_path, "conf.py", """
        import os
        A = os.getenv("HAS_DEFAULT", "x")
        B = os.environ["NO_DEFAULT"]
    """)
    names = {f.subject for f in scan(tmp_path).findings if f.kind == "env_unset"}
    assert names == {"NO_DEFAULT"}


def test_env_declared_in_dotenv_is_not_a_finding(tmp_path):
    write(tmp_path, "conf.py", 'import os\nX = os.environ["DECLARED"]\n')
    (tmp_path / ".env").write_text("DECLARED=1\n", encoding="utf-8")
    assert [f for f in scan(tmp_path).findings if f.kind == "env_unset"] == []


def test_env_declared_in_github_workflow_is_not_a_finding(tmp_path):
    write(tmp_path, "conf.py", 'import os\nX = os.environ["CI_ONLY"]\n')
    write(tmp_path, ".github/workflows/ci.yml", """
        name: ci
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            env:
              CI_ONLY: hello
            steps:
              - run: echo hi
    """)
    assert [f for f in scan(tmp_path).findings if f.kind == "env_unset"] == []


# --------------------------------------------------------------- scanner core
def test_mask_is_not_fooled_by_braces_inside_strings():
    src = 'const a = "}{"; fetch("/x", { method: "POST" });'
    masked = ts_fetch.mask(src)
    assert masked.count("{") == 1 and masked.count("}") == 1
    assert len(masked) == len(src)


def test_path_parameter_spellings_all_normalise_together():
    assert (
        normalise_path("/users/{id}")
        == normalise_path("/users/:id")
        == normalise_path("/users/${id}")
        == "/users/{}"
    )


def test_template_literal_url_matches_a_declared_route(tmp_path):
    write(tmp_path, "api.py", """
        from fastapi import FastAPI
        app = FastAPI()

        @app.get("/api/orders/{order_id}")
        async def get_order(order_id: str):
            return {}
    """)
    write(tmp_path, "client.ts", """
        export async function load(id: string) {
          return fetch(`/api/orders/${id}`);
        }
    """)
    assert [f for f in scan(tmp_path).findings if f.kind == "endpoint_not_found"] == []


def test_router_prefix_and_mount_prefix_compose_in_order(tmp_path):
    write(tmp_path, "api.py", """
        from fastapi import APIRouter, FastAPI

        app = FastAPI()
        router = APIRouter(prefix="/users")

        @router.get("/{uid}")
        async def get_user(uid: str):
            return {}

        app.include_router(router, prefix="/api")
    """)
    seams = {p.seam for p in scan(tmp_path).producers}
    assert seams == {"GET /api/users/{}"}


def test_unmounted_router_is_high_confidence(tmp_path):
    write(tmp_path, "api.py", """
        from fastapi import APIRouter, FastAPI

        app = FastAPI()
        orphan = APIRouter()

        @orphan.get("/api/never")
        async def never():
            return {}
    """)
    findings = [f for f in scan(tmp_path).findings if f.kind == "unmounted_route"]
    assert len(findings) == 1 and findings[0].confidence == HIGH


def test_express_producer_is_extracted(tmp_path):
    """A-R7: the comparer needs no knowledge of which stack produced a side."""
    write(tmp_path, "server.js", """
        const express = require("express");
        const app = express();
        const router = express.Router();

        router.post("/checkout", (req, res) => {
          const { email, amount } = req.body;
          res.json({ ok: true });
        });

        app.use("/api", router);
    """)
    surfaces = ts_express.extract_file(tmp_path / "server.js", tmp_path)
    assert len(surfaces) == 1
    s = surfaces[0]
    assert s.seam == "POST /api/checkout"
    assert {f.name for f in s.fields} == {"email", "amount"}
    assert s.mounted is True


def test_express_and_fetch_mismatch_is_detected(tmp_path):
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
          await fetch("/api/pay", {
            method: "POST",
            body: JSON.stringify({ mail: "a@b.c" }),
          });
        }
    """)
    kinds = {f.kind for f in scan(tmp_path).findings}
    assert "missing_required_field" in kinds


# ------------------------------------------------------------ finding identity
def test_finding_key_survives_line_movement():
    """A key that changes on every edit can never be suppressed by a baseline."""
    from irus.model import Loc

    a = Finding("encoding_mismatch", "POST /x", "client sends multipart, server expects json", producer_loc=Loc("a.py", 10))
    b = Finding("encoding_mismatch", "POST /x", "a different rendering of the same disagreement", producer_loc=Loc("a.py", 900))
    assert a.key == b.key


def test_findings_of_same_kind_on_same_seam_stay_distinct():
    a = Finding("missing_required_field", "POST /x", "client sends multipart, server expects json", subject="email", producer_loc=Loc("api.py", 1))
    b = Finding("missing_required_field", "POST /x", "client sends multipart, server expects json", subject="amount", producer_loc=Loc("api.py", 1))
    assert a.key != b.key


# ------------------------------------------------------------------ event log
def test_event_log_replay_is_idempotent(tmp_path):
    """B-R4: a browser refresh must rebuild identical state."""
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append("finding", id="f-1")
    log.append("proof", id="f-1", result="fail")
    first = log.replay()
    assert [e["seq"] for e in first] == [1, 2]
    assert EventLog(path).replay() == first


def test_event_log_tolerates_a_torn_line_and_unknown_kinds(tmp_path):
    """B-R22: an older reader must not crash on a newer writer."""
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"kind":"finding","id":"a"}\n'
        '{"kind":"from_the_future","weird":true}\n'
        '{"kind":"trunc',
        encoding="utf-8",
    )
    events = EventLog(path).replay()
    assert [e["kind"] for e in events] == ["finding", "from_the_future"]


# ----------------------------------------------------------------- receipts
def test_receipt_renders_pass_and_fail_lines():
    result = scan(FIXTURE)
    text = receipts_mod.render(receipts_mod.build(result), only_failing=True)
    assert "POST /api/checkout" in text
    assert "encoding matches" in text and "FAIL" in text
    assert "endpoint exists" in text and "PASS" in text


# ------------------------------------------------------------------ baseline
def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@e.st")
    _git(tmp_path, "config", "user.name", "Test")
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
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "clean")
    return tmp_path


def test_baseline_anchors_to_a_commit_not_the_clock(repo):
    base = baseline_mod.compute(repo)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert base.sha == head


def test_baseline_hides_pre_existing_and_shows_only_new(repo):
    """A-R14: the whole false-positive defence in one assertion."""
    before = baseline_mod.compute(repo)
    assert before.suppress(scan(repo).findings) == []

    write(repo, "client.ts", """
        export async function send() {
          const form = new FormData();
          form.append("user_email", "a@b.c");
          await fetch("/api/thing", { method: "POST", body: form });
        }
    """)
    after = baseline_mod.compute(repo)
    new = after.suppress(scan(repo).findings)
    kinds = {f.kind for f in new}
    assert "encoding_mismatch" in kinds
    assert "missing_required_field" in kinds
    assert after.sha == before.sha


def test_baseline_is_cached_by_sha(repo):
    baseline_mod.compute(repo, refresh=True)
    again = baseline_mod.compute(repo)
    assert again.cached is True
    assert (repo / ".irus").exists()


# ---------------------------------------------------------------------- cli
def test_cli_exit_code_is_a_merge_gate(repo):
    """A-R17: 0 when clean, 1 when a high-confidence finding is introduced."""
    from irus.cli import main

    assert main(["check", str(repo)]) == 0
    write(repo, "client.ts", """
        export async function send() {
          const form = new FormData();
          form.append("user_email", "a@b.c");
          await fetch("/api/thing", { method: "POST", body: form });
        }
    """)
    assert main(["check", str(repo)]) == 1


def test_cli_json_output_is_machine_readable(repo, capsys):
    from irus.cli import main

    main(["check", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert "findings" in payload and "baseline" in payload


# --- port selection ---------------------------------------------------------
# A room on an OS-chosen high port was unreachable twice in a row: Windows
# reserves blocks up there for Hyper-V and WSL and refuses the socket with a
# bare WinError 10013.

def test_pick_port_prefers_a_stable_low_port():
    assert party.pick_port(0) in party.PREFERRED_PORTS


def test_pick_port_honours_an_explicit_request():
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    wanted = free.getsockname()[1]
    free.close()
    assert party.pick_port(wanted) == wanted


def test_pick_port_refuses_a_port_windows_reserves(monkeypatch):
    monkeypatch.setattr(party, "excluded_ports", lambda: [(50000, 50999)])
    assert party.pick_port(50637) != 50637


def test_pick_port_skips_a_port_already_in_use():
    taken = party.PREFERRED_PORTS[0]
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        held.bind(("0.0.0.0", taken))
    except OSError:
        pass  # something else already holds it, which is the same condition
    held.listen(1)
    try:
        chosen = party.pick_port(0)
        assert chosen != taken
        assert chosen in party.PREFERRED_PORTS
    finally:
        held.close()


def test_excluded_ports_returns_pairs_or_nothing():
    for low, high in party.excluded_ports():
        assert isinstance(low, int) and low <= high


# --- unreachable rooms explain themselves -----------------------------------

def test_winsock_errors_name_their_own_fix():
    room = join.Room("http://10.0.0.9:50637", "t")
    assert "reserved by Hyper-V" in room._explain(OSError("[WinError 10013] forbidden"))
    assert "Tailscale" in room._explain(OSError("timed out"))
    assert "no room is running" in room._explain(OSError("[WinError 10061] refused"))
    assert "http://10.0.0.9:50637" in room._explain(OSError("something else"))


def test_a_prompt_never_exits_silently(monkeypatch, capsys):
    """Exiting mutely on end-of-input was indistinguishable from a paste that
    worked and a program that then did nothing."""
    def no_input(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    with pytest.raises(SystemExit):
        party.ask("paste the join code")
    assert "nothing was pasted" in capsys.readouterr().out


def test_ctrl_c_says_cancelled(monkeypatch, capsys):
    def interrupted(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted)
    with pytest.raises(SystemExit):
        party.ask("choose", "1")
    assert "cancelled" in capsys.readouterr().out
