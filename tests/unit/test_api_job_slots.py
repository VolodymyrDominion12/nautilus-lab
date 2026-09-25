"""A job slot is claimed inside the request, not later by the background task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import create_app
from nautilus_lab.api.jobs import JobManager
from nautilus_lab.infrastructure.settings import Settings


def _jobs(tmp_path: Path, launched: list[Any] | None = None) -> JobManager:
    return JobManager(
        reports_dir=tmp_path,
        python="python",
        schedule=None if launched is None else launched.append,
    )


def test_reserve_is_exclusive_until_released(tmp_path: Path) -> None:
    jobs = _jobs(tmp_path)
    assert jobs.reserve("paper")
    assert not jobs.reserve("paper")
    assert jobs.active("paper")
    jobs.release("paper")
    assert not jobs.active("paper")
    assert jobs.reserve("paper")


def test_submitted_work_releases_the_slot_even_when_it_fails(tmp_path: Path) -> None:
    launched: list[Any] = []
    jobs = _jobs(tmp_path, launched)
    assert jobs.reserve("ml_train")

    def boom() -> None:
        raise RuntimeError("the job crashed")

    jobs.submit(None, "ml_train", boom)  # type: ignore[arg-type]
    assert jobs.active("ml_train"), "still claimed until the work has run"
    with pytest.raises(RuntimeError):
        launched[0]()
    assert not jobs.active("ml_train")


def test_second_launch_is_refused_while_the_first_has_not_spawned(tmp_path: Path) -> None:
    """Two quick clicks used to start two processes that clobbered one result file."""
    launched: list[Any] = []
    # The scheduled work never runs: the slot must stay claimed by the request alone.
    app = create_app(
        Settings(_env_file=None),  # type: ignore[call-arg]
        root=tmp_path,
        jobs=_jobs(tmp_path / "reports", launched),
    )
    client = TestClient(app)

    first = client.post("/api/paper/run", json={"robot": "regime", "bars": 200})
    second = client.post("/api/paper/run", json={"robot": "regime", "bars": 200})

    assert first.json()["status"] == "started"
    assert second.json()["status"] == "error"
    assert len(launched) == 1
    # A poll straight after launch sees the job as running, not as finished.
    assert client.get("/api/paper/log").json()["is_running"] is True
