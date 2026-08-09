"""A-R17 and A-R19: the command line.

`irus check` is the whole product for anyone who never opens the page. It exits
nonzero on a high-confidence finding so it works as a merge gate and a CI step,
which is the only adoption path that requires nobody else on the team to change
anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import baseline as baseline_mod
from . import coordinate as coordinate_mod
from . import ledger as ledger_mod
from . import prove as prove_mod
from . import receipts as receipts_mod
from .eventlog import EventLog
from .model import HIGH, Finding
from .scan import ScanCache, scan
from .suppress import Suppressions

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def _emit(log: EventLog, result, findings: list[Finding], base) -> None:
    log.append("baseline", sha=base.sha, how=base.how, suppressed=len(base.keys))
    for s in result.producers + result.consumers:
        log.append(
            "surface",
            id=s.seam,
            side=s.side,
            encoding=s.encoding,
            shape={f.name: f.type for f in s.fields},
            file=str(s.loc),
            mounted=s.mounted,
        )
    for f in findings:
        log.append(
            "finding",
            id=f.key,
            seam=f.seam,
            subject=f.subject,
            **{"class": f.kind},
            confidence=f.confidence,
            detail=f.detail,
            producer=str(f.producer_loc) if f.producer_loc else None,
            consumer=str(f.consumer_loc) if f.consumer_loc else None,
        )


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"irus: {root} is not a directory", file=sys.stderr)
        return EXIT_ERROR

    result = scan(root)
    findings = result.findings

    base = baseline_mod.Baseline(sha="", how="baseline disabled", keys=set())
    if not args.no_baseline:
        try:
            base = baseline_mod.compute(root, refresh=args.refresh_baseline)
            findings = base.suppress(findings)
        except baseline_mod.GitError as exc:
            print(f"irus: baseline unavailable ({exc}); reporting every finding", file=sys.stderr)

    silenced: list = []
    rules = Suppressions.load(root)
    if len(rules):
        findings, silenced = rules.apply(findings)

    proofs: list = []
    if args.prove:
        # A-R12 and B-R12: execution is opt-in twice over. The flag is consent
        # for this run; the recorded consent file is consent given knowingly
        # once, and revoked by deleting a file.
        if args.yes:
            prove_mod.grant_consent(root)
        try:
            prove_mod.require_consent(root)
        except prove_mod.ConsentRequired as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        proofs = prove_mod.prove_all(
            root, result.producers, result.consumers, findings, args.app, args.base_url
        )
        findings = findings + [p.to_finding() for p in proofs if not p.passed]

    log = EventLog(root / ".irus" / "events.jsonl") if args.log else EventLog()
    _emit(log, result, findings, base)
    for pr in proofs:
        log.append(
            "proof",
            seam=pr.seam,
            method=pr.tier,
            result="pass" if pr.passed else "fail",
            status=pr.status,
            detail=pr.detail,
        )

    if args.json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "baseline": {"sha": base.sha, "how": base.how, "suppressed": len(base.keys)},
                    "suppressed_by_rule": [
                        {"key": f.key, "reason": r.reason} for f, r in silenced
                    ],
                    "findings": [f.to_dict() for f in findings],
                },
                indent=2,
                default=str,
            )
        )
    else:
        text = receipts_mod.render(
            receipts_mod.build(result, findings, coordinate_mod.assign(findings)),
            only_failing=not args.all,
        )
        if text.strip():
            print(text)
        for pr in proofs:
            mark = "PASS" if pr.passed else "FAIL"
            print(f"\nproof[{pr.tier}] {pr.seam}  {mark}   {pr.detail}")
        high = [f for f in findings if f.confidence == HIGH]
        print(
            f"\n{len(findings)} finding(s) introduced this session "
            f"({len(high)} high) | baseline {base.sha[:12] or 'none'} "
            f"suppressed {len(base.keys)} pre-existing"
            + (f" | {len(silenced)} silenced by rule" if silenced else "")
        )
        if not findings:
            print("nothing new since the baseline")

    # A-R21 and B-R17: only a high-confidence finding fails the gate, so a
    # speculative finding can be surfaced without ever blocking a merge.
    return EXIT_FINDINGS if any(f.confidence == HIGH for f in findings) else EXIT_CLEAN


def cmd_baseline(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    try:
        base = baseline_mod.compute(root, refresh=True)
    except baseline_mod.GitError as exc:
        print(f"irus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"baseline {base.sha[:12]} ({base.how}): {len(base.keys)} pre-existing finding(s)")
    return EXIT_CLEAN


def cmd_suppress(args: argparse.Namespace) -> int:
    """B-R18. A suppression without a reason is refused, not recorded."""
    root = Path(args.path).resolve()
    if not args.reason.strip():
        print("irus: --reason is required; a suppression with no reason rots", file=sys.stderr)
        return EXIT_ERROR

    match = next((f for f in scan(root).findings if f.key == args.key), None)
    if match is None:
        print(f"irus: no current finding with key {args.key}", file=sys.stderr)
        return EXIT_ERROR

    rules = Suppressions.load(root)
    rules.add(match, args.reason)
    rules.save()
    print(f"silenced {args.key} ({match.kind} on {match.seam}): {args.reason}")
    return EXIT_CLEAN


def cmd_ledger(args: argparse.Namespace) -> int:
    """B-R25, B-R30 to B-R32."""
    roots = [Path(p).resolve() for p in args.paths]
    missing = [p for p in roots if not p.is_dir()]
    if missing:
        print(f"irus: not a directory: {missing[0]}", file=sys.stderr)
        return EXIT_ERROR

    out_dir = Path(args.out).resolve()
    labels = ledger_mod.previous_labels(out_dir / "ledger.json")
    led = ledger_mod.build(roots, labels)
    md, js = ledger_mod.write(led, out_dir)

    print(ledger_mod.to_markdown(led))
    print(f"\nwritten: {md}\n         {js}")
    if led.unlabelled:
        print(
            f"\n{led.unlabelled} finding(s) still unlabelled. "
            "An unlabelled ledger is not evidence: label them before quoting a number."
        )
    return EXIT_CLEAN


def _snapshot(root: Path) -> float:
    from .scan import walk

    return sum(p.stat().st_mtime for p in walk(root))


def cmd_watch(args: argparse.Namespace) -> int:
    import threading
    import time

    from . import web

    root = Path(args.path).resolve()
    web.DATA_DIR = root / ".irus" / "rooms"
    log = web.room("default")
    cache = ScanCache()  # B-R14: one edit re-reads one file, not the tree

    def publish() -> None:
        result = scan(root, cache=cache)
        findings = result.findings
        base = baseline_mod.Baseline(sha="", how="disabled", keys=set())
        if not args.no_baseline:
            try:
                base = baseline_mod.compute(root)
                findings = base.suppress(findings)
            except baseline_mod.GitError:
                pass
        rules = Suppressions.load(root)
        if len(rules):
            findings, _ = rules.apply(findings)
        _emit(log, result, findings, base)

    publish()
    stop = threading.Event()

    def watcher() -> None:
        last = _snapshot(root)
        while not stop.wait(1.0):
            try:
                now = _snapshot(root)
            except OSError:
                continue
            if now != last:
                last = now
                time.sleep(0.25)  # debounce a burst of writes
                publish()

    threading.Thread(target=watcher, daemon=True).start()

    httpd = web.serve(port=args.port, host="127.0.0.1")
    # flush: stdout is block-buffered when this is piped or redirected, and a
    # long-running server never fills the buffer, so the URL would never appear
    # to anything reading our output.
    print(f"irus watching {root}", flush=True)
    print(f"open http://127.0.0.1:{httpd.server_address[1]}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return EXIT_CLEAN


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="irus", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="one-shot sweep; nonzero exit on a high-confidence finding")
    check.add_argument("path", nargs="?", default=".")
    check.add_argument("--json", action="store_true", help="machine-readable output")
    check.add_argument("--all", action="store_true", help="show passing receipts too")
    check.add_argument("--no-baseline", action="store_true", help="report pre-existing findings too")
    check.add_argument("--refresh-baseline", action="store_true")
    check.add_argument("--log", action="store_true", help="append events to .irus/events.jsonl")
    check.add_argument(
        "--prove", action="store_true", help="execute the suspected seams to prove them (opt-in)"
    )
    check.add_argument(
        "--app", default=None, metavar="module:attr", help="ASGI app to drive in-process"
    )
    check.add_argument(
        "--yes", action="store_true",
        help="record consent for stage-2 execution in this repository",
    )
    check.add_argument(
        "--base-url", default=None, metavar="URL",
        help="localhost server to probe with real GET/HEAD/OPTIONS requests (tier 3)",
    )
    check.set_defaults(func=cmd_check)

    base = sub.add_parser("baseline", help="recompute and cache the merge-base baseline")
    base.add_argument("path", nargs="?", default=".")
    base.set_defaults(func=cmd_baseline)

    sup = sub.add_parser("suppress", help="silence a known false positive, with a reason")
    sup.add_argument("key", help="finding key, as printed by check --json")
    sup.add_argument("--reason", required=True)
    sup.add_argument("--path", default=".")
    sup.set_defaults(func=cmd_suppress)

    led = sub.add_parser("ledger", help="unfiltered run across repositories, for labelling")
    led.add_argument("paths", nargs="+")
    led.add_argument("--out", default="findings")
    led.set_defaults(func=cmd_ledger)

    watch = sub.add_parser("watch", help="serve the live page")
    watch.add_argument("path", nargs="?", default=".")
    watch.add_argument("--port", type=int, default=0)
    watch.add_argument("--no-baseline", action="store_true")
    watch.set_defaults(func=cmd_watch)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
