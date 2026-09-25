"""The gate wired into the FastAPI app, end to end through TestClient."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import app, create_app
from nautilus_lab.infrastructure.settings import Settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_cross_site_settings_write_is_refused(client: TestClient) -> None:
    response = client.put(
        "/api/settings",
        json={"settings": {"LLM_BASE_URL": "https://evil.example/v1"}},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_dashboard_origin_reads_status(client: TestClient) -> None:
    response = client.get("/api/status", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_configured_token_is_enforced(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, api_token="s3cret")  # type: ignore[call-arg]
    client = TestClient(create_app(cfg, root=tmp_path))
    assert client.get("/api/status").status_code == 403
    assert client.get("/api/status", headers={"X-Lab-Token": "s3cret"}).status_code == 200


def test_live_stream_refuses_a_foreign_origin(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/api/paper/live-stream", headers={"Origin": "https://evil.example"}
        ) as socket,
    ):
        socket.receive_text()
