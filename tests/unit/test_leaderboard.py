from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.dtos import SelectedParams
from nautilus_lab.application.leaderboard import (
    LEADERBOARD_ROWS_END,
    LEADERBOARD_ROWS_START,
    LeaderboardEntry,
    build_reproduce_command,
    load_leaderboard_entries,
    rank_leaderboard_entries,
    record_leaderboard_entry,
    strategy_params_for_robot,
)
from nautilus_lab.domain.provenance import RunManifest


def test_leaderboard_entry_roundtrip() -> None:
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    prov = RunManifest(code_revision="abc1234", nautilus_version="1.231.0")
    entry = LeaderboardEntry(
        id="test_01",
        recorded_at=now,
        robot="regime",
        instrument_id="ETH/USDT.SIM",
        timeframe="1h",
        bar_count=3000,
        source="catalog",
        run_type="walk_forward",
        folds=4,
        oos_return=Decimal("0.0450"),
        buy_and_hold_return=Decimal("0.0210"),
        excess_return=Decimal("0.0240"),
        sharpe_ratio=Decimal("1.25"),
        max_drawdown=Decimal("0.0420"),
        fills=142,
        fees_paid=Decimal("38.50"),
        profitable_folds="3/4",
        ending_balance=Decimal("104500.00"),
        strategy_params={"fast_ema": 10, "slow_ema": 20, "donchian_period": 20, "bb_k": "2.0"},
        run_args={"starting_equity": "100000", "is_fraction": "0.7", "embargo_bars": 10},
        reproduce_command="uv run lab research --robot regime --folds 4",
        provenance=prov,
        notes="sample run",
    )

    data = entry.as_dict()
    assert data["id"] == "test_01"
    assert data["oos_return"] == "0.0450"
    assert data["buy_and_hold_return"] == "0.0210"
    assert data["excess_return"] == "0.0240"
    assert data["fills"] == 142
    assert data["profitable_folds"] == "3/4"

    rebuilt = LeaderboardEntry.from_dict(data)
    assert rebuilt.id == entry.id
    assert rebuilt.robot == entry.robot
    assert rebuilt.instrument_id == entry.instrument_id
    assert rebuilt.timeframe == entry.timeframe
    assert rebuilt.bar_count == entry.bar_count
    assert rebuilt.oos_return == entry.oos_return
    assert rebuilt.buy_and_hold_return == entry.buy_and_hold_return
    assert rebuilt.excess_return == entry.excess_return
    assert rebuilt.fills == entry.fills
    assert rebuilt.provenance is not None
    assert rebuilt.provenance.code_revision == "abc1234"


def test_format_params_and_markdown_row() -> None:
    entry = LeaderboardEntry(
        id="test_02",
        recorded_at=datetime.now(UTC),
        robot="ema",
        instrument_id="BTCUSDT.SIM",
        timeframe="1h",
        bar_count=2000,
        source="catalog",
        run_type="walk_forward",
        folds=1,
        oos_return=Decimal("-0.0120"),
        buy_and_hold_return=Decimal("0.0150"),
        excess_return=Decimal("-0.0270"),
        sharpe_ratio=Decimal("-0.30"),
        max_drawdown=Decimal("0.0550"),
        fills=80,
        fees_paid=Decimal("15.20"),
        profitable_folds="0/1",
        ending_balance=Decimal("98800.00"),
        strategy_params={"fast_ema": 12, "slow_ema": 26},
        run_args={},
        reproduce_command="uv run lab research --robot ema",
    )
    summary = entry.format_params_summary()
    assert "fast_ema=12" in summary
    assert "slow_ema=26" in summary

    row = entry.markdown_row(rank=1)
    assert "| 1 | `ema` | `BTCUSDT.SIM` | `1h` | 2000 |" in row
    assert "-1.20%" in row
    assert "+1.50%" in row
    assert "`uv run lab research --robot ema`" in row


def test_build_reproduce_command() -> None:
    cmd_synth = build_reproduce_command(
        robot="regime",
        instrument_id="SYNTHETIC",
        timeframe="1m",
        bar_count=5000,
        folds=4,
        source="synthetic",
        strategy_params={"bb_k": 2.5, "donchian_period": 30},
        run_args={
            "is_fraction": "0.6",
            "embargo_bars": 15,
            "use_optuna": True,
            "optuna_trials": 30,
        },
    )
    assert "BB_K=2.5" in cmd_synth
    assert "DONCHIAN_PERIOD=30" in cmd_synth
    assert "uv run lab research --robot regime --synthetic --bars 5000 --folds 4" in cmd_synth
    assert "--optuna --trials 30" in cmd_synth
    assert "--is-fraction 0.6" in cmd_synth
    assert "--embargo-bars 15" in cmd_synth

    cmd_cat = build_reproduce_command(
        robot="ema",
        instrument_id="ETH/USDT.SIM",
        timeframe="4h",
        bar_count=3000,
        folds=2,
        source="catalog",
        catalog_path="custom_cat",
        strategy_params={"fast_ema": 12, "slow_ema": 26},
        run_args={"stress_slice": "covid2020"},
    )
    assert "FAST_EMA=12" in cmd_cat
    assert "SLOW_EMA=26" in cmd_cat
    assert "--catalog custom_cat" in cmd_cat
    assert "--instrument ETH/USDT.SIM" in cmd_cat
    assert "--interval 4h" in cmd_cat
    assert "--slice covid2020" in cmd_cat


