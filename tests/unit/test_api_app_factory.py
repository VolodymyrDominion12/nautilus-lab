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
from starlette.routing import WebSocketRoute

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
    """HTTP routes from the OpenAPI schema, WebSocket routes from the route tree.

    Newer FastAPI keeps an included router as one nested entry in `app.routes` instead of
    copying its routes up, so walking `app.routes` alone sees almost nothing. The schema is
    the public contract and lists every HTTP route however it was mounted; a WebSocket
    has no schema entry, so those are found by walking whatever nesting FastAPI uses.
    """
    served = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    served.update(("WS", path) for path in _websocket_paths(app.routes, set()))
    return served


def _websocket_paths(routes: Any, seen: set[int]) -> set[str]:
    found: set[str] = set()
    for route in routes or ():
        if id(route) in seen:
            continue
        seen.add(id(route))
        if isinstance(route, WebSocketRoute):
            found.add(route.path)
        for attr in ("routes", "original_router", "router", "original_route", "app"):
            child = getattr(route, attr, None)
            if child is None or child is route:
                continue
            nested = getattr(child, "routes", None) if attr != "routes" else child
            if nested is not None and not isinstance(nested, (str, bytes)):
                found |= _websocket_paths(nested, seen)
    return found


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
