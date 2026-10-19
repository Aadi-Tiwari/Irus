"""A-R22: the MCP surface.

Agents get the map as text, never as a picture. The graph is for humans; a
compact text summary is what an agent can actually act on.

JSON-RPC 2.0 over stdio, newline delimited, standard library only.
"""

from __future__ import annotations

import json
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Any

from .eventlog import EventLog
from .model import HIGH
from .intent import load as load_brief
from .report import check

PROTOCOL_VERSION = "2025-06-18"

# Versions this server is happy to speak. The handshake echoes the client's
# choice when it appears here, so a client pinned to an older revision is not
# handed a newer one it never agreed to.
SUPPORTED_VERSIONS = {"2025-06-18", "2025-03-26", "2024-11-05"}


def coordinated(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        path = self.root / ".irus" / "claims.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as lock:
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("Another client is updating claims. Retry this operation.") from exc
            try:
                self.log = EventLog(self.log.path)
                return method(self, *args, **kwargs)
            finally:
                lock.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return locked

TOOLS = [
    {
        "name": "status",
        "description": (
            "Current integration state: seams that disagree, routes nobody calls, "
            "environment variables read but never set. Text, not a picture."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "repository root"}},
        },
    },
    {
        "name": "next",
        "description": "One unclaimed piece of work, or nothing if everything is claimed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "agent": {"type": "string", "description": "who is asking"},
            },
            "required": ["agent"],
        },
    },
    {
        "name": "claim",
        "description": "Announce that you are about to work on a target so others route around it.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent": {"type": "string"}, "target": {"type": "string"}},
            "required": ["agent", "target"],
        },
    },
    {
        "name": "release",
        "description": "Give up a claim.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent": {"type": "string"}, "target": {"type": "string"}},
            "required": ["agent", "target"],
        },
    },
]

TOOLS.insert(0, {
    "name": "brief",
    "description": "Read the human-owned IRUS.md and its revision before claiming work.",
    "inputSchema": {"type": "object", "properties": {}},
})
TOOLS.append({
    "name": "complete",
    "description": "Recheck a claimed HTTP contract in its original worktrees before releasing it.",
    "inputSchema": {
        "type": "object",
        "properties": {"agent": {"type": "string"}, "target": {"type": "string"}},
        "required": ["agent", "target"],
    },
})
for tool in TOOLS:
    props = tool["inputSchema"]["properties"]
    if tool["name"] in {"status", "next", "claim"}:
        props["worktrees"] = {"type": "array", "items": {"type": "string"}}
        props["no_baseline"] = {"type": "boolean", "default": False}
    if tool["name"] in {"next", "claim", "complete"}:
        props["brief_revision"] = {"type": "string", "description": "Revision returned by brief"}


