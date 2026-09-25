"""The browser smoke test's server, checked without a browser (docs/27 E-2.4).

`scripts/e2e_server.py` is what Playwright runs against. If its synthetic market stops
fitting the session code, for example a warm-up the robot rejects or a kline the
parser no longer reads, this file fails in `pytest` with a precise message. Without it
the only symptom would be a browser test waiting on "Stream Active".
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import time
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.paper_streamer import WARMUP_BARS, parse_kline_message

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = "http://127.0.0.1:4173"


def _server() -> ModuleType:
    spec = importlib.util.spec_from_file_location("e2e_server", ROOT / "scripts" / "e2e_server.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_stream_continues_the_history_and_stays_in_the_past() -> None:
    now = time.time()
    market = _server().SyntheticMarket("BTCUSDT", now=now)
    assert len(market.history) == WARMUP_BARS
    last = market.history[-1].ts_utc
    assert market.live[-1].ts_utc.timestamp() <= now, "no bar may come from the future"
    steps = {b.ts_utc - a.ts_utc for a, b in zip(market.history, market.history[1:], strict=False)}
    assert steps == {timedelta(minutes=1)}
    assert market.live[0].ts_utc == last + timedelta(minutes=1)


def test_a_synthetic_kline_reads_back_as_the_same_closed_bar() -> None:
    server = _server()
    bar = server.SyntheticMarket("ETHUSDT", now=time.time()).live[0]
    update = parse_kline_message(server.kline_message(bar))
    assert update is not None
    assert update["time_sec"] == int(bar.ts_utc.timestamp())
    assert update["close_price"] == bar.close
    assert update["is_closed"] is True


def test_only_one_minute_bars_are_served() -> None:
    markets = _server().SyntheticMarkets()
    assert len(asyncio.run(markets.history("BTCUSDT", "1m", 50))) == 50
    with pytest.raises(ValueError, match="1m"):
        asyncio.run(markets.history("BTCUSDT", "1h", 50))


@pytest.fixture
def client(tmp_path: Path) -> Any:
    app = _server().build_app(origins=DASHBOARD, workdir=tmp_path, tick_seconds=0.02)
    with TestClient(app) as test_client:
        yield test_client


def _wait_for(check: Any, timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    pytest.fail(f"condition not met within {timeout}s")


def test_the_dashboard_origin_is_allowed_and_others_are_not(client: TestClient) -> None:
    assert client.get("/api/status", headers={"Origin": DASHBOARD}).status_code == 200
    refused = client.get("/api/status", headers={"Origin": "http://evil.example"})
    assert refused.status_code == 403


def test_a_session_warms_up_trades_live_bars_and_streams(client: TestClient) -> None:
    started = client.post(
        "/api/paper/sessions", json={"symbol": "BTCUSDT", "interval": "1m", "name": "e2e"}
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]

    def state() -> dict[str, Any]:
        reply = client.get(f"/api/paper/sessions/{session_id}")
        assert reply.status_code == 200
        body: dict[str, Any] = reply.json()
        return body

    warmed = _wait_for(lambda: state()["last_bar_ts"])
    # Live closed bars from the synthetic feed move the session past its warm-up.
    _wait_for(lambda: (state()["last_bar_ts"] or "") > warmed)
    assert state()["is_active"] is True

    listed = client.get("/api/paper/sessions").json()["sessions"]
    assert [row["name"] for row in listed] == ["e2e"]

    with client.websocket_connect(
        f"/api/paper/live-stream?session={session_id}", headers={"Origin": DASHBOARD}
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "INIT_STATE"
        assert first["data"]["name"] == "e2e"
        ws.send_text("ping")
        # Bar and state broadcasts may arrive before the pong; any text reply is fine.
        assert ws.receive_text()

    assert client.post(f"/api/paper/sessions/{session_id}/stop").status_code == 200
