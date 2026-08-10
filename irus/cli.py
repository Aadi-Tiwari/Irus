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
from . import join as join_mod
from . import ledger as ledger_mod
from . import party as party_mod
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


def cmd_join(args: argparse.Namespace) -> int:
    """Join a room someone else is hosting."""
    url, token = args.url, args.token or ""
    # A join code carries the address and the token together, so there is one
    # thing to paste rather than two flags to get right.
    if not url.startswith(("http://", "https://")) or "#" in url:
        try:
            invite = party_mod.decode(url)
            url, token = invite.url, invite.token or token
        except party_mod.BadCode:
            if not url.startswith(("http://", "https://")):
                url = "http://" + url
    room = join_mod.Room(url=url, room=args.room, token=token)
    try:
        health = room.health()
    except join_mod.JoinError as exc:
        print(f"irus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"joined {url} room={args.room} ({health.get('service', '?')})", flush=True)

    if args.pull:
        target = Path(args.pull).resolve()
        try:
            written = room.pull(target)
        except join_mod.JoinError as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"pulled {len(written)} file(s) into {target}", flush=True)
        print("\n  edit them however you like, then:", flush=True)
        print(f"    irus join {args.url} --push {target}\n", flush=True)
        return EXIT_CLEAN

    if args.push:
        source = Path(args.push).resolve()
        if not source.is_dir():
            print(f"irus: {source} is not a directory", file=sys.stderr)
            return EXIT_ERROR
        try:
            sent = room.push(source)
        except join_mod.JoinError as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        if not sent:
            print("nothing changed", flush=True)
        for rel in sent:
            print(f"  pushed {rel}", flush=True)
        return EXIT_CLEAN

    if args.ls:
        try:
            for entry in room.files():
                print(f"  {entry['bytes']:>8}  {entry['path']}", flush=True)
        except join_mod.JoinError as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_CLEAN

    if args.cat:
        try:
            sys.stdout.write(room.read_file(args.cat))
        except join_mod.JoinError as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_CLEAN

    if args.put:
        remote, local = args.put
        try:
            content = Path(local).read_text(encoding="utf-8")
            result = room.write_file(remote, content)
        except (OSError, join_mod.JoinError) as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"wrote {result['bytes']} bytes to {remote} on the host", flush=True)
        return EXIT_CLEAN

    if args.leave:
        try:
            room.depart(args.agent)
        except join_mod.JoinError as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"left the room as {args.agent}", flush=True)
        return EXIT_CLEAN

    # Announcing presence is a write, so it only happens when a token was
    # given. A read-only guest watches without appearing in the roster, which
    # is honest: we cannot vouch for someone who never authenticated.
    if args.token and not (args.claim or args.release):
        try:
            room.announce(args.agent, tool=args.tool)
        except join_mod.JoinError:
            pass

    if args.claim:
        try:
            room.send("claim", agent=args.agent, target=args.claim)
        except join_mod.JoinError as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"claimed {args.claim} as {args.agent}", flush=True)
        return EXIT_CLEAN

    if args.release:
        try:
            room.send("release", agent=args.agent, target=args.release)
        except join_mod.JoinError as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(f"released {args.release}", flush=True)
        return EXIT_CLEAN

    try:
        events = room.state()
    except join_mod.JoinError as exc:
        print(f"irus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(join_mod.summarise(events), flush=True)

    if not args.follow:
        return EXIT_CLEAN

    print("\nfollowing; ctrl-c to stop", flush=True)
    seen = len(events)
    try:
        for index, event in enumerate(room.follow()):
            if index < seen or event.get("kind") == "ping":
                continue
            kind = event.get("kind")
            if kind == "finding":
                mark = "!" if event.get("confidence") == "high" else "-"
                print(f"  {mark} [{event.get('class')}] {event.get('seam')}: "
                      f"{event.get('detail')}", flush=True)
            elif kind in ("claim", "release"):
                print(f"  {kind}: {event.get('target')} by {event.get('agent')}",
                      flush=True)
    except KeyboardInterrupt:
        pass
    except join_mod.JoinError as exc:
        print(f"irus: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_CLEAN


def _local_addresses() -> list[str]:
    """Every IPv4 address a second machine might reach this one on."""
    import socket

    out: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in out and not address.startswith("127."):
                out.append(address)
    except OSError:
        pass
    return out


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

    # Binding past localhost puts the room on a network, so it may not be done
    # unauthenticated. A shared room with no token is one that anyone able to
    # reach the port can write findings into.
    if args.host != "127.0.0.1" and not web.TOKEN:
        print(
            f"irus: refusing to bind {args.host} without a token. Set IRUS_TOKEN "
            "first, and give the same value to whoever joins.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    if args.share_files:
        if not web.TOKEN:
            print(
                "irus: --share-files needs a token. Set IRUS_TOKEN first: it is "
                "the only thing standing between a guest and your disk.",
                file=sys.stderr,
            )
            return EXIT_ERROR
        web.SHARE_ROOT = root
        print(f"sharing files from {root} with anyone holding the token", flush=True)

    try:
        httpd = web.serve(port=args.port, host=args.host)
    except OSError as exc:
        hint = ""
        if "10013" in str(exc):
            hint = (
                "\n      That port is reserved by Windows, usually for Hyper-V"
                " or WSL.\n      Try: irus host --port 8787"
            )
        print(f"irus: cannot start on port {args.port}: {exc}{hint}", file=sys.stderr)
        return EXIT_ERROR
    port = httpd.server_address[1]
    # flush: stdout is block-buffered when this is piped or redirected, and a
    # long-running server never fills the buffer, so the URL would never appear
    # to anything reading our output.
    print(f"irus watching {root}", flush=True)
    print(f"open http://127.0.0.1:{port}", flush=True)
    invite = getattr(args, "_invite", None)
    if invite is not None:
        address, token = invite
        code = party_mod.encode(address, port, token)
        print("", flush=True)
        print("  send them this one line:", flush=True)
        print(f"\n    irus join {code}\n", flush=True)
        print(f"  (that is http://{address}:{port} plus the token)", flush=True)
        others = [a for a in _local_addresses() if a != address]
        if others:
            print(f"  other addresses if that one cannot be reached: "
                  f"{', '.join(others)}", flush=True)
        if sys.platform == "win32":
            print(
                "\n  if they cannot connect, allow it through the firewall once:"
                f"\n    netsh advfirewall firewall add rule name=irus dir=in "
                f"action=allow protocol=TCP localport={port}",
                flush=True,
            )
    elif args.host != "127.0.0.1":
        for address in _local_addresses():
            print(f"joinable at http://{address}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return EXIT_CLEAN


def cmd_host(args: argparse.Namespace) -> int:
    """Start a room and print one thing to send someone."""
    from . import web

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"irus: {root} is not a directory", file=sys.stderr)
        return EXIT_ERROR

    token = args.token or party_mod.new_token()
    web.TOKEN = token
    if not args.no_files:
        web.SHARE_ROOT = root

    address = args.address or party_mod.best_address()
    if not args.address and not address.startswith("100."):
        print(
            "irus: no Tailscale address found, so this code will only work for "
            "someone on the same network.\n"
            "      If Tailscale is running, pass it explicitly:\n"
            "        irus host --address 100.x.x.x",
            file=sys.stderr,
        )
    port = party_mod.pick_port(args.port)
    if port == 0:
        print(
            "irus: could not bind any of the usual ports. Pass one explicitly:"
            "\n        irus host --port 9000",
            file=sys.stderr,
        )
        return EXIT_ERROR

    watch_args = argparse.Namespace(
        path=str(root), port=port, host="0.0.0.0",
        no_baseline=True, share_files=not args.no_files,
        _invite=(address, token),
    )
    return cmd_watch(watch_args)


def interactive() -> int:
    """`irus` with no arguments. A menu, because a tool people have to be
    talked through is a tool nobody uses under time pressure."""
    print(party_mod.MENU)
    choice = party_mod.ask("choose", "1").lower()

    if choice in ("q", "quit", "exit"):
        return EXIT_CLEAN

    if choice in ("1", "host", "h"):
        path = party_mod.ask("project to share", ".")
        return cmd_host(argparse.Namespace(
            path=path, port=0, token=None, no_files=False, address=None))

    if choice in ("2", "join", "j"):
        code = party_mod.ask("paste the join code")
        if not code:
            print("irus: nothing pasted", file=sys.stderr)
            return EXIT_ERROR
        try:
            invite = party_mod.decode(code)
        except party_mod.BadCode as exc:
            print(f"irus: {exc}", file=sys.stderr)
            return EXIT_ERROR
        agent = party_mod.ask("your name", "guest")
        return cmd_join(argparse.Namespace(
            url=invite.url, room="default", token=invite.token, agent=agent,
            tool="", follow=False, claim=None, release=None, leave=False,
            ls=False, cat=None, put=None, pull=None, push=None))

    if choice in ("3", "check", "c"):
        path = party_mod.ask("project to check", ".")
        return cmd_check(argparse.Namespace(
            path=path, json=False, all=False, no_baseline=False,
            refresh_baseline=False, log=False, prove=False, yes=False,
            app=None, base_url=None))

    print("irus: pick 1, 2, 3 or q", file=sys.stderr)
    return EXIT_ERROR


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="irus", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=False)

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

    host = sub.add_parser("host", help="start a room and print one line to send")
    host.add_argument("path", nargs="?", default=".")
    host.add_argument("--port", type=int, default=0)
    host.add_argument("--token", default=None, help="use this token instead of a fresh one")
    host.add_argument("--address", default=None,
                      help="the address to put in the join code, e.g. your Tailscale 100.x.x.x")
    host.add_argument("--no-files", action="store_true", help="share findings only, not files")
    host.set_defaults(func=cmd_host)

    join = sub.add_parser("join", help="join a room someone else is hosting")
    join.add_argument("url", help="the host's address, e.g. http://10.10.8.145:8902")
    join.add_argument("--room", default="default")
    join.add_argument("--token", default=None, help="the host's IRUS_TOKEN; needed to write")
    join.add_argument("--agent", default="guest", help="who you are, for claims")
    join.add_argument("--follow", action="store_true", help="stream new events as they land")
    join.add_argument("--claim", default=None, metavar="SEAM", help="claim a seam, then exit")
    join.add_argument("--release", default=None, metavar="SEAM")
    join.add_argument("--leave", action="store_true", help="announce that you are leaving")
    join.add_argument("--tool", default="", help="which agent tool you are driving")
    join.add_argument("--ls", action="store_true", help="list the host's project files")
    join.add_argument("--pull", default=None, metavar="DIR",
                      help="copy the host's project into DIR so you can edit it normally")
    join.add_argument("--push", default=None, metavar="DIR",
                      help="send your changed files in DIR back to the host")
    join.add_argument("--cat", default=None, metavar="PATH", help="print one of the host's files")
    join.add_argument(
        "--put", nargs=2, metavar=("REMOTE", "LOCAL"),
        help="write your local file over the host's, at REMOTE",
    )
    join.set_defaults(func=cmd_join)

    watch = sub.add_parser("watch", help="serve the live page")
    watch.add_argument("path", nargs="?", default=".")
    watch.add_argument("--port", type=int, default=0)
    watch.add_argument("--no-baseline", action="store_true")
    watch.add_argument(
        "--share-files", action="store_true",
        help="let guests with the token read and edit this repository's files",
    )
    watch.add_argument(
        "--host", default="127.0.0.1",
        help="bind address; use 0.0.0.0 to let another machine join (requires IRUS_TOKEN)",
    )
    watch.set_defaults(func=cmd_watch)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None) is None:
        return interactive()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
