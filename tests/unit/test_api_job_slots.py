"""A job slot is claimed inside the request, not later by the background task."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api import app as app_module


@pytest.fixture(autouse=True)
def _clean_slots() -> Iterator[None]:
    app_module.JOBS_STARTING.clear()
    yield
    app_module.JOBS_STARTING.clear()


def test_reserve_is_exclusive_until_released() -> None:
    assert app_module._reserve_job("paper")
    assert not app_module._reserve_job("paper")
    assert app_module._job_active("paper")
    app_module._release_job("paper")
    assert not app_module._job_active("paper")
    assert app_module._reserve_job("paper")


def test_second_launch_is_refused_while_the_first_has_not_spawned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two quick clicks used to start two processes that clobbered one result file."""
    launched: list[dict[str, Any]] = []
    # The background task never spawns: the slot must stay claimed by the request alone.
    monkeypatch.setattr(app_module, "run_paper_subprocess", launched.append)
    client = TestClient(app_module.app)

    first = client.post("/api/paper/run", json={"robot": "regime", "bars": 200})
    second = client.post("/api/paper/run", json={"robot": "regime", "bars": 200})

    assert first.json()["status"] == "started"
    assert second.json()["status"] == "error"
    assert len(launched) == 1
    # A poll straight after launch sees the job as running, not as finished.
    assert client.get("/api/paper/log").json()["is_running"] is True