class Server:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or ".").resolve()
        self.log = EventLog(self.root / ".irus" / "claims.jsonl")

    # ---- state ----------------------------------------------------------
    def claims(self) -> dict[str, str]:
        return {target: str(event["agent"]) for target, event in self.claim_records().items()}

    def claim_records(self) -> dict[str, dict]:
        held: dict[str, dict] = {}
        for event in EventLog(self.log.path).replay():
            target = str(event.get("target", ""))
            if event.get("kind") == "claim" and target:
                held[target] = event
            elif event.get("kind") == "release":
                held.pop(target, None)
        return held

    # ---- tools ----------------------------------------------------------
    def tool_brief(self) -> str:
        brief = load_brief(self.root)
        if brief is None:
            return "No IRUS.md. Add the project's goal, boundaries, and acceptance checks to share its intent."
        return f"revision: {brief.revision}\n{brief.path}\n\n{brief.text}"

    def acknowledge(self, revision: str | None) -> None:
        brief = load_brief(self.root)
        if brief is not None and revision != brief.revision:
            raise ValueError("Read brief and supply its current brief_revision before claiming or completing work.")

    def tool_status(self, path: str | None = None, worktrees=(), no_baseline=False) -> str:
        root = Path(path).resolve() if path else self.root
        report = check(root, worktrees=worktrees, no_baseline=no_baseline)
        held = self.claims() if root == self.root else {}
        lines: list[str] = []
        if report.brief:
            lines.append(f"brief revision: {report.brief.revision} (read with brief)")
        high = [f for f in report.findings if f.confidence == HIGH]
        lines.append(f"{len(report.findings)} finding(s), {len(high)} high confidence")
        for f in report.findings:
            mark = "!" if f.confidence == HIGH else "-"
            lines.append(f"{mark} [{f.kind}] {f.seam} {f.subject}: {f.detail}")
            for loc in (f.producer_loc, f.consumer_loc):
                lines.extend("  " + source for source in report.source_locations(loc))
        if held:
            lines.append("")
            lines.append("claimed: " + ", ".join(f"{t} by {a}" for t, a in sorted(held.items())))
        return "\n".join(lines) if lines else "nothing to report"

    @coordinated
    def tool_next(self, agent: str, path: str | None = None, worktrees=(), no_baseline=False, brief_revision=None) -> str:
        if path and Path(path).resolve() != self.root:
            raise ValueError("Claims belong to the configured repository. Start irus-mcp with that repository path.")
        self.acknowledge(brief_revision)
        report = check(self.root, worktrees=worktrees, no_baseline=no_baseline)
        held = self.claims()
        for f in report.findings:
            if f.confidence != HIGH:
                continue
            if f.seam in held:
                continue
            self.record_claim(agent, f.seam, report, brief_revision)
            return f"claimed {f.seam}\n{f.kind}: {f.detail}"
        return "nothing unclaimed"

    def record_claim(self, agent, target, report, revision):
        if not agent.strip() or not target.strip():
            raise ValueError("agent and target must be nonempty")
        self.log.append("claim", agent=agent, target=target, worktrees=report.worktrees[1:], brief_revision=revision)

    @coordinated
    def tool_claim(self, agent: str, target: str, worktrees=(), no_baseline=False, brief_revision=None) -> str:
        self.acknowledge(brief_revision)
        held = self.claims()
        if target in held and held[target] != agent:
            return f"already claimed by {held[target]}"
        report = check(self.root, worktrees=worktrees, no_baseline=no_baseline)
        self.record_claim(agent, target, report, brief_revision)
        return f"claimed {target}"

    @coordinated
    def tool_release(self, agent: str, target: str) -> str:
        if self.claims().get(target) != agent:
            raise ValueError("Only the claim owner can release it.")
        self.log.append("release", agent=agent, target=target)
        return f"released {target}"

    @coordinated
    def tool_complete(self, agent: str, target: str, brief_revision=None) -> str:
        self.acknowledge(brief_revision)
        claim = self.claim_records().get(target)
        if claim is None or claim["agent"] != agent:
            raise ValueError("Only the claim owner can complete it.")
        report = check(self.root, worktrees=claim.get("worktrees", ()), no_baseline=True)
        remaining = [f for f in report.result.findings if f.seam == target]
        if remaining:
            return "still failing: " + "; ".join(f.detail for f in remaining)
        producers = [p for p in report.result.producers if p.seam == target and p.mounted and not p.external]
        consumers = [c for c in report.result.consumers if c.seam == target and not c.external]
        if not producers or not consumers:
            return "unverified: both sides of the HTTP contract must still be present"
        if any(s.encoding == "unknown" or any(f.name == "..." for f in s.fields) for s in [*producers, *consumers]):
            return "unverified: the scanner cannot resolve the complete request contract"
        self.log.append("release", agent=agent, target=target, checked=True, brief_revision=brief_revision)
        return f"completed {target}: static contract rechecked in the claimed worktrees; runtime behavior remains unverified"

    def call(self, name: str, args: dict[str, Any]) -> str:
        if name not in {tool["name"] for tool in TOOLS}:
            raise KeyError(name)
        return getattr(self, "tool_" + name)(**args)

    # ---- protocol -------------------------------------------------------
    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        rid = request.get("id")

        if method == "initialize":
            # Echo the client's protocol version when we know it, rather than
            # always announcing ours. A client that asked for an older version
            # and is handed a newer one is entitled to hang up.
            asked = str((request.get("params") or {}).get("protocolVersion", ""))
            result: Any = {
                "protocolVersion": asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "irus", "version": "0.1.0"},
            }
        elif method == "ping":
            # Clients use ping as a keepalive. Answering -32601 to it makes a
            # perfectly healthy server look dead.
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = request.get("params") or {}
            try:
                text = self.call(params.get("name", ""), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}]}
            except KeyError as exc:
                return _error(rid, -32601, f"unknown tool {exc}")
            except Exception as exc:  # a tool failure is a result, not a crash
                result = {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                }
        elif method in ("notifications/initialized", "initialized"):
            return None
        else:
            return _error(rid, -32601, f"unknown method {method}")

        if rid is None:
            return None
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def main(root: str | None = None) -> int:
    server = Server(Path(root) if root else None)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = server.handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


def cli() -> int:
    """Console-script entry point.

    Takes the repository path as an optional argument and otherwise uses the
    working directory, so a client can register it either way.
    """
    return main(sys.argv[1] if len(sys.argv) > 1 else None)


if __name__ == "__main__":
    raise SystemExit(cli())
