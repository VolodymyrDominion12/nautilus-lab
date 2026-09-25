"""Job state survives an API restart (docs/27 E-2.2): adopt the living, record the lost.

These use real child processes: whether a pid is alive, a zombie or reused is exactly
what a fake would get wrong.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from nautilus_lab.api.job_store import FINISHED, LOST, RUNNING, AdoptedProcess, JobStore
from nautilus_lab.api.jobs import JobManager

pytestmark = pytest.mark.skipif(
    not Path("/proc/self").exists(), reason="pid checks read /proc (Linux, the VPS)"
)

SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]


def _manager(tmp_path: Path) -> JobManager:
    return JobManager(
        reports_dir=tmp_path, python=sys.executable, store=JobStore(tmp_path / "jobs.sqlite")
    )


@pytest.fixture
def sleeper() -> Iterator[subprocess.Popen[bytes]]:
    """A child left running by 'the previous API process'."""
    process = subprocess.Popen(SLEEPER)
    yield process
    process.kill()
    process.wait()


def test_store_keeps_the_last_run_of_each_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "data" / "jobs.sqlite")
    assert not (tmp_path / "data").exists(), "nothing is written before the first use"
    store.started("ingest", pid=123, command=["lab", "ingest"], started_at="2026-09-25T10:00")
    assert [r.name for r in store.running()] == ["ingest"]
    store.finished("ingest", returncode=0, finished_at="2026-09-25T10:05")
    record = store.get("ingest")
    assert record is not None
    assert (record.status, record.returncode, record.command) == (FINISHED, 0, "lab ingest")
    assert store.running() == []
    # A new run replaces the row: one row per job kind, the last run.
    store.started("ingest", pid=456, command=["lab"], started_at="2026-09-25T11:00")
    again = store.get("ingest")
    assert again is not None and (again.status, again.pid, again.returncode) == (RUNNING, 456, None)


def test_a_finished_run_is_written_down(tmp_path: Path) -> None:
    jobs = _manager(tmp_path)
    code = jobs.run_to_log("ingest", [sys.executable, "-c", "print('ok')"], tmp_path / "i.log")
    assert code == 0
    record = JobStore(tmp_path / "jobs.sqlite").get("ingest")
    assert record is not None and record.status == FINISHED and record.returncode == 0


def test_a_living_child_is_adopted_and_blocks_a_second_run(
    tmp_path: Path, sleeper: subprocess.Popen[bytes]
) -> None:
    JobStore(tmp_path / "jobs.sqlite").started(
        "ingest", pid=sleeper.pid, command=SLEEPER, started_at="2026-09-25T10:00:00+00:00"
    )
    jobs = _manager(tmp_path)  # the restarted API

    assert jobs.adopt() == [f"adopted ingest (pid {sleeper.pid})"]
    assert jobs.active("ingest")
    assert not jobs.reserve("ingest"), "no second ingest on top of the adopted one"
    payload = jobs.payload("ingest")
    assert payload["running"] and payload["adopted"]
    assert payload["started_at"] == "2026-09-25T10:00:00+00:00"

    assert jobs.cancel("ingest")
    sleeper.wait(timeout=5)  # reaped by its real parent, the test
    assert not jobs.active("ingest")
    record = JobStore(tmp_path / "jobs.sqlite").get("ingest")
    assert record is not None and record.status == FINISHED
    assert record.returncode == AdoptedProcess.UNKNOWN_EXIT


def test_a_child_that_died_with_the_api_is_recorded_as_lost(tmp_path: Path) -> None:
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    JobStore(tmp_path / "jobs.sqlite").started(
        "research", pid=gone.pid, command=["python", "-m", "x"], started_at="2026-09-25T10:00"
    )
    jobs = _manager(tmp_path)

    assert jobs.adopt()[0].startswith("lost research")
    assert not jobs.active("research")
    assert jobs.reserve("research"), "a lost run does not hold the slot"
    jobs.release("research")
    assert jobs.payload("research")["last_run"]["status"] == LOST


def test_a_reused_pid_is_neither_adopted_nor_signalled(tmp_path: Path) -> None:
    """The recorded pid now belongs to another program: leave it alone."""
    stranger = subprocess.Popen(SLEEPER)
    try:
        JobStore(tmp_path / "jobs.sqlite").started(
            "ml_train",
            pid=stranger.pid,
            command=["python", "-m", "nautilus_lab.api.run_ml_job"],
            started_at="2026-09-25T10:00",
        )
        jobs = _manager(tmp_path)
        assert jobs.adopt()[0].startswith("lost ml_train")
        assert not jobs.cancel("ml_train")
        assert stranger.poll() is None, "the other program is still running"
    finally:
        stranger.kill()
        stranger.wait()


def test_without_a_store_nothing_is_adopted(tmp_path: Path) -> None:
    jobs = JobManager(reports_dir=tmp_path, python=sys.executable)
    assert jobs.adopt() == []
    assert "last_run" not in jobs.payload("paper")
