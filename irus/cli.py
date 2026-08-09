"""The command line — PRD-B section 3.1.

    irus check            one-shot sweep, prints receipts     0 clean / 1 finding
    irus check --prove    same, plus stage-2 execution proof   as above
    irus watch            local server, browser, live stream   until interrupted
    irus baseline         recompute and cache the baseline     0
    irus ledger <repo>    unfiltered run + labelling worksheet 0

Plus three that support them: `label` (record a ledger verdict), `suppress`
(silence a false positive with a reason), and `replay` (reconstruct state from a
log, which is how B-R4 is checked by hand).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

from . import baseline as baseline_mod
from . import ledger as ledger_mod
from .check import SeamCache, sweep
from .events import EventLog, replay
from .findings import Suppressions
from .prove import ConsentRequired, SafetyViolation, grant_consent, prove
from .receipts import Receipt, render
from .server import BIND_HOST, serve
from .watcher import Watcher

DEFAULT_LOG = Path(".irus") / "events.jsonl"


def _log_for(root: Path, override: str | None) -> EventLog:
    return EventLog(Path(override) if override else root / DEFAULT_LOG)


def _run_sweep(root: Path, log: EventLog, *, no_baseline: bool, do_prove: bool, unfiltered: bool):
    """One full pass, with events written as it goes. Shared by `check` and the
    watch loop so the two cannot drift apart."""
    cache = SeamCache(root / ".irus" / "seams.json")
    result = sweep(root, cache=cache)
    cache.save()

    if unfiltered or no_baseline:
        base = baseline_mod.Baseline(sha="", finding_ids=set(), count=0, anchor="none")
        session = result.findings
    else:
        base = baseline_mod.compute(root)
        session, _pre_existing = baseline_mod.session_findings(result.findings, base)

    log.append("baseline", sha=base.sha, findings=base.count, anchor=base.anchor)

    # Surfaces, both sides, so the page can draw the seam even when it is fine.
    for route in result.routes:
        log.append(
            "surface", id=route.seam, side="producer",
            shape=dict(route.model.fields) if route.model else {},
            encoding=route.encoding, file=route.file,
        )
    for call in result.calls:
        log.append(
            "surface", id=call.seam, side="consumer",
            shape=dict(call.fields), encoding=call.encoding, file=call.file,
        )

    suppressions = Suppressions(root)
    kept, hidden = suppressions.apply(session)

    for finding in kept:
        log.append("finding", **finding.to_event())

    proofs = {}
    if do_prove:
        for result_ in prove(kept, root=root):
            proofs[result_.finding_id] = result_
            log.append("proof", **result_.to_event())

    receipt = Receipt(
        findings=kept,
        suppressed=hidden,
        proofs=proofs,
        baseline_sha=base.sha,
        baseline_anchor=base.anchor,
        baseline_count=base.count,
        files_scanned=result.files_scanned,
        duration_ms=result.duration_ms,
    )
    log.append(
        "receipt", total=len(kept), high=len(receipt.gating),
        suppressed=len(hidden), exit_code=receipt.exit_code,
        duration_ms=round(result.duration_ms, 1), files=result.files_scanned,
    )
    return receipt


# ------------------------------------------------------------------ commands


def cmd_check(args) -> int:
    root = Path(args.root).resolve()
    log = _log_for(root, args.log)
    if args.prove and args.yes:
        grant_consent(root)
    log.append("session", command="check", root=str(root), prove=bool(args.prove))
    try:
        receipt = _run_sweep(
            root, log,
            no_baseline=args.no_baseline, do_prove=args.prove, unfiltered=False,
        )
    except ConsentRequired as exc:
        print(f"irus: {exc}", file=sys.stderr)
        return 2
    except SafetyViolation as exc:
        print(f"irus: SAFETY: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(render(receipt))
    return receipt.exit_code


def cmd_baseline(args) -> int:
    root = Path(args.root).resolve()
    base = baseline_mod.compute(root, refresh=True)
    if base.anchor == "none":
        print("irus: not a git repository; nothing to anchor a baseline to", file=sys.stderr)
        return 0
    print(f"baseline {base.sha[:7]} ({base.anchor}) — {base.count} findings cached")
    _log_for(root, args.log).append("baseline", sha=base.sha, findings=base.count, anchor=base.anchor)
    return 0


def cmd_watch(args) -> int:
    root = Path(args.root).resolve()
    log = _log_for(root, args.log)
    log.append("session", command="watch", root=str(root))

    httpd = serve(log.path, port=args.port)
    url = f"http://{BIND_HOST}:{args.port}/"
    print(f"irus watching {root}")
    print(f"  → {url}   (loopback only; nothing leaves this machine)")

    receipt = _run_sweep(root, log, no_baseline=args.no_baseline, do_prove=False, unfiltered=False)
    print(render(receipt))

    if not args.no_browser:
        webbrowser.open(url)

    watcher = Watcher(root)

    def on_change(change) -> None:
        started = time.perf_counter()
        result = _run_sweep(root, log, no_baseline=args.no_baseline, do_prove=False, unfiltered=False)
        elapsed = (time.perf_counter() - started) * 1000
        touched = ", ".join(sorted(change.paths)[:3])
        print(f"  {touched} → {len(result.findings)} findings ({elapsed:.0f} ms)")

    try:
        watcher.watch(on_change)
    except KeyboardInterrupt:
        print("\nirus: stopped")
    finally:
        httpd.shutdown()
    return 0


def cmd_ledger(args) -> int:
    root = Path(args.root).resolve()
    repos = [Path(r).resolve() for r in args.repos]
    labels = ledger_mod.load_labels(root)

    results = [ledger_mod.run_repo(repo, labels=labels) for repo in repos]
    for result in results:
        sys.stdout.write(ledger_mod.worksheet(result))

    if args.write:
        markdown = ledger_mod.render_ledger(results)
        out = root / ledger_mod.LEDGER_PATH
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print(f"wrote {out}")
    return 0


def cmd_label(args) -> int:
    root = Path(args.root).resolve()
    try:
        ledger_mod.label(root, args.repo, args.finding, args.verdict, args.reason)
    except ValueError as exc:
        print(f"irus: {exc}", file=sys.stderr)
        return 2
    print(f"labelled {args.finding} {args.verdict.upper()} in {args.repo}")
    return 0


def cmd_suppress(args) -> int:
    root = Path(args.root).resolve()
    try:
        Suppressions(root).add(args.finding, args.reason)
    except ValueError as exc:
        print(f"irus: {exc}", file=sys.stderr)
        return 2
    print(f"suppressed {args.finding} — {args.reason}")
    return 0


def cmd_replay(args) -> int:
    """Fold a log into state and print its digest. Two identical digests from
    the same log is B-R4, checkable by hand."""
    state = replay(EventLog(args.log).read())
    if args.digest:
        print(state.digest())
        return 0
    print(json.dumps(json.loads(state.digest()), indent=2))
    return 0


# -------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="irus", description="Catch the bug between two agents.")
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    parser.add_argument("--log", default=None, help="event log path (default: .irus/events.jsonl)")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="one-shot sweep, prints receipts")
    check.add_argument("--prove", action="store_true", help="add stage-2 execution proof")
    check.add_argument("--yes", action="store_true", help="record consent for stage 2 (B-R12)")
    check.add_argument("--no-baseline", action="store_true", help="report everything, not just this session")
    check.set_defaults(func=cmd_check)

    base = sub.add_parser("baseline", help="recompute and cache the baseline")
    base.set_defaults(func=cmd_baseline)

    watch = sub.add_parser("watch", help="serve the live local page")
    watch.add_argument("--port", type=int, default=7345)
    watch.add_argument("--no-browser", action="store_true")
    watch.add_argument("--no-baseline", action="store_true")
    watch.set_defaults(func=cmd_watch)

    ledger = sub.add_parser("ledger", help="unfiltered run against repositories")
    ledger.add_argument("repos", nargs="+")
    ledger.add_argument("--write", action="store_true", help="write findings/ledger.md")
    ledger.set_defaults(func=cmd_ledger)

    label = sub.add_parser("label", help="record a ledger verdict with a reason")
    label.add_argument("repo")
    label.add_argument("finding")
    label.add_argument("verdict", choices=["TRUE", "FALSE", "true", "false"])
    label.add_argument("reason")
    label.set_defaults(func=cmd_label)

    suppress = sub.add_parser("suppress", help="silence a known false positive")
    suppress.add_argument("finding")
    suppress.add_argument("reason")
    suppress.set_defaults(func=cmd_suppress)

    rep = sub.add_parser("replay", help="reconstruct state from a log")
    rep.add_argument("log")
    rep.add_argument("--digest", action="store_true")
    rep.set_defaults(func=cmd_replay)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
