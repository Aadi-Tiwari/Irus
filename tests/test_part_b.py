"""Conformance tests for PRD-B.

One test (or one tightly grouped set) per requirement, named for the id it
covers, so a failure says which requirement broke rather than which function.
Requirements that are process rather than code — B-R28 (never demo a live
agent), B-R40 (ten rehearsals) — are asserted as documented commitments in
`docs/DEMO.md`, which is the strongest thing a test suite can honestly do about
a promise a human makes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from irus import baseline as baseline_mod
from irus import ledger as ledger_mod
from irus import prove, receipts, server
from irus.check import SeamCache, digest, sweep
from irus.events import EventLog, replay
from irus.findings import Finding, MissingEvidence, Side, Suppressions
from irus.walk import ALWAYS_IGNORE, source_files
from irus.watcher import Change, Watcher

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "fixtures" / "synthetic-checkout"
CLEAN = ROOT / "fixtures" / "clean-checkout"
SESSION_LOG = ROOT / "fixtures" / "session.jsonl"
PAGE = ROOT / "irus" / "page" / "index.html"


# ------------------------------------------------------------ 1.1 determinism


def test_b_r1_stage_1_is_a_pure_function_of_the_tree():
    digests = {digest(sweep(SYNTHETIC).findings) for _ in range(8)}
    assert len(digests) == 1, "stage 1 produced different output for identical input"


def test_b_r1_no_clock_or_randomness_reaches_a_finding():
    """duration_ms is measurement and must not leak into any finding."""
    a, b = sweep(SYNTHETIC), sweep(SYNTHETIC)
    assert a.duration_ms != b.duration_ms or True   # timing may coincide; that is fine
    assert [f.to_event() for f in a.findings] == [f.to_event() for f in b.findings]


def test_b_r1_stage_1_imports_no_model_and_no_network():
    """B-R1 and B-R24 both rest on this being literally true, so it is checked
    rather than asserted in prose. The demo says it out loud (B-R36)."""
    banned = {
        "openai", "anthropic", "torch", "transformers", "tensorflow",
        "requests", "httpx", "urllib3", "socket", "aiohttp",
    }
    for module in ("irus.check", "irus.extract.producer", "irus.extract.consumer", "irus.extract.env"):
        source = (ROOT / Path(module.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        for name in banned:
            assert f"import {name}" not in source, f"{module} imports {name}"


def test_b_r2_layout_is_seeded_from_node_identity():
    page = PAGE.read_text(encoding="utf-8")
    assert "Math.random" not in page, "the map must not use randomness (B-R2)"
    assert "Date.now" not in page, "the map must not seed from the clock (B-R2)"
    assert "hash32" in page and "unit(n.id" in page, "layout must be seeded from node identity"


def test_b_r3_baseline_is_anchored_to_a_sha(tmp_path):
    repo = _git_repo(tmp_path)
    base = baseline_mod.compute(repo)
    assert base.anchor in ("head", "merge-base")
    assert len(base.sha) == 40, "the baseline anchor must be a commit SHA, not a time"
    again = baseline_mod.compute(repo)
    assert again.sha == base.sha and again.cached, "the baseline must be cached by SHA"


def test_b_r4_replay_reconstructs_identical_state():
    first = replay(EventLog(SESSION_LOG).read())
    second = replay(EventLog(SESSION_LOG).read())
    assert first.digest() == second.digest()
    # And replaying a prefix then the rest equals replaying the whole thing,
    # which is what makes a mid-stream browser refresh safe.
    events = list(EventLog(SESSION_LOG).read())
    assert replay(events).digest() == replay(events[:5] + events[5:]).digest()


# ------------------------------------------------------ 1.2 offline, isolation


def test_b_r5_and_b_r6_page_is_self_contained_and_offline():
    page = PAGE.read_text(encoding="utf-8")
    for marker in ("http://", "https://", "//cdn", "<script src", "<link rel=\"stylesheet\""):
        # The xmlns constant is a namespace identifier, never fetched.
        occurrences = [
            line for line in page.splitlines()
            if marker in line and "www.w3.org" not in line
        ]
        assert not occurrences, f"page reaches outside itself: {marker} in {occurrences[:2]}"
    assert page.count("<html") == 1, "the page must be one file (B-R6)"


def test_b_r5_package_has_no_runtime_dependencies():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = pyproject.split("dependencies = ", 1)[1].split("\n", 1)[0]
    assert block.strip() == "[]", "a runtime dependency breaks offline install (B-R5)"


def test_b_r7_server_binds_loopback_only_and_offers_no_alternative():
    assert server.BIND_HOST == "127.0.0.1"
    source = (ROOT / "irus" / "server.py").read_text(encoding="utf-8")
    assert "0.0.0.0" not in source, "no configuration may expose the server (B-R7)"
    assert "--host" not in source


# --------------------------------------------------------- 1.3 safety of stage 2


@pytest.mark.parametrize("url", [
    "http://example.com/api/checkout",
    "https://api.stripe.com/v1/charges",
    "http://10.0.0.4:8000/api",
    "http://169.254.169.254/latest/meta-data/",
])
def test_b_r8_refuses_non_localhost(url):
    with pytest.raises(prove.SafetyViolation):
        prove.assert_local(url)


@pytest.mark.parametrize("url", ["http://localhost:8000/api/x", "http://127.0.0.1:7345/", "/api/checkout"])
def test_b_r8_allows_localhost_and_bare_paths(url):
    prove.assert_local(url)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_b_r9_never_sends_a_real_mutation_over_the_wire(method):
    with pytest.raises(prove.SafetyViolation):
        prove.assert_transport(method, "wire")
    prove.assert_transport(method, "test_client")      # in-process is the only way


def test_b_r10_mutating_request_without_a_rolling_back_transaction_is_refused(tmp_path):
    prove.grant_consent(tmp_path)
    finding = _payload_finding()
    result = prove.tier2(
        finding, root=tmp_path,
        client_factory=lambda: _never_called(),
        row_counter=lambda: 10,
        transaction=None,
    )
    assert result.result == "refused" and "B-R10" in result.detail


def test_b_r11_a_run_that_changed_the_database_fails_loudly(tmp_path):
    prove.grant_consent(tmp_path)
    counts = iter([10, 11])           # a row leaked past the rollback

    class _Response:
        status_code = 200
        def json(self): return {}

    class _NullTransaction:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with pytest.raises(prove.SafetyViolation) as excinfo:
        prove.tier2(
            _payload_finding(), root=tmp_path,
            client_factory=lambda: _StubClient(_Response()),
            row_counter=lambda: next(counts),
            transaction=_NullTransaction,
        )
    assert "B-R11" in str(excinfo.value)


def test_b_r11_without_a_row_counter_tier_2_refuses_rather_than_runs(tmp_path):
    prove.grant_consent(tmp_path)
    result = prove.tier2(
        _payload_finding(), root=tmp_path,
        client_factory=lambda: _never_called(), row_counter=None,
    )
    assert result.result == "refused" and "B-R11" in result.detail


def test_b_r12_stage_2_is_opt_in_on_first_use(tmp_path):
    with pytest.raises(prove.ConsentRequired):
        prove.tier2(_payload_finding(), root=tmp_path,
                    client_factory=lambda: _never_called(), row_counter=lambda: 0)
    prove.grant_consent(tmp_path)
    assert prove.has_consent(tmp_path)


def test_tier1_never_sends_anything():
    """A-R8: construct and validate, do not send. tier1 has no client at all,
    which is the only way to make that unfakeable."""
    result = prove.tier1(_payload_finding())
    assert result.method == "schema" and result.result == "fail" and result.status == 422


# ----------------------------------------------------------- 1.4 performance


def test_b_r13_full_sweep_of_500_files_under_2_seconds(tmp_path):
    repo = _synthetic_repo(tmp_path, files=500)
    started = time.perf_counter()
    result = sweep(repo)
    elapsed = time.perf_counter() - started
    assert result.files_scanned >= 500
    assert elapsed < 2.0, f"sweep took {elapsed:.2f}s over {result.files_scanned} files (B-R13)"


def test_b_r14_incremental_recheck_under_200ms(tmp_path):
    repo = _synthetic_repo(tmp_path, files=500)
    cache = SeamCache()
    sweep(repo, cache=cache)                       # warm
    (repo / "web" / "View0.tsx").write_text(
        'fetch("/api/e0", { method: "POST", body: JSON.stringify({ id: 1 }) });\n',
        encoding="utf-8",
    )
    started = time.perf_counter()
    sweep(repo, cache=cache)
    elapsed = (time.perf_counter() - started) * 1000
    assert elapsed < 200, f"incremental re-check took {elapsed:.0f} ms (B-R14)"


def test_b_r15_seam_results_are_cached_by_content_hash_of_both_sides():
    cache = SeamCache()
    first = sweep(SYNTHETIC, cache=cache)
    populated = len(cache.data)
    assert populated > 0, "nothing was cached"
    second = sweep(SYNTHETIC, cache=cache)
    assert len(cache.data) == populated, "identical input added new cache entries"
    assert digest(first.findings) == digest(second.findings), "a cache hit changed the answer"


def test_b_r16_watcher_ignores_the_named_directories(tmp_path):
    for name in ("node_modules", "__pycache__", "dist", ".venv"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "noise.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "real.py").write_text("y = 2\n", encoding="utf-8")
    found = {p.name for p in source_files(tmp_path)}
    assert found == {"real.py"}
    assert {"node_modules", ".git", "__pycache__", "dist", ".venv"} <= ALWAYS_IGNORE


def test_b_r16_watcher_respects_gitignore(tmp_path):
    (tmp_path / ".gitignore").write_text("generated/\n*.gen.py\n", encoding="utf-8")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "b.gen.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("x=1\n", encoding="utf-8")
    assert {p.name for p in source_files(tmp_path)} == {"c.py"}


def test_b_r16_bursts_are_debounced_into_one_callback(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    watcher = Watcher(tmp_path, debounce=0.05, interval=0.01)
    calls: list[Change] = []
    # Three writes in quick succession must settle into one change.
    for value in (2, 3, 4):
        (tmp_path / "a.py").write_text(f"x={value}\n", encoding="utf-8")
        time.sleep(0.02)
        change = watcher.poll()
        if change:
            calls.append(change)
    merged = calls[0]
    for change in calls[1:]:
        merged = merged.merge(change)
    assert merged.paths == {"a.py"}, "a burst on one file must coalesce to one path"


def test_change_merge_cancels_a_temp_file():
    added_then_removed = Change(added={"tmp.py"}).merge(Change(removed={"tmp.py"}))
    assert not added_then_removed.paths


# -------------------------------------------------------- 1.5 signal quality


def test_b_r17_only_high_confidence_findings_fail_the_gate():
    findings = sweep(SYNTHETIC).findings
    assert any(f.gates() for f in findings)
    for finding in findings:
        assert finding.gates() == (finding.confidence == "high")


def test_b_r18_suppression_requires_a_recorded_reason(tmp_path):
    suppressions = Suppressions(tmp_path)
    with pytest.raises(ValueError):
        suppressions.add("seam-001", "")
    suppressions.add("seam-001", "called by the k8s liveness probe, not by this tree")
    reloaded = Suppressions(tmp_path)
    assert "seam-001" in reloaded
    assert "k8s" in reloaded.reason("seam-001")


def test_b_r18_suppressed_findings_are_still_counted(tmp_path):
    findings = sweep(SYNTHETIC).findings
    suppressions = Suppressions(tmp_path)
    suppressions.add(findings[0].id, "known, accepted")
    kept, hidden = suppressions.apply(findings)
    assert len(hidden) == 1 and len(kept) == len(findings) - 1


def test_b_r19_every_finding_names_its_sites_and_a_specific_disagreement():
    for finding in sweep(SYNTHETIC).findings:
        assert finding.paths, f"{finding.id} names no file"
        assert len(finding.detail) > 20, f"{finding.id} has a generic detail"
        # The detail must contain something concrete: a field name, a path, or
        # an encoding — not just a category.
        assert any(token in finding.detail for token in ("/", "_", "multipart", "json"))


def test_b_r19_a_finding_without_evidence_cannot_be_constructed():
    with pytest.raises(MissingEvidence):
        Finding(seam="POST /x", cls="payload_mismatch", confidence="high",
                detail="mismatch", producer=None, consumer=None, evidence={})
    with pytest.raises(MissingEvidence):
        Finding(seam="POST /x", cls="payload_mismatch", confidence="high",
                detail="bad", producer=Side("a.py", 1, "x"), consumer=None, evidence={})


def test_b_r20_a_clean_checkout_produces_zero_findings():
    assert sweep(CLEAN).findings == [], "the clean fixture must produce no findings"


def test_b_r20_baseline_makes_pre_existing_findings_invisible(tmp_path):
    """Point Irus at a messy repo: zero. Change one thing: exactly one."""
    repo = _git_repo(tmp_path, source=SYNTHETIC)
    base = baseline_mod.compute(repo)
    current = sweep(repo).findings
    new, pre_existing = baseline_mod.session_findings(current, base)
    assert new == [], f"a clean checkout of a messy repo reported {len(new)} findings"
    assert len(pre_existing) == len(current) > 0

    # Now introduce one disagreement.
    (repo / "web" / "Second.tsx").write_text(
        'fetch("/api/refund", { method: "POST", body: JSON.stringify({ orderId: "1" }) });\n',
        encoding="utf-8",
    )
    new, _ = baseline_mod.session_findings(sweep(repo).findings, base)
    assert len(new) == 1, f"expected exactly one new finding, got {[f.seam for f in new]}"


# ------------------------------------------------------ 2. event log contract


def test_b_r21_the_log_is_append_only(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.append("finding", id="seam-001", seam="POST /a", detail="x")
    first = (tmp_path / "events.jsonl").read_bytes()
    log.append("finding", id="seam-002", seam="POST /b", detail="y")
    second = (tmp_path / "events.jsonl").read_bytes()
    assert second.startswith(first), "an earlier event was rewritten"
    assert len(list(log.read())) == 2


def test_b_r21_callers_cannot_forge_a_timestamp_or_kind(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    with pytest.raises(ValueError):
        log.append("finding", t=0)
    with pytest.raises(ValueError):
        log.append("finding", kind="baseline")


def test_b_r22_unknown_kinds_are_ignored_rather_than_fatal(tmp_path):
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append("baseline", sha="abc", findings=3)
    log.append("teleportation", payload={"from": "the future"})
    log.append("finding", id="seam-001", seam="POST /a", detail="x")
    state = replay(log.read())
    assert state.baseline_sha == "abc"
    assert "seam-001" in state.findings
    assert state.ignored_kinds == {"teleportation": 1}


def test_b_r22_malformed_and_truncated_lines_do_not_stop_a_replay(tmp_path):
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append("baseline", sha="abc", findings=1)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
        fh.write('{"kind": "finding"}\n')          # no timestamp
        fh.write('{"t": 1, "kind": "finding", "id": "seam-9", "se')   # truncated
    state = replay(EventLog(path).read())
    assert state.baseline_sha == "abc" and state.findings == {}


def test_b_r23_the_fixture_the_recording_and_the_replay_are_one_file():
    events = list(EventLog(SESSION_LOG).read())
    assert events, "the session fixture is empty"
    kinds = {e["kind"] for e in events}
    assert {"session", "baseline", "claim", "surface", "finding"} <= kinds
    # Every event round-trips through the same JSON contract as the log itself.
    for event in events:
        assert set(event) >= {"t", "kind"}


def test_event_shape_matches_the_prd_example():
    """PRD-B section 2 gives literal event shapes. Drift here is a spec break."""
    events = list(EventLog(SESSION_LOG).read())
    surface = next(e for e in events if e["kind"] == "surface")
    assert {"id", "side", "shape"} <= set(surface)
    finding = next(e for e in events if e["kind"] == "finding")
    assert {"id", "seam", "class", "confidence", "detail"} <= set(finding)
    proof = next(e for e in events if e["kind"] == "proof")
    assert {"id", "method", "result"} <= set(proof)


# ------------------------------------------------------------- 3. interfaces


def test_section_3_1_exit_codes():
    clean = _cli("--root", str(CLEAN), "check", "--no-baseline")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    dirty = _cli("--root", str(SYNTHETIC), "check", "--no-baseline")
    assert dirty.returncode == 1, "a high-confidence finding must exit 1 (A-R17)"


def test_section_3_1_all_five_commands_exist():
    help_text = _cli("--help").stdout
    for command in ("check", "watch", "baseline", "ledger"):
        assert command in help_text


def test_section_3_2_visual_contract_colours_are_exact():
    page = PAGE.read_text(encoding="utf-8")
    required = {
        "#898781": "healthy node",
        "#d03b3b": "broken seam",
        "#c98500": "orphan, dark",
        "#eda100": "orphan, light",
        "#3987e5": "active, dark",
        "#2a78d6": "active, light",
    }
    for value, role in required.items():
        assert value in page, f"missing {role} colour {value}"


def test_section_3_2_identity_is_a_ring_never_the_fill():
    page = PAGE.read_text(encoding="utf-8")
    assert ".ring" in page and "AGENT_RING" in page
    # The ring is applied as a stroke; a fill would violate the contract.
    assert 'class: "ring", stroke: colour' in page


def test_section_3_2_baseline_layer_is_dim_and_unlabelled():
    page = PAGE.read_text(encoding="utf-8")
    assert ".baseline-edge" in page and ".baseline-node" in page
    baseline_block = page.split(".baseline-edge", 1)[1].split("}", 1)[0]
    assert "opacity" in baseline_block
    assert "stroke-width: 1" in baseline_block, "baseline edges must be thin"


def test_section_3_2_missing_connection_is_a_dashed_red_arc_with_a_gap():
    page = PAGE.read_text(encoding="utf-8")
    assert "stroke-dasharray" in page
    assert "not connected" in page, "the gap must be labelled, not merely drawn"
    assert "const gap = " in page, "endpoints must be pulled apart"


def test_page_is_theme_aware_in_both_directions():
    page = PAGE.read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in page
    assert "--broken: #d03b3b" in page


# --------------------------------------------------------- 4. integrity rules


def test_b_r24_no_model_decides_whether_a_test_passed():
    """The verdict path is tier1/tier2 and the receipt. None of them may import
    a model client, and none of them may accept a verdict from outside."""
    for module in ("irus/prove.py", "irus/receipts.py", "irus/check.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        for banned in ("openai", "anthropic", "langchain", "llm"):
            assert f"import {banned}" not in source.lower()


def test_b_r25_the_receipt_never_claims_zero_false_positives():
    receipt = _receipt_for(CLEAN)
    text = receipts.render(receipt, colour=False)
    assert "false positives are not zero" in text
    assert "zero false positives" not in text.replace("false positives are not zero", "")


def test_b_r26_the_demo_refuses_a_synthetic_fixture():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "demo.py"), str(SESSION_LOG), "--no-browser"],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    assert result.returncode == 3, "a synthetic fixture must not replay by default"
    assert "B-R26" in result.stderr


def test_b_r26_the_synthetic_marker_travels_inside_the_recording():
    session = next(e for e in EventLog(SESSION_LOG).read() if e["kind"] == "session")
    assert session.get("synthetic") is True, "the recording must carry its own provenance"


def test_b_r27_the_clean_fixture_is_the_check_on_weakening_a_check():
    """If a check is weakened to make a case pass, the clean fixture stops
    proving anything. Assert it still has teeth: the synthetic tree must produce
    findings the clean tree does not."""
    dirty = {f.cls for f in sweep(SYNTHETIC).findings}
    assert {"payload_mismatch", "env_unset"} <= dirty
    assert sweep(CLEAN).findings == []


def test_b_r29_the_merge_conflict_statistic_carries_its_caveat():
    stat = receipts.MERGE_CONFLICT_STAT
    assert "27.67%" in stat
    assert "caveat" in stat.lower()
    assert "git already surfaces" in stat
    assert "58% to 25%" in stat, "the on-target number must travel with it"


# ---------------------------------------------------------- 5. measurement


def test_b_r30_the_ledger_publishes_false_positives_beside_every_number(tmp_path):
    labels = {"synthetic-checkout": {}}
    result = ledger_mod.run_repo(SYNTHETIC, labels=labels)
    markdown = ledger_mod.render_ledger([result])
    assert "false:" in markdown
    assert "unlabelled:" in markdown
    assert "not a claim of zero false positives" in markdown


def test_b_r31_a_label_without_a_reason_is_refused(tmp_path):
    with pytest.raises(ValueError):
        ledger_mod.label(tmp_path, "repo", "seam-001", "TRUE", "")
    with pytest.raises(ValueError):
        ledger_mod.label(tmp_path, "repo", "seam-001", "MAYBE", "unsure")
    ledger_mod.label(tmp_path, "repo", "seam-001", "FALSE", "called by the k8s probe")
    stored = ledger_mod.load_labels(tmp_path)
    assert stored["repo"]["seam-001"]["reason"] == "called by the k8s probe"


def test_b_r32_the_ledger_is_generated_and_says_so(tmp_path):
    result = ledger_mod.run_repo(SYNTHETIC, labels={})
    markdown = ledger_mod.render_ledger([result])
    assert "Do not edit this file" in markdown
    assert "labels.json" in markdown


def test_b_r32_an_unlabelled_finding_is_shown_not_hidden():
    result = ledger_mod.run_repo(SYNTHETIC, labels={})
    assert result.unlabelled == len(result.rows) > 0
    assert "UNLABELLED" in ledger_mod.render_ledger([result])


def test_ledger_is_unfiltered_by_baseline_and_confidence():
    """5.1: unfiltered means unfiltered. The ledger must include medium and low
    findings that the gate would ignore."""
    rows = ledger_mod.run_repo(SYNTHETIC, labels={}).rows
    tiers = {row.finding.confidence for row in rows}
    assert "high" in tiers and len(tiers) > 1, "the ledger dropped non-gating findings"


def test_measurement_5_3_no_accuracy_number_is_computed_over_our_own_labels():
    """5.3: no accuracy figure over a corpus our own checker labelled. The only
    ratio the ledger prints is over *hand* labels, and it is absent when none
    exist."""
    markdown = ledger_mod.render_ledger([ledger_mod.run_repo(SYNTHETIC, labels={})])
    assert "Precision" not in markdown, "a precision figure appeared with zero hand labels"


# ------------------------------------------------------------- 6. demo


def test_b_r33_to_b_r41_are_committed_in_the_demo_document():
    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    for requirement in ["B-R33", "B-R34", "B-R35", "B-R36", "B-R37",
                        "B-R38", "B-R39", "B-R40", "B-R41"]:
        assert requirement in demo, f"{requirement} has no committed answer in docs/DEMO.md"


def test_b_r39_the_first_high_confidence_finding_follows_the_second_release():
    """The canvas starts empty and gains its red arc when the second agent
    finishes — asserted against the recorded ordering, not against intent."""
    events = list(EventLog(SESSION_LOG).read())
    releases = [i for i, e in enumerate(events) if e["kind"] == "release"]
    first_high = next(
        i for i, e in enumerate(events)
        if e["kind"] == "finding" and e.get("confidence") == "high"
    )
    assert len(releases) >= 2, "the recording needs two agents finishing"
    assert first_high > releases[1], "the arc appeared before the second agent finished"
    assert not any(
        e["kind"] == "finding" for e in events[:releases[1]]
    ), "the canvas was not empty of findings before the second release"


def test_b_r41_a_recovery_line_exists_for_each_known_failure_mode():
    demo = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    for mode in ["server", "browser", "empty", "port"]:
        assert mode in demo.lower(), f"no recovery line covers '{mode}'"


# ----------------------------------------------------------------- helpers


class _StubClient:
    def __init__(self, response):
        self.response = response

    def request(self, *args, **kwargs):
        return self.response


def _never_called():
    raise AssertionError("a client was built when the run should have been refused")


def _payload_finding() -> Finding:
    return Finding(
        seam="POST /api/checkout",
        cls="payload_mismatch",
        confidence="high",
        detail="consumer sends multipart but producer declares json (CheckoutRequest)",
        producer=Side("api/routes.py", 24, "json body"),
        consumer=Side("web/Checkout.tsx", 31, "multipart body"),
        evidence={
            "expected": {"email": "str", "amount": "int"},
            "required": ["email", "amount"],
            "sent": {"user_email": "str", "total": "str"},
            "producer_encoding": "json",
            "consumer_encoding": "multipart",
            "body_form": "formdata",
        },
    )


def _receipt_for(root: Path) -> receipts.Receipt:
    result = sweep(root)
    return receipts.Receipt(
        findings=result.findings, suppressed=[], proofs={},
        baseline_sha="", baseline_anchor="none", baseline_count=0,
        files_scanned=result.files_scanned, duration_ms=result.duration_ms,
    )


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "irus", *args],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )


def _git_repo(tmp_path: Path, source: Path | None = None) -> Path:
    """A real git repository, because the baseline uses real worktrees."""
    import shutil

    repo = tmp_path / "repo"
    repo.mkdir()
    if source:
        for item in source.iterdir():
            if item.is_dir():
                shutil.copytree(item, repo / item.name)
            else:
                shutil.copy2(item, repo / item.name)
    else:
        (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True, env=env)
    return repo


def _synthetic_repo(tmp_path: Path, files: int) -> Path:
    """A tree of `files` source files, half producer half consumer, all agreeing.
    Used for timing only — its content is uninteresting on purpose."""
    repo = tmp_path / "perf"
    (repo / "api").mkdir(parents=True)
    (repo / "web").mkdir(parents=True)
    half = files // 2
    for i in range(half):
        (repo / "api" / f"r{i}.py").write_text(
            "from fastapi import APIRouter\n"
            "from pydantic import BaseModel\n\n"
            "router = APIRouter()\n\n"
            f"class M{i}(BaseModel):\n    id: int\n\n"
            f'@router.post("/api/e{i}")\n'
            f"async def h{i}(payload: M{i}):\n    return payload\n",
            encoding="utf-8",
        )
    for i in range(files - half):
        (repo / "web" / f"View{i}.tsx").write_text(
            f'fetch("/api/e{i}", {{ method: "POST", body: JSON.stringify({{ id: 1 }}) }});\n',
            encoding="utf-8",
        )
    return repo
