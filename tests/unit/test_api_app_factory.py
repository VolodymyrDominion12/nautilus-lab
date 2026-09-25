"""`create_app(settings)`: the API as a value a test can build (docs/27 E-2.1).

Before the split every test shared one import-time app and patched its globals
(`SECURITY`, `settings`, `run_paper_subprocess`, `JOBS_STARTING`). These build their own
app from their own settings and check the wiring the split must not lose.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route, WebSocketRoute

from nautilus_lab.api.app import create_app
from nautilus_lab.api.jobs import JobManager
from nautilus_lab.infrastructure.settings import Settings

#: Every route the dashboard and the deploy use, as served before the split into routers.
#: A route that disappears breaks a screen or a health check without any other test
#: failing, so the inventory is pinned. Adding a route means adding it here.
ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/"),
        ("GET", "/api/catalog"),
        ("GET", "/api/catalog/bars"),
        ("GET", "/api/catalog/ingest/log"),
        ("GET", "/api/catalogs"),
        ("GET", "/api/command-center"),
        ("GET", "/api/data"),
        ("GET", "/api/hypotheses"),
        ("GET", "/api/hypotheses/{filename}"),
        ("GET", "/api/journal"),
        ("GET", "/api/metrics"),
        ("GET", "/api/ml/models"),
        ("GET", "/api/ml/train/log"),
        ("GET", "/api/paper/live/state"),
        ("GET", "/api/paper/log"),
        ("GET", "/api/paper/portfolio"),
        ("GET", "/api/paper/sessions"),
        ("GET", "/api/paper/sessions/{key}"),
        ("GET", "/api/reports"),
        ("GET", "/api/research/history"),
        ("GET", "/api/research/history/{history_id}"),
        ("GET", "/api/research/log"),
        ("GET", "/api/settings"),
        ("GET", "/api/settings/schema"),
        ("GET", "/api/status"),
        ("GET", "/api/strategies"),
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("PATCH", "/api/journal/{index}"),
        ("POST", "/api/catalog/ingest"),
        ("POST", "/api/catalog/ingest/cancel"),
        ("POST", "/api/ml/train"),
        ("POST", "/api/ml/train/cancel"),
        ("POST", "/api/paper/cancel"),
        ("POST", "/api/paper/live/close-position"),
        ("POST", "/api/paper/live/start"),
        ("POST", "/api/paper/live/stop"),
        ("POST", "/api/paper/live/update-stops"),
        ("POST", "/api/paper/run"),
        ("POST", "/api/paper/sessions"),
        ("POST", "/api/paper/sessions/{key}/close-position"),
        ("POST", "/api/paper/sessions/{key}/pause"),
        ("POST", "/api/paper/sessions/{key}/resume"),
        ("POST", "/api/paper/sessions/{key}/stop"),
        ("POST", "/api/paper/sessions/{key}/update-stops"),
        ("POST", "/api/propose"),
        ("POST", "/api/research"),
        ("POST", "/api/research/cancel"),
        ("POST", "/api/scan/triangular"),
        ("PUT", "/api/settings"),
        ("WS", "/api/paper/live-stream"),
    }
)


def _cfg(**overrides: Any) -> Settings:
    """Code defaults only: no `.env`, so the machine running the tests does not matter."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _served(app: Any) -> set[tuple[str, str]]:
    served: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, WebSocketRoute):
            served.add(("WS", route.path))
        elif isinstance(route, Route) and route.methods:
            served.update((method, route.path) for method in route.methods - {"HEAD"})
    return served


def test_every_route_survived_the_split_into_routers(tmp_path: Path) -> None:
    served = _served(create_app(_cfg(), root=tmp_path))
    assert ROUTES - served == set(), "routes lost"
    assert served - ROUTES == set(), "new route: add it to ROUTES"


def test_apps_do_not_share_job_slots(tmp_path: Path) -> None:
    first = create_app(_cfg(), root=tmp_path / "a")
    second = create_app(_cfg(), root=tmp_path / "b")
    assert first.state.lab.jobs.reserve("paper")
    assert not second.state.lab.jobs.active("paper")


def test_token_comes_from_the_settings_the_app_was_built_with(tmp_path: Path) -> None:
    client = TestClient(create_app(_cfg(api_token="s3cret"), root=tmp_path))
    assert client.get("/api/status").status_code == 403
    assert client.get("/api/status", headers={"X-Lab-Token": "s3cret"}).status_code == 200
    # Health stays reachable without the token: Docker and the uptime monitor call it.
    assert client.get("/healthz").status_code == 200


def test_paper_role_is_taken_from_settings(tmp_path: Path) -> None:
    client = TestClient(create_app(_cfg(lab_role="paper"), root=tmp_path))
    assert client.get("/api/status").json()["lab_role"] == "paper"
    refused = client.post("/api/research", json={"robot": "regime", "source": "synthetic"})
    assert refused.status_code == 403


def test_reports_and_logs_live_under_the_given_root(tmp_path: Path) -> None:
    launched: list[Any] = []
    jobs = JobManager(reports_dir=tmp_path / "reports", python="python", schedule=launched.append)
    client = TestClient(create_app(_cfg(), root=tmp_path, jobs=jobs))
    res = client.post("/api/catalog/ingest", json={"symbols": "ETHUSDT"})
    assert res.json()["status"] == "started"
    assert (tmp_path / "reports" / "ingest.log").exists()
    assert len(launched) == 1
    assert client.get("/api/catalog/ingest/log").json()["is_running"] is True
    assert client.get("/api/reports").json() == {"reports": []}


@pytest.mark.parametrize("job", ["research", "ingest", "ml_train", "paper"])
def test_cancel_without_a_process_is_idle(tmp_path: Path, job: str) -> None:
    path = {
        "research": "/api/research/cancel",
        "ingest": "/api/catalog/ingest/cancel",
        "ml_train": "/api/ml/train/cancel",
        "paper": "/api/paper/cancel",
    }[job]
    client = TestClient(create_app(_cfg(), root=tmp_path))
    assert client.post(path).json()["status"] == "idle"
