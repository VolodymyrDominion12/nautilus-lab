"""deploy/backup.sh: the off-server backup loop, run against a stub `restic` and `wget`.

The real restic is not needed to check what matters here: the job refuses to run
without a repository and a password, initialises a new repository once, backs up only
paths that exist, prunes at most once a day, and reports success to the heartbeat only
after a snapshot was actually written.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "backup.sh"
SH = shutil.which("sh")

pytestmark = pytest.mark.skipif(SH is None, reason="needs a POSIX sh")

# The stubs log every call as one line; `restic cat config` fails until `restic init`.
_RESTIC = """#!/bin/sh
echo "restic $*" >> "$STUB_LOG"
case "$1" in
    cat) [ -f "$STUB_DIR/initialised" ] ;;
    init) touch "$STUB_DIR/initialised" ;;
    backup) [ "${STUB_BACKUP_FAILS:-0}" != "1" ] ;;
    *) true ;;
esac
"""
_WGET = """#!/bin/sh
echo "wget $*" >> "$STUB_LOG"
"""


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def world(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "restic", _RESTIC)
    _stub(bin_dir, "wget", _WGET)
    root = tmp_path / "backup"
    (root / "data" / "paper" / "sessions").mkdir(parents=True)
    (root / "reports").mkdir()
    return tmp_path


def _run(world: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    log = world / "calls.log"
    base = {
        "PATH": f"{world / 'bin'}:{os.environ.get('PATH', '')}",
        "STUB_LOG": str(log),
        "STUB_DIR": str(world),
        "BACKUP_ROOT": str(world / "backup"),
        "BACKUP_ONESHOT": "1",
        "RESTIC_REPOSITORY": "s3:https://example.invalid/bucket",
        "RESTIC_PASSWORD": "pw",
    }
    merged = {**base, **env}
    merged = {key: value for key, value in merged.items() if value != "<unset>"}
    assert SH is not None
    result = subprocess.run(
        [SH, str(SCRIPT)], capture_output=True, text=True, env=merged, check=False
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


@pytest.mark.parametrize("missing", ["RESTIC_REPOSITORY", "RESTIC_PASSWORD"])
def test_refuses_to_run_without_repository_or_password(world: Path, missing: str) -> None:
    result, calls = _run(world, **{missing: "<unset>"})
    assert result.returncode != 0
    assert missing in result.stderr
    assert calls == [], "nothing touched before the configuration is complete"


def test_first_run_initialises_then_backs_up_existing_paths_only(world: Path) -> None:
    result, calls = _run(world, BACKUP_HEARTBEAT_URL="https://hc.invalid/abc")
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls[0] == "restic cat config"
    assert calls[1] == "restic init"
    backup = next(call for call in calls if call.startswith("restic backup"))
    assert f"{world}/backup/data/paper" in backup
    assert f"{world}/backup/reports" in backup
    assert "agg_trade" not in backup, "absent paths are skipped, not errors"
    assert any(call.startswith("restic forget") and "--prune" in call for call in calls)
    assert calls[-1] == "wget -q -T 10 -O /dev/null https://hc.invalid/abc"


def test_existing_repository_is_not_initialised_again(world: Path) -> None:
    (world / "initialised").touch()
    _, calls = _run(world)
    assert "restic init" not in calls


def test_failed_backup_exits_non_zero_and_skips_the_heartbeat(world: Path) -> None:
    result, calls = _run(
        world, STUB_BACKUP_FAILS="1", BACKUP_HEARTBEAT_URL="https://hc.invalid/abc"
    )
    assert result.returncode == 1
    assert not any(call.startswith("wget") for call in calls), "no ping for a failed backup"
    assert not any(call.startswith("restic forget") for call in calls)


def test_nothing_to_back_up_is_a_failure_not_a_silent_success(world: Path) -> None:
    shutil.rmtree(world / "backup")
    (world / "backup").mkdir()
    result, calls = _run(world)
    assert result.returncode == 1
    assert "nothing to back up" in result.stdout
    assert not any(call.startswith("restic backup") for call in calls)


def test_compose_backup_service_mounts_read_only_whole_folders() -> None:
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((SCRIPT.parent / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["backup"]
    assert service["profiles"] == ["backup"], "opt-in: no repository, no backup service"
    data_mounts = [m for m in service["volumes"] if not m.startswith(("./", "restic_cache"))]
    assert data_mounts, "the backup must see the data"
    for mount in data_mounts:
        assert mount.endswith(":ro"), f"{mount} must be read-only"
        host = mount.split(":")[0]
        assert host.count("/") == 1, f"{mount}: mount whole top-level folders only"
