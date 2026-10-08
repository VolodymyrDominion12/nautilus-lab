from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.leaderboard import (
    LeaderboardEntry,
    load_leaderboard_entries,
    record_leaderboard_entry,
)
from nautilus_lab.interfaces.cli import main


def test_cli_leaderboard_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    md_file = tmp_path / "lb.md"
    jsonl_file = tmp_path / "lb.jsonl"
    monkeypatch.setenv("LEADERBOARD_PATH", str(md_file))
    monkeypatch.setenv("LEADERBOARD_JSONL_PATH", str(jsonl_file))

    code = main(["leaderboard"])
    assert code == 0
    captured = capsys.readouterr()
    assert "No leaderboard entries found" in captured.out


def test_cli_leaderboard_display_and_reproduce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    md_file = tmp_path / "lb.md"
    jsonl_file = tmp_path / "lb.jsonl"
    monkeypatch.setenv("LEADERBOARD_PATH", str(md_file))
    monkeypatch.setenv("LEADERBOARD_JSONL_PATH", str(jsonl_file))

    entry = LeaderboardEntry(
        id="test_top1",
        recorded_at=datetime.now(UTC),
        robot="regime",
        instrument_id="ETH/USDT.SIM",
        timeframe="1h",
        bar_count=3000,
        source="catalog",
        run_type="walk_forward",
        folds=4,
        oos_return=Decimal("0.0850"),
        buy_and_hold_return=Decimal("0.0320"),
        excess_return=Decimal("0.0530"),
        sharpe_ratio=Decimal("1.80"),
        max_drawdown=Decimal("0.0250"),
        fills=150,
        fees_paid=Decimal("20.00"),
        profitable_folds="4/4",
        ending_balance=Decimal("108500.00"),
        strategy_params={"donchian_period": 20, "bb_k": "2.0"},
        run_args={"starting_equity": "100000", "is_fraction": "0.7"},
        reproduce_command="uv run lab research --robot regime --folds 4 --instrument ETH/USDT.SIM",
    )
    record_leaderboard_entry(markdown_path=md_file, jsonl_path=jsonl_file, entry=entry)

    # 1. Table output
    code = main(["leaderboard"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Nautilus Lab Backtest Leaderboard" in out
    assert "regime" in out
    assert "ETH/USDT.SIM" in out
    assert "+8.50%" in out

    # 2. JSON output
    code_json = main(["leaderboard", "--json"])
    assert code_json == 0
    out_json = capsys.readouterr().out
    assert '"robot": "regime"' in out_json

    # 3. Reproduce flag
    code_rep = main(["leaderboard", "--reproduce", "1"])
    assert code_rep == 0
    out_rep = capsys.readouterr().out
    assert "Exact Reproduce Command:" in out_rep
    assert "uv run lab research --robot regime --folds 4 --instrument ETH/USDT.SIM" in out_rep
    assert "donchian_period = 20" in out_rep


def test_cli_research_with_leaderboard_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    md_file = tmp_path / "lb.md"
    jsonl_file = tmp_path / "lb.jsonl"
    monkeypatch.setenv("LEADERBOARD_PATH", str(md_file))
    monkeypatch.setenv("LEADERBOARD_JSONL_PATH", str(jsonl_file))

    # Run synthetic research with --leaderboard
    code = main(["research", "--synthetic", "--bars", "1200", "--folds", "2", "--leaderboard"])
    assert code == 0
    out = capsys.readouterr().out
    assert "leaderboard_recorded=" in out

    entries = load_leaderboard_entries(jsonl_file)
    assert len(entries) == 1
    assert entries[0].robot == "regime"
    assert entries[0].source == "synthetic"
    assert entries[0].folds == 2
    assert md_file.exists()
