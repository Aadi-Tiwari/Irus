"""One word to start: `irus`.

Hosting used to mean remembering an environment variable, three flags and a bind
address, and joining meant pasting a URL and a token as separate arguments. Both
are one step now, because a tool people have to be talked through is a tool they
do not use at a hackathon.

A join code is the whole invitation in one string: address, port and token,
base64url encoded so it survives being pasted into a chat window without a
helpful client turning part of it into a link.
"""

from __future__ import annotations

import base64
import binascii
import secrets
import socket
from dataclasses import dataclass


class BadCode(ValueError):
    """The pasted code is not a join code."""


@dataclass(frozen=True)
class Invite:
    host: str
    port: int
    token: str

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def encode(host: str, port: int, token: str) -> str:
    raw = f"{host}|{port}|{token}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(code: str) -> Invite:
    """Accept a join code, or a plain URL with the token after a #."""
    code = code.strip()

    if code.startswith(("http://", "https://")):
        base, _, token = code.partition("#")
        rest = base.split("://", 1)[1]
        host, _, port = rest.partition(":")
        if not port.rstrip("/").isdigit():
            raise BadCode("that URL has no port")
        return Invite(host, int(port.rstrip("/")), token)

    padded = code + "=" * (-len(code) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded).decode()
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise BadCode("that is not a join code") from exc
    parts = raw.split("|")
    if len(parts) != 3 or not parts[1].isdigit():
        raise BadCode("that is not a join code")
    return Invite(parts[0], int(parts[1]), parts[2])


def new_token() -> str:
    """A token nobody has to invent, so nobody picks `password`."""
    return secrets.token_urlsafe(12)


TAILSCALE_PATHS = (
    "tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
    "/usr/bin/tailscale",
    "/usr/local/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
)


def tailscale_address() -> str:
    """Ask Tailscale for its own address rather than inferring it.

    Reading adapters through the hostname does not reliably enumerate the
    Tailscale interface on Windows: it worked on one machine here and silently
    missed it on another, so hosting handed out a LAN address that the guest
    could never reach. `tailscale ip -4` is authoritative and costs one
    subprocess.
    """
    import subprocess

    for binary in TAILSCALE_PATHS:
        try:
            out = subprocess.run(
                [binary, "ip", "-4"], capture_output=True, text=True, timeout=5
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in out.stdout.splitlines():
            candidate = line.strip()
            if candidate.startswith("100."):
                return candidate
    return ""


def local_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in addresses and not address.startswith("127."):
                addresses.append(address)
    except OSError:
        pass
    return addresses


def best_address() -> str:
    """The address most likely to reach another machine.

    Tailscale first: it works across networks, and venue and campus wifi
    routinely isolates clients from each other, so a LAN address is the one that
    silently fails on demo day.
    """
    tailnet = tailscale_address()
    if tailnet:
        return tailnet

    addresses = local_addresses()
    for address in addresses:
        if address.startswith("100."):
            return address
    for address in addresses:
        if not address.startswith("10.5."):   # skip the vpn adapter
            return address
    return addresses[0] if addresses else "127.0.0.1"


# Windows reserves blocks of high ports for Hyper-V and WSL, and a socket in a
# reserved range fails with WinError 10013 rather than anything legible. Letting
# the OS choose landed a teammate on 50315 and then 50637, both unreachable.
# These are low, stable and outside every default reservation.
PREFERRED_PORTS = (8787, 8788, 8789, 7373, 9797, 8910)


def excluded_ports() -> list[tuple[int, int]]:
    """Ranges Windows will refuse to bind. Empty everywhere else."""
    import re
    import subprocess

    try:
        out = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [
        (int(a), int(b))
        for a, b in re.findall(r"^\s*(\d+)\s+(\d+)", out, re.M)
    ]


def pick_port(preferred: int = 0) -> int:
    """A port that actually binds, preferring stable low ones.

    Returning 0 and letting the OS decide is what produced an unreachable
    room, so a port is chosen and proven bindable before anything is announced.
    """
    blocked = excluded_ports()

    def usable(port: int) -> bool:
        if any(low <= port <= high for low, high in blocked):
            return False
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    candidates = (preferred,) + PREFERRED_PORTS if preferred else PREFERRED_PORTS
    for port in candidates:
        if port and usable(port):
            return port
    return 0  # nothing worked; fall back to whatever the OS gives us


MENU = """
  irus

  1  host a room        share this project with someone
  2  join a room        work in someone else's project
  3  check this project on your own
  q  quit
"""


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0)
    return answer or default
