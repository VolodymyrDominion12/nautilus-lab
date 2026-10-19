"""SSH tunnel from the workstation to the live paper terminal on the VPS.

The VPS publishes only Caddy (``deploy/docker-compose.yml``): the ``api`` container has
no host port, and the dashboard is meant to be reached over Tailscale. An SSH tunnel is
the alternative when Tailscale is not available — the browser talks to
``http://127.0.0.1:<local-port>`` on the workstation, sshd on the server connects to
Caddy's port, and the server opens nothing new.

Two things can silently point the tunnel at nothing, so the command says both before it
starts:

* the server's ``API_ALLOWED_ORIGINS`` must contain the tunnel origin
  (``http://127.0.0.1:<local-port>``): the dashboard bundle is same-origin
  (``VITE_API_URL=same-origin``), so the browser sends exactly that ``Origin``
  (docs/26-deploy-vps.md §4);
* Caddy binds ``BIND_ADDR`` (``deploy/.env``) — ``127.0.0.1`` by default, but the
  Tailscale address on a server that is reached over Tailscale. In that case the
  forward target is that address, not localhost.

This module only builds and runs the ``ssh`` argv; it has no opinion about trading and
never talks to the API itself.
"""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from subprocess import CompletedProcess, run

#: Local port by default, so it never collides with the workstation's own API (:8000).
DEFAULT_LOCAL_PORT = 8087
#: Caddy's plain-HTTP port (deploy/Caddyfile `{$SITE_ADDRESS::80}`).
DEFAULT_REMOTE_PORT = 80
#: Caddy's `BIND_ADDR` default. Override when the server binds its Tailscale address.
DEFAULT_REMOTE_HOST = "127.0.0.1"
#: Keeps the tunnel through NAT/idle timeouts; 0 disables the keepalive options.
DEFAULT_KEEPALIVE_SECONDS = 30
#: The tunnel listens on loopback only: a forwarded dashboard must not become a LAN service.
LOCAL_BIND_HOST = "127.0.0.1"


@dataclass(frozen=True)
class VpsTarget:
    """``[user@]host`` as written on the ``ssh`` command line."""

    user: str
    host: str

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host


@dataclass(frozen=True)
class VpsTunnel:
    """Everything one local port-forward to the paper dashboard needs."""

    target: VpsTarget
    local_port: int = DEFAULT_LOCAL_PORT
    remote_host: str = DEFAULT_REMOTE_HOST
    remote_port: int = DEFAULT_REMOTE_PORT
    ssh_port: int | None = None
    identity: str | None = None
    keepalive_seconds: int = DEFAULT_KEEPALIVE_SECONDS

    @property
    def url(self) -> str:
        return f"http://{LOCAL_BIND_HOST}:{self.local_port}"


def parse_vps_target(raw: str) -> VpsTarget:
    """Parse ``user@host`` (or just ``host``), rejecting anything ssh would misread."""
    value = raw.strip()
    if not value:
        raise ValueError(
            "set the VPS: lab tunnel --vps user@host (or VPS=user@host, like scripts/deploy_vps.sh)"
        )
    if any(ch.isspace() for ch in value):
        raise ValueError(f"invalid VPS target {raw!r}: whitespace is not allowed")
    if value.startswith("-"):
        raise ValueError(f"invalid VPS target {raw!r}: must not start with '-'")
    user, marker, host = value.rpartition("@")
    if not marker:
        user, host = "", value
    if not host or host.startswith("-"):
        raise ValueError(f"invalid VPS target {raw!r}: expected user@host or host")
    if marker and (not user or "@" in user):
        raise ValueError(f"invalid VPS target {raw!r}: expected one user before '@'")
    return VpsTarget(user=user, host=host)


def build_ssh_command(tunnel: VpsTunnel) -> list[str]:
    """The exact argv: an ssh local forward, no remote command, no shell involved."""
    local_port = _checked_port("--local-port", tunnel.local_port)
    remote_port = _checked_port("--remote-port", tunnel.remote_port)
    ssh_port = _checked_port("--ssh-port", tunnel.ssh_port)
    remote_host = tunnel.remote_host.strip()
    if not remote_host:
        raise ValueError(
            "remote host is empty: pass --remote-host <BIND_ADDR> (Caddy's bind address)"
        )
    if tunnel.keepalive_seconds < 0:
        raise ValueError("--keepalive must be >= 0")

    forward = f"{LOCAL_BIND_HOST}:{local_port}:{_bracket(remote_host)}:{remote_port}"
    command = ["ssh", "-N", "-T", "-o", "ExitOnForwardFailure=yes"]
    if tunnel.keepalive_seconds:
        command += [
            "-o",
            f"ServerAliveInterval={tunnel.keepalive_seconds}",
            "-o",
            "ServerAliveCountMax=3",
        ]
    command += ["-L", forward]
    if ssh_port is not None:
        command += ["-p", str(ssh_port)]
    if tunnel.identity:
        command += ["-i", str(Path(tunnel.identity).expanduser())]
    command.append(tunnel.target.destination)
    return command


def tunnel_notes(tunnel: VpsTunnel) -> tuple[str, ...]:
    """What the user must know for the tunnel to show a real dashboard, not a dead port."""
    return (
        f"paper terminal: {tunnel.url} (through ssh to {tunnel.target.destination})",
        f"the server's .env must allow that exact origin: API_ALLOWED_ORIGINS={tunnel.url} "
        "(docs/26-deploy-vps.md §4); restart the api container after changing it",
        f"Caddy must listen on {tunnel.remote_host}:{tunnel.remote_port} — if the server "
        "uses a Tailscale BIND_ADDR, pass --remote-host <that 100.x.y.z address>",
        "Ctrl-C closes the tunnel; nothing new is published on the server",
    )


def run_tunnel(tunnel: VpsTunnel) -> int:
    """Print what is about to happen, then hold the tunnel in the foreground."""
    command = build_ssh_command(tunnel)
    ssh = which(command[0])
    if ssh is None:
        print(
            "ssh is not installed (OpenSSH client not found on PATH); "
            "install it to open the tunnel",
            file=sys.stderr,
        )
        return 1
    command[0] = ssh
    for line in tunnel_notes(tunnel):
        print(line)
    print(f"$ {shlex.join(command)}")
    try:
        completed: CompletedProcess[bytes] = run(command, check=False)  # noqa: S603 — fixed argv, no shell
    except KeyboardInterrupt:
        print("\ntunnel closed", file=sys.stderr)
        return 0
    except OSError as exc:
        print(f"could not start ssh: {exc}", file=sys.stderr)
        return 1
    if completed.returncode != 0:
        print(
            f"ssh exited with code {completed.returncode}: the tunnel is not established",
            file=sys.stderr,
        )
        return 1
    return 0


def _checked_port(flag: str, port: int | None) -> int | None:
    if port is None:
        return None
    if not 1 <= port <= 65535:
        raise ValueError(f"{flag} must be between 1 and 65535, got {port}")
    return port


def _bracket(host: str) -> str:
    """IPv6 literals need brackets inside an ssh ``-L`` forward spec."""
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host
