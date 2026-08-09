"""A-R22: the MCP surface.

Agents get the map as text, never as a picture. The graph is for humans; a
compact text summary is what an agent can actually act on.

JSON-RPC 2.0 over stdio, newline delimited, standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .eventlog import EventLog
from .model import HIGH
from .scan import scan

PROTOCOL_VERSION = "2025-06-18"

# Versions this server is happy to speak. The handshake echoes the client's
# choice when it appears here, so a client pinned to an older revision is not
# handed a newer one it never agreed to.
SUPPORTED_VERSIONS = {"2025-06-18", "2025-03-26", "2024-11-05"}

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


class Server:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or ".").resolve()
        self.log = EventLog(self.root / ".irus" / "events.jsonl")

    # ---- state ----------------------------------------------------------
    def claims(self) -> dict[str, str]:
        held: dict[str, str] = {}
        for event in self.log.replay():
            target = str(event.get("target", ""))
            if event.get("kind") == "claim" and target:
                held[target] = str(event.get("agent", "?"))
            elif event.get("kind") == "release":
                held.pop(target, None)
        return held

    # ---- tools ----------------------------------------------------------
    def tool_status(self, path: str | None = None) -> str:
        root = Path(path).resolve() if path else self.root
        result = scan(root)
        held = self.claims()
        lines: list[str] = []
        high = [f for f in result.findings if f.confidence == HIGH]
        lines.append(f"{len(result.findings)} finding(s), {len(high)} high confidence")
        for f in result.findings:
            mark = "!" if f.confidence == HIGH else "-"
            lines.append(f"{mark} [{f.kind}] {f.seam} {f.subject}: {f.detail}")
        if held:
            lines.append("")
            lines.append("claimed: " + ", ".join(f"{t} by {a}" for t, a in sorted(held.items())))
        return "\n".join(lines) if lines else "nothing to report"

    def tool_next(self, agent: str, path: str | None = None) -> str:
        root = Path(path).resolve() if path else self.root
        result = scan(root)
        held = self.claims()
        for f in result.findings:
            if f.confidence != HIGH:
                continue
            if f.seam in held:
                continue
            self.log.append("claim", agent=agent, target=f.seam)
            return f"claimed {f.seam}\n{f.kind}: {f.detail}"
        return "nothing unclaimed"

    def tool_claim(self, agent: str, target: str) -> str:
        held = self.claims()
        if target in held and held[target] != agent:
            return f"already claimed by {held[target]}"
        self.log.append("claim", agent=agent, target=target)
        return f"claimed {target}"

    def tool_release(self, agent: str, target: str) -> str:
        self.log.append("release", agent=agent, target=target)
        return f"released {target}"

    def call(self, name: str, args: dict[str, Any]) -> str:
        if name == "status":
            return self.tool_status(args.get("path"))
        if name == "next":
            return self.tool_next(args.get("agent", "?"), args.get("path"))
        if name == "claim":
            return self.tool_claim(args.get("agent", "?"), args.get("target", ""))
        if name == "release":
            return self.tool_release(args.get("agent", "?"), args.get("target", ""))
        raise KeyError(name)

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
