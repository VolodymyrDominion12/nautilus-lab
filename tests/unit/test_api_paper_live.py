from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import app
from nautilus_lab.api.paper_streamer import LIVE_PAPER_SESSION


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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

    # Verify session state updated
    assert LIVE_PAPER_SESSION.is_active
    assert LIVE_PAPER_SESSION.config.symbol == "ETHUSDT"
    assert LIVE_PAPER_SESSION.starting_equity == Decimal("25000")

    # Stop session
    stop_res = client.post("/api/paper/live/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "stopped"
    assert not LIVE_PAPER_SESSION.is_active


def test_api_paper_live_close_and_update_stops(client: TestClient) -> None:
    # 1. Start a session
    client.post("/api/paper/live/start", json={"symbol": "BTCUSDT", "starting_equity": "10000"})

    # 2. Simulate opening a position directly
    LIVE_PAPER_SESSION._open_position_internal("LONG", Decimal("65000"))
    assert LIVE_PAPER_SESSION.position is not None

    # 3. Update stops
    update_res = client.post(
        "/api/paper/live/update-stops",
        json={"stop_loss": "64000", "take_profit": "68000"},
    )
    assert update_res.status_code == 200
    assert LIVE_PAPER_SESSION.position.stop_loss == "64000"
    assert LIVE_PAPER_SESSION.position.take_profit == "68000"

    # 4. Manual close
    close_res = client.post("/api/paper/live/close-position")
    assert close_res.status_code == 200
    assert LIVE_PAPER_SESSION.position is None

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