def test_rank_leaderboard_entries() -> None:
    now = datetime.now(UTC)
    e1 = LeaderboardEntry(
        id="1",
        recorded_at=now,
        robot="regime",
        instrument_id="ETH",
        timeframe="1h",
        bar_count=1000,
        source="catalog",
        run_type="walk_forward",
        folds=2,
        oos_return=Decimal("0.05"),
        buy_and_hold_return=Decimal("0.02"),
        excess_return=Decimal("0.03"),
        sharpe_ratio=Decimal("1.1"),
        max_drawdown=Decimal("0.04"),
        fills=100,
        fees_paid=None,
        profitable_folds=None,
        ending_balance=None,
        strategy_params={},
        run_args={},
        reproduce_command="cmd1",
    )
    e2 = LeaderboardEntry(
        id="2",
        recorded_at=now,
        robot="ema",
        instrument_id="BTC",
        timeframe="1h",
        bar_count=1000,
        source="catalog",
        run_type="walk_forward",
        folds=2,
        oos_return=Decimal("0.10"),
        buy_and_hold_return=Decimal("0.12"),
        excess_return=Decimal("-0.02"),
        sharpe_ratio=Decimal("0.9"),
        max_drawdown=Decimal("0.08"),
        fills=50,
        fees_paid=None,
        profitable_folds=None,
        ending_balance=None,
        strategy_params={},
        run_args={},
        reproduce_command="cmd2",
    )

    by_oos = rank_leaderboard_entries([e1, e2], sort_by="oos")
    assert by_oos[0].id == "2"  # 10% > 5%

    by_excess = rank_leaderboard_entries([e1, e2], sort_by="excess")
    assert by_excess[0].id == "1"  # +3% > -2%

    by_sharpe = rank_leaderboard_entries([e1, e2], sort_by="sharpe")
    assert by_sharpe[0].id == "1"  # 1.1 > 0.9

    by_drawdown = rank_leaderboard_entries([e1, e2], sort_by="drawdown")
    assert by_drawdown[0].id == "1"  # 4% dd is better than 8% dd


def test_file_persistence_and_markdown_generation(tmp_path: Path) -> None:
    md_file = tmp_path / "leaderboard.md"
    jsonl_file = tmp_path / "leaderboard.jsonl"

    e1 = LeaderboardEntry(
        id="e1",
        recorded_at=datetime.now(UTC),
        robot="regime",
        instrument_id="ETH/USDT.SIM",
        timeframe="1h",
        bar_count=3000,
        source="catalog",
        run_type="multi_window",
        folds=4,
        oos_return=Decimal("0.035"),
        buy_and_hold_return=Decimal("0.010"),
        excess_return=Decimal("0.025"),
        sharpe_ratio=Decimal("1.2"),
        max_drawdown=Decimal("0.03"),
        fills=120,
        fees_paid=Decimal("25"),
        profitable_folds="3/4",
        ending_balance=Decimal("103500"),
        strategy_params={"fast_ema": 10, "slow_ema": 20},
        run_args={"starting_equity": "100000"},
        reproduce_command="uv run lab research --robot regime --folds 4",
    )

    record_leaderboard_entry(markdown_path=md_file, jsonl_path=jsonl_file, entry=e1)

    assert jsonl_file.exists()
    assert md_file.exists()

    loaded = load_leaderboard_entries(jsonl_file)
    assert len(loaded) == 1
    assert loaded[0].id == "e1"

    md_content = md_file.read_text(encoding="utf-8")
    assert LEADERBOARD_ROWS_START in md_content
    assert LEADERBOARD_ROWS_END in md_content
    assert "regime" in md_content
    assert "ETH/USDT.SIM" in md_content
    assert "+3.50%" in md_content
    assert "+2.50%" in md_content


def test_strategy_params_for_robot() -> None:
    sel = SelectedParams(
        fast_ema=12,
        slow_ema=26,
        donchian_period=40,
        bb_period=20,
        bb_k=Decimal("2.5"),
        enter_trend_er=Decimal("0.35"),
        exit_trend_er=Decimal("0.25"),
    )
    p_regime = strategy_params_for_robot("regime", selected=sel)
    assert p_regime["donchian_period"] == 40
    assert p_regime["bb_k"] == "2.5"

    p_ema = strategy_params_for_robot("ema", selected=sel)
    assert p_ema["fast_ema"] == 12
    assert p_ema["slow_ema"] == 26
    assert "donchian_period" not in p_ema
