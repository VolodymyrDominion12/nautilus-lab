from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from nautilus_lab.api.app import create_app
from nautilus_lab.application.leaderboard import LeaderboardEntry, record_leaderboard_entry
from nautilus_lab.infrastructure.settings import Settings


def test_api_leaderboard_empty(tmp_path: Path) -> None:
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        leaderboard_path=str(tmp_path / "lb.md"),
        leaderboard_jsonl_path=str(tmp_path / "lb.jsonl"),
    )
    app = create_app(cfg, root=tmp_path)
    client = TestClient(app)

    resp = client.get("/api/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["total"] == 0


def test_api_leaderboard_queries_and_sync(tmp_path: Path) -> None:
    md_file = tmp_path / "lb.md"
    jsonl_file = tmp_path / "lb.jsonl"
    cfg = Settings(
        _env_file=None,  # type: ignore[call-arg]
        leaderboard_path=str(md_file),
        leaderboard_jsonl_path=str(jsonl_file),
    )

    e1 = LeaderboardEntry(
        id="e1",
        recorded_at=datetime.now(UTC),
        robot="regime",
        instrument_id="ETH/USDT.SIM",
        timeframe="1h",
        bar_count=3000,
        source="catalog",
        run_type="walk_forward",
        folds=4,
        oos_return=Decimal("0.0520"),
        buy_and_hold_return=Decimal("0.0210"),
        excess_return=Decimal("0.0310"),
        sharpe_ratio=Decimal("1.40"),
        max_drawdown=Decimal("0.0350"),
        fills=130,
        fees_paid=Decimal("30"),
        profitable_folds="3/4",
        ending_balance=Decimal("105200"),
        strategy_params={"fast_ema": 10, "slow_ema": 20},
        run_args={"is_fraction": "0.7"},
        reproduce_command="uv run lab research --robot regime --folds 4",
    )
    e2 = LeaderboardEntry(
        id="e2",
        recorded_at=datetime.now(UTC),
        robot="ema",
        instrument_id="BTCUSDT.SIM",
        timeframe="4h",
        bar_count=2000,
        source="catalog",
        run_type="walk_forward",
        folds=2,
        oos_return=Decimal("0.0120"),
        buy_and_hold_return=Decimal("0.0400"),
        excess_return=Decimal("-0.0280"),
        sharpe_ratio=Decimal("0.50"),
        max_drawdown=Decimal("0.0600"),
        fills=45,
        fees_paid=Decimal("10"),
        profitable_folds="1/2",
        ending_balance=Decimal("101200"),
        strategy_params={"fast_ema": 12, "slow_ema": 26},
        run_args={"is_fraction": "0.7"},
        reproduce_command="uv run lab research --robot ema --folds 2",
    )

    record_leaderboard_entry(markdown_path=md_file, jsonl_path=jsonl_file, entry=e1)
    record_leaderboard_entry(markdown_path=md_file, jsonl_path=jsonl_file, entry=e2)

    app = create_app(cfg, root=tmp_path)
    client = TestClient(app)

    # 1. Get all
    resp = client.get("/api/leaderboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["entries"]) == 2
    assert data["entries"][0]["id"] == "e1"  # 5.2% > 1.2%

    # 2. Filter by robot
    resp_ema = client.get("/api/leaderboard?robot=ema")
    assert resp_ema.status_code == 200
    data_ema = resp_ema.json()
    assert len(data_ema["entries"]) == 1
    assert data_ema["entries"][0]["robot"] == "ema"

    # 3. Filter by instrument
    resp_eth = client.get("/api/leaderboard?instrument=ETH")
    assert resp_eth.status_code == 200
    assert len(resp_eth.json()["entries"]) == 1
    assert resp_eth.json()["entries"][0]["id"] == "e1"

    # 4. Get specific entry
    resp_single = client.get("/api/leaderboard/e1")
    assert resp_single.status_code == 200
    assert resp_single.json()["reproduce_command"] == "uv run lab research --robot regime --folds 4"

    # 5. Get missing entry
    resp_missing = client.get("/api/leaderboard/nonexistent")
    assert resp_missing.status_code == 404

    # 6. Sync route
    resp_sync = client.post("/api/leaderboard/sync")
    assert resp_sync.status_code == 200
    assert resp_sync.json()["status"] == "ok"
