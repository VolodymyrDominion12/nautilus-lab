"""deploy/check_exposure.sh: an exposed dashboard must not ship without a lock.

The API token is compiled into the dashboard bundle, so on a public bind it protects
nothing; the script is what stops `scripts/deploy_vps.sh` from publishing that.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "check_exposure.sh"
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="needs a POSIX sh")


def run_check(
    tmp_path: Path, env_text: str, *, allow_open: bool = False
) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / "compose.env"
    env_file.write_text(env_text, encoding="utf-8")
    env = {**os.environ, "ALLOW_OPEN_DASHBOARD": "1" if allow_open else "0"}
    assert SH is not None
    return subprocess.run(
        [SH, str(SCRIPT), str(env_file)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    "env_text",
    [
        "",  # compose defaults: 127.0.0.1, :80
        "BIND_ADDR=127.0.0.1\n",
        "BIND_ADDR=100.101.102.103\nSITE_ADDRESS=:80\n",
        "BIND_ADDR=100.64.0.1\n",
        "BIND_ADDR=100.127.255.254\n",
        # A MagicDNS name on a tailnet bind is still reachable only from the tailnet.
        "BIND_ADDR=100.64.0.5\nSITE_ADDRESS=lab.tail1234.ts.net\n",
    ],
)
def test_private_bind_passes_without_lock(tmp_path: Path, env_text: str) -> None:
    result = run_check(tmp_path, env_text)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "bind",
    ["0.0.0.0", "203.0.113.7", "100.63.1.1", "100.128.0.1"],
)
def test_public_bind_without_lock_is_refused(tmp_path: Path, bind: str) -> None:
    result = run_check(tmp_path, f"BIND_ADDR={bind}\nSITE_ADDRESS=lab.example.com\n")
    assert result.returncode == 1
    assert "refusing" in result.stderr


def test_public_bind_with_basic_auth_passes(tmp_path: Path) -> None:
    env_text = (
        "BIND_ADDR=0.0.0.0\n"
        "SITE_ADDRESS=lab.example.com\n"
        "DASHBOARD_AUTH=on\n"
        "BASIC_AUTH_USER=volodymyr\n"
        "BASIC_AUTH_HASH='$2a$14$abcdefghijklmnopqrstuv'\n"
    )
    result = run_check(tmp_path, env_text)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "env_text",
    [
        "DASHBOARD_AUTH=on\nBASIC_AUTH_USER=volodymyr\n",  # no hash
        "DASHBOARD_AUTH=on\nBASIC_AUTH_HASH='$2a$14$x'\n",  # no user
        "DASHBOARD_AUTH=on\nBASIC_AUTH_USER=v\nBASIC_AUTH_HASH=plaintext\n",
        "DASHBOARD_AUTH=ON\n",  # Caddy imports `auth_<value>`: case matters
        "DASHBOARD_AUTH=yes\n",
    ],
)
def test_broken_lock_configuration_is_refused(tmp_path: Path, env_text: str) -> None:
    assert run_check(tmp_path, env_text).returncode == 1


def test_last_assignment_wins_like_compose(tmp_path: Path) -> None:
    result = run_check(tmp_path, 'BIND_ADDR=0.0.0.0\nBIND_ADDR="127.0.0.1"\n')
    assert result.returncode == 0, result.stderr


def test_override_is_explicit_and_loud(tmp_path: Path) -> None:
    result = run_check(tmp_path, "BIND_ADDR=0.0.0.0\n", allow_open=True)
    assert result.returncode == 0
    assert "WARNING" in result.stderr


def test_missing_env_file_fails(tmp_path: Path) -> None:
    assert SH is not None
    result = subprocess.run(
        [SH, str(SCRIPT), str(tmp_path / "absent.env")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_compose_example_is_safe_by_default(tmp_path: Path) -> None:
    example = SCRIPT.parent / "compose.env.example"
    result = run_check(tmp_path, example.read_text(encoding="utf-8"))
    assert result.returncode == 0, result.stderr
