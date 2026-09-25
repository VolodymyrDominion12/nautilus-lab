"""The dashboard's Decision Logs tab reads what the session actually wrote.

On the VPS (2026-09-25) the tab was empty while `data/paper/decisions/` filled up at every
bar close: the route looked the log up by `config.name` ("ema-eth") while the writer files by
session id ("ema-eth-159a09"). These tests pin the shared key, end to end over HTTP, with no
network: the session is registered the way `SessionRegistry.create` registers it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from nautilus_lab.api.app import create_app
from nautilus_lab.api.paper_streamer import LivePaperConfig, LivePaperSessionManager
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.infrastructure.settings import Settings


def _cfg(**overrides: Any) -> Settings:
    """Code defaults plus decision logging on: the test does not read the machine's `.env`."""
    values: dict[str, Any] = {
        "decision_log_enabled": True,
        "decision_log_dir": "data/paper/decisions",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _register(app: Any, *, robot: str, symbol: str, name: str, session_id: str) -> Any:
    """A session as the registry holds it, without starting a stream or warming up."""
    registry = app.state.lab.sessions
    manager = LivePaperSessionManager(
        LivePaperConfig(robot=robot, symbol=symbol, name=name),
        decision_log=registry.decision_log_writer,
    )
    manager.session_id = session_id
    registry.sessions[session_id] = manager
    return manager


def _bar(ts: datetime, instrument_id: str = "ETHUSDT") -> OhlcvBar:
    return OhlcvBar(
        instrument_id=instrument_id,
        ts_utc=ts,
        open=Decimal("2680"),
        high=Decimal("2690"),
        low=Decimal("2670"),
        close=Decimal("2685.91"),
        volume=Decimal("10"),
    )


def test_decision_log_route_returns_the_session_s_own_records(tmp_path: Path) -> None:
    app = create_app(_cfg(), root=tmp_path)
    manager = _register(
        app, robot="ema", symbol="ETHUSDT", name="ema-eth", session_id="ema-eth-159a09"
    )
    manager._record_decision_log(_bar(datetime(2026, 9, 25, 16, 0, tzinfo=UTC)), None)

    client = TestClient(app)
    res = client.get("/api/paper/sessions/ema-eth-159a09/decision-log")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert (tmp_path / "data/paper/decisions/ema-eth-159a09_2026-09-25.jsonl").is_file()
    assert [row["session_id"] for row in body["logs"]] == ["ema-eth-159a09"]
    assert body["logs"][0]["robot"] == "ema"
    assert body["logs"][0]["instrument"] == "ETHUSDT"
    assert body["logs"][0]["ts"].startswith("2026-09-25T16:00")
    assert body["logs"][0]["close"] == "2685.91"


def test_decision_log_route_does_not_show_another_session_s_decisions(tmp_path: Path) -> None:
    """Two sessions of one robot: each must see only its own bar decisions."""
    app = create_app(_cfg(), root=tmp_path)
    btc = _register(
        app, robot="hold", symbol="BTCUSDT", name="hold-btc", session_id="hold-btc-5d65f4"
    )
    eth = _register(
        app, robot="hold", symbol="ETHUSDT", name="hold-eth", session_id="hold-eth-4d1f08"
    )
    ts = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)
    btc._record_decision_log(_bar(ts, "BTCUSDT"), None)
    eth._record_decision_log(_bar(ts, "ETHUSDT"), None)

    client = TestClient(app)
    btc_logs = client.get("/api/paper/sessions/hold-btc-5d65f4/decision-log").json()["logs"]
    eth_logs = client.get("/api/paper/sessions/hold-eth-4d1f08/decision-log").json()["logs"]

    assert [row["instrument"] for row in btc_logs] == ["BTCUSDT"]
    assert [row["instrument"] for row in eth_logs] == ["ETHUSDT"]


def test_decision_log_route_reports_a_session_that_has_no_id_yet(tmp_path: Path) -> None:
    """No id means no key: say so instead of answering "ok" with an empty list."""
    app = create_app(_cfg(), root=tmp_path)
    registry = app.state.lab.sessions
    manager = LivePaperSessionManager(
        LivePaperConfig(robot="ema", symbol="ETHUSDT", name="ema-eth"),
        decision_log=registry.decision_log_writer,
    )
    manager.session_id = None
    registry.sessions["unstarted"] = manager

    client = TestClient(app)
    body = client.get("/api/paper/sessions/unstarted/decision-log").json()

    assert body["status"] == "error"
    assert "session id" in body["message"]
    assert body["logs"] == []


def test_decision_log_route_reports_logging_being_off(tmp_path: Path) -> None:
    app = create_app(_cfg(decision_log_enabled=False), root=tmp_path)
    _register(app, robot="ema", symbol="ETHUSDT", name="ema-eth", session_id="ema-eth-159a09")

    client = TestClient(app)
    body = client.get("/api/paper/sessions/ema-eth-159a09/decision-log").json()

    assert body["status"] == "error"
    assert "disabled" in body["message"]
    assert body["logs"] == []
