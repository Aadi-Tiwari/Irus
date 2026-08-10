"""Join someone else's session from your own machine.

The room is the only thing that is shared. Your code stays on your disk and
theirs stays on theirs; what crosses the network is claims, interface shapes and
findings, which is text measured in kilobytes. That is the whole reason this can
be a small feature instead of a file-sync product.

Reading a room needs nothing but the URL. Writing to it needs the token the host
set, because a shared room with no token is one that anyone able to reach the
port can write findings into.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator


class JoinError(RuntimeError):
    pass


@dataclass
class Room:
    url: str
    room: str = "default"
    token: str = ""

    def _endpoint(self, path: str) -> str:
        base = self.url.rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = "http://" + base
        sep = "&" if "?" in path else "?"
        return f"{base}{path}{sep}room={self.room}"

    def _open(self, path: str, data: bytes | None = None, timeout: float = 10.0):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self._endpoint(path), data=data, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise JoinError(
                    "the host requires a token; pass --token with the value they "
                    "set as IRUS_TOKEN"
                ) from exc
            if exc.code == 404 and "/fs/" in path:
                raise JoinError(
                    "this room is not sharing files; the host has to start it "
                    "with --share-files"
                ) from exc
            if exc.code == 400:
                try:
                    raise JoinError(json.load(exc)["error"]) from exc
                except (json.JSONDecodeError, KeyError):
                    pass
            raise JoinError(f"{exc.code} from {self.url}") from exc
        except OSError as exc:
            raise JoinError(f"cannot reach {self.url}: {exc}") from exc

    # ---- reading ---------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return json.load(self._open("/health"))

    def state(self) -> list[dict[str, Any]]:
        return json.load(self._open("/state"))["events"]

    def follow(self) -> Iterator[dict[str, Any]]:
        """Replay everything, then block for new events as they land."""
        stream = self._open("/events", timeout=None)
        for raw in stream:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                yield json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue

    # ---- writing ---------------------------------------------------------
    def send(self, kind: str, **fields: Any) -> dict[str, Any]:
        payload = json.dumps({"kind": kind, **fields}).encode()
        return json.load(self._open("/ingest", data=payload))

    # ---- presence --------------------------------------------------------
    def announce(self, agent: str, tool: str = "") -> dict[str, Any]:
        """Say you are here. Presence is a write, so it needs the token: a room
        anyone can silently appear in is not a room anyone can trust."""
        return self.send("join", agent=agent, tool=tool)

    def depart(self, agent: str) -> dict[str, Any]:
        return self.send("leave", agent=agent)

    # ---- the host's files ------------------------------------------------
    # Only available when the host started the room with --share-files, and
    # always token-gated, reads included. Source is not findings.
    def files(self) -> list[dict[str, Any]]:
        return json.load(self._open("/fs/list"))["files"]

    def read_file(self, path: str) -> str:
        from urllib.parse import quote

        return json.load(self._open(f"/fs/read?path={quote(path)}"))["content"]

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        payload = json.dumps({"path": path, "content": content}).encode()
        return json.load(self._open("/fs/write", data=payload))


def members(events: list[dict[str, Any]]) -> dict[str, str]:
    """Who is currently in the room, from the join and leave events.

    Derived from the log rather than tracked separately, so a member list
    survives a server restart and a browser refresh for the same reason the
    findings do.
    """
    present: dict[str, str] = {}
    for event in events:
        agent = str(event.get("agent", ""))
        if not agent:
            continue
        if event.get("kind") == "join":
            present[agent] = str(event.get("tool") or "")
        elif event.get("kind") == "leave":
            present.pop(agent, None)
    return present


def summarise(events: list[dict[str, Any]]) -> str:
    """What a person wants to know on joining: what is broken and who holds what."""
    findings: dict[str, dict[str, Any]] = {}
    claims: dict[str, str] = {}
    surfaces: set[str] = set()
    for event in events:
        kind = event.get("kind")
        if kind == "finding":
            findings[str(event.get("id"))] = event
        elif kind == "surface":
            surfaces.add(str(event.get("id")))
        elif kind == "claim":
            claims[str(event.get("target"))] = str(event.get("agent", "?"))
        elif kind == "release":
            claims.pop(str(event.get("target")), None)

    present = members(events)
    high = [f for f in findings.values() if f.get("confidence") == "high"]
    lines = [
        f"{len(surfaces)} surface(s), {len(findings)} finding(s), "
        f"{len(high)} high confidence"
    ]
    if present:
        who = ", ".join(
            f"{a} ({t})" if t else a for a, t in sorted(present.items())
        )
        lines.append(f"in the room: {who}")
    for f in sorted(findings.values(), key=lambda x: x.get("confidence") != "high"):
        mark = "!" if f.get("confidence") == "high" else "-"
        lines.append(f"  {mark} [{f.get('class')}] {f.get('seam')}: {f.get('detail')}")
    if claims:
        lines.append("")
        for target, agent in sorted(claims.items()):
            lines.append(f"  claimed: {target} by {agent}")
    return "\n".join(lines)
