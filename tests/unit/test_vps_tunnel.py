"""`lab tunnel`: the ssh argv that reaches the VPS paper dashboard (docs/26)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nautilus_lab.infrastructure import vps_tunnel
from nautilus_lab.infrastructure.vps_tunnel import (
    VpsTunnel,
    build_ssh_command,
    parse_vps_target,
    run_tunnel,
    tunnel_notes,
)
from nautilus_lab.interfaces import cli as cli_module
from nautilus_lab.interfaces.cli import main


def test_target_parses_user_and_host() -> None:
    target = parse_vps_target("lab@100.101.102.103")

    assert target.user == "lab"
    assert target.host == "100.101.102.103"
    assert target.destination == "lab@100.101.102.103"


def test_target_host_only_uses_ssh_default_user() -> None:
    target = parse_vps_target("100.101.102.103")

    assert target.user == ""
    assert target.destination == "100.101.102.103"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "lab@", "@host", "lab @host", "a@b@c", "-oProxyCommand=evil"],
)
def test_target_rejects_garbage(raw: str) -> None:
    with pytest.raises(ValueError, match="VPS"):
        parse_vps_target(raw)


def test_default_command_forwards_localhost_to_caddy() -> None:
    command = build_ssh_command(VpsTunnel(parse_vps_target("lab@vps.example")))

    assert command == [
        "ssh",
        "-N",
        "-T",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-L",
        "127.0.0.1:8087:127.0.0.1:80",
        "lab@vps.example",
    ]


def test_ports_identity_and_ssh_port_land_on_the_right_flags(tmp_path: Path) -> None:
    key = tmp_path / "id_ed25519"
    tunnel = VpsTunnel(
        parse_vps_target("lab@vps"),
        local_port=9001,
        remote_host="100.101.102.103",
        remote_port=443,
        ssh_port=2222,
        identity=str(key),
    )

    command = build_ssh_command(tunnel)

    assert command[command.index("-L") + 1] == "127.0.0.1:9001:100.101.102.103:443"
    assert command[command.index("-p") + 1] == "2222"
    assert command[command.index("-i") + 1] == str(key)
    assert command[-1] == "lab@vps"


def test_ipv6_remote_host_is_bracketed() -> None:
    command = build_ssh_command(VpsTunnel(parse_vps_target("vps"), remote_host="::1"))

    assert command[command.index("-L") + 1] == "127.0.0.1:8087:[::1]:80"


def test_identity_expands_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    command = build_ssh_command(VpsTunnel(parse_vps_target("vps"), identity="~/keys/id"))

    assert command[command.index("-i") + 1] == str(tmp_path / "keys" / "id")


def test_keepalive_can_be_disabled() -> None:
    command = build_ssh_command(VpsTunnel(parse_vps_target("vps"), keepalive_seconds=0))

    assert not any(item.startswith("ServerAlive") for item in command)


@pytest.mark.parametrize("local_port", [0, -1, 65536])
def test_local_port_must_be_in_range(local_port: int) -> None:
    with pytest.raises(ValueError, match="--local-port"):
        build_ssh_command(VpsTunnel(parse_vps_target("vps"), local_port=local_port))


def test_remote_port_must_be_in_range() -> None:
    with pytest.raises(ValueError, match="--remote-port"):
        build_ssh_command(VpsTunnel(parse_vps_target("vps"), remote_port=0))


def test_empty_remote_host_is_refused() -> None:
    with pytest.raises(ValueError, match="--remote-host"):
        build_ssh_command(VpsTunnel(parse_vps_target("vps"), remote_host="  "))


def test_notes_name_the_origin_the_server_must_allow() -> None:
    tunnel = VpsTunnel(parse_vps_target("lab@vps"), local_port=8087)

    notes = "\n".join(tunnel_notes(tunnel))

    assert tunnel.url == "http://127.0.0.1:8087"
    assert "API_ALLOWED_ORIGINS=http://127.0.0.1:8087" in notes
    assert "--remote-host" in notes
    assert "lab@vps" in notes


def test_cli_print_only_prints_a_runnable_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VPS", raising=False)

    rc = main(["tunnel", "--vps", "lab@vps.example", "--print-only"])

    assert rc == 0
    printed = capsys.readouterr().out.strip()
    assert printed.startswith("ssh -N -T ")
    assert "-L 127.0.0.1:8087:127.0.0.1:80" in printed
    assert printed.endswith("lab@vps.example")


def test_cli_uses_vps_env_like_the_deploy_scripts(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VPS", "lab@100.101.102.103")

    assert main(["tunnel", "--print-only"]) == 0

    assert capsys.readouterr().out.strip().endswith("lab@100.101.102.103")


def test_cli_without_a_target_explains_the_flag(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VPS", raising=False)

    assert main(["tunnel", "--print-only"]) == 1

    assert "--vps" in capsys.readouterr().err


def test_cli_rejects_an_out_of_range_port(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VPS", raising=False)

    assert main(["tunnel", "--vps", "lab@vps", "--local-port", "0", "--print-only"]) == 1

    assert "--local-port" in capsys.readouterr().err


def test_cli_tunnel_needs_no_settings_or_catalog(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> None:
        raise AssertionError("`lab tunnel` must not compose Settings")

    monkeypatch.setattr(cli_module, "settings", boom)

    assert main(["tunnel", "--vps", "lab@vps", "--print-only"]) == 0
    assert capsys.readouterr().out.strip().endswith("lab@vps")


def test_run_tunnel_execs_the_resolved_ssh_and_prints_the_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        assert check is False
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(vps_tunnel, "which", lambda name: "/usr/bin/ssh")
    monkeypatch.setattr(vps_tunnel, "run", fake_run)

    rc = run_tunnel(VpsTunnel(parse_vps_target("lab@vps")))

    assert rc == 0
    assert calls[0][0] == "/usr/bin/ssh"
    assert calls[0][-1] == "lab@vps"
    out = capsys.readouterr().out
    assert "$ /usr/bin/ssh" in out
    assert "API_ALLOWED_ORIGINS=http://127.0.0.1:8087" in out


def test_run_tunnel_maps_ssh_failure_to_exit_code_1(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vps_tunnel, "which", lambda name: "/usr/bin/ssh")
    monkeypatch.setattr(
        vps_tunnel,
        "run",
        lambda command, *, check: subprocess.CompletedProcess(command, 255),
    )

    assert run_tunnel(VpsTunnel(parse_vps_target("lab@vps"))) == 1

    assert "not established" in capsys.readouterr().err


def test_run_tunnel_without_ssh_client_fails_closed(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(vps_tunnel, "which", lambda name: None)

    assert run_tunnel(VpsTunnel(parse_vps_target("lab@vps"))) == 1

    assert "ssh is not installed" in capsys.readouterr().err


def test_run_tunnel_treats_ctrl_c_as_a_clean_close(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(command: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        raise KeyboardInterrupt

    monkeypatch.setattr(vps_tunnel, "which", lambda name: "/usr/bin/ssh")
    monkeypatch.setattr(vps_tunnel, "run", interrupted)

    assert run_tunnel(VpsTunnel(parse_vps_target("lab@vps"))) == 0

    assert "tunnel closed" in capsys.readouterr().err


def test_run_tunnel_maps_oserror_to_exit_code_1(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(command: list[str], *, check: bool) -> subprocess.CompletedProcess[bytes]:
        raise OSError("exec format error")

    monkeypatch.setattr(vps_tunnel, "which", lambda name: "/usr/bin/ssh")
    monkeypatch.setattr(vps_tunnel, "run", broken)

    assert run_tunnel(VpsTunnel(parse_vps_target("lab@vps"))) == 1

    assert "could not start ssh" in capsys.readouterr().err
