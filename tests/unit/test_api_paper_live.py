from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import LIVE_SESSIONS, app
from nautilus_lab.api.paper_streamer import LivePaperSessionManager


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _session(session_id: str) -> LivePaperSessionManager:
    manager = LIVE_SESSIONS.find(session_id)
    assert manager is not None
    return manager


def test_api_paper_live_state(client: TestClient) -> None:
    res = client.get("/api/paper/live/state")
    assert res.status_code == 200
    data = res.json()
    assert "is_active" in data
    assert "current_equity" in data
    assert "config" in data
    assert "fills" in data
    assert "recent_bars" in data


def test_api_paper_live_start_and_stop(client: TestClient) -> None:
    payload = {
        "symbol": "ETHUSDT",
        "interval": "5m",
        "robot": "regime",
        "starting_equity": "25000",
        "risk_per_trade": "0.01",
        "stop_pct": "0.02",
        "take_profit_multiple": "2.0",
        "mode": "paper",
        "auto_trade": True,
    }
    start_res = client.post("/api/paper/live/start", json=payload)
    assert start_res.status_code == 200
    assert start_res.json()["status"] == "started"
    session = _session(start_res.json()["session_id"])

    # Verify session state updated
    assert session.is_active
    assert session.config.symbol == "ETHUSDT"
    assert session.starting_equity == Decimal("25000")

    # Stop session
    stop_res = client.post("/api/paper/live/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "stopped"
    assert not session.is_active


def test_api_paper_live_close_and_update_stops(client: TestClient) -> None:
    # 1. Start a session
    started = client.post(
        "/api/paper/live/start", json={"symbol": "BTCUSDT", "starting_equity": "10000"}
    )
    session = _session(started.json()["session_id"])

    # 2. Simulate opening a position directly
    session._open_position_internal("LONG", Decimal("65000"))
    assert session.position is not None

    # 3. Update stops
    update_res = client.post(
        "/api/paper/live/update-stops",
        json={"stop_loss": "64000", "take_profit": "68000"},
    )
    assert update_res.status_code == 200
    assert session.position.stop_loss == "64000"
    assert session.position.take_profit == "68000"

    # 4. Manual close
    close_res = client.post("/api/paper/live/close-position")
    assert close_res.status_code == 200
    assert session.position is None

    # Clean up
    client.post("/api/paper/live/stop")


def test_api_paper_live_websocket(client: TestClient) -> None:
    with client.websocket_connect("/api/paper/live-stream") as ws:
        # First message should be INIT_STATE
        init_raw = ws.receive_text()
        init_msg = json.loads(init_raw)
        assert init_msg["type"] == "INIT_STATE"
        assert "data" in init_msg
        assert "current_equity" in init_msg["data"]

        # Send ping
        ws.send_text("ping")
        resp = ws.receive_text()
        assert resp == "pong"


def test_api_paper_sessions_create_list_pause_stop(client: TestClient) -> None:
    created = client.post(
        "/api/paper/sessions",
        json={"name": "api-test-hold", "robot": "hold", "symbol": "ETHUSDT", "interval": "1h"},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    duplicate = client.post(
        "/api/paper/sessions", json={"name": "api-test-hold", "robot": "ema", "interval": "1h"}
    )
    assert duplicate.status_code == 400

    listing = client.get("/api/paper/sessions").json()
    names = [row["name"] for row in listing["sessions"]]
    assert "api-test-hold" in names
    assert "portfolio" in listing

    assert client.post("/api/paper/sessions/api-test-hold/pause").json()["status"] == "paused"
    assert client.get(f"/api/paper/sessions/{session_id}").json()["paused"] is True
    assert client.post("/api/paper/sessions/api-test-hold/resume").json()["status"] == "active"
    assert client.post("/api/paper/sessions/api-test-hold/stop").json()["status"] == "stopped"
    assert client.get("/api/paper/sessions/no-such-session").status_code == 404
