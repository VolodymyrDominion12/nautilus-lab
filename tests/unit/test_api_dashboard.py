from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.api.research_runner import summary_from_result
from nautilus_lab.api.serializers import build_job_result, pct, serialize_backtest
from nautilus_lab.api.settings_schema import validate_settings_update
from nautilus_lab.application.dtos import (
    BacktestReport,
    MultiWindowReport,
    SelectedParams,
    WalkForwardFold,
)
from nautilus_lab.domain.metrics import BacktestMetrics
from nautilus_lab.domain.walk_forward import WalkForwardWindow


def test_pct_formats_signed_percent() -> None:
    assert pct(Decimal("0.0123")) == "+1.23%"
    assert pct(Decimal("-0.05")) == "-5.00%"
    assert pct(None) == "n/a"


def test_serialize_backtest_includes_metrics() -> None:
    report = BacktestReport(
        fills=3,
        positions=2,
        ending_balance=Decimal("101000"),
        notes="test",
        metrics=BacktestMetrics(
            fees_paid=Decimal("12.5"),
            max_drawdown=Decimal("0.04"),
            turnover=Decimal("5000"),
            sharpe_like=Decimal("1.25"),
        ),
    )
    payload = serialize_backtest(report)
    assert payload["fills"] == 3
    assert payload["sharpe"] == 1.25
    assert payload["max_dd_pct"] == "4.00%"


def test_validate_settings_update_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="Unknown setting key"):
        validate_settings_update({"NOT_A_REAL_SETTING": "1"})


def test_validate_settings_update_normalizes_case() -> None:
    validated = validate_settings_update({"robot": "regime", "RISK_PER_TRADE": "0.01"})
    assert validated["ROBOT"] == "regime"
    assert validated["RISK_PER_TRADE"] == "0.01"


def test_summary_from_structured_multi_window() -> None:
    window = WalkForwardWindow(
        in_sample_start=datetime(2024, 1, 1, tzinfo=UTC),
        in_sample_end=datetime(2024, 6, 1, tzinfo=UTC),
        out_of_sample_start=datetime(2024, 6, 1, tzinfo=UTC),
        out_of_sample_end=datetime(2024, 7, 1, tzinfo=UTC),
    )
    fold = WalkForwardFold(
        index=0,
        selected=SelectedParams(
            fast_ema=10,
            slow_ema=20,
            donchian_period=20,
            bb_period=20,
            bb_k=Decimal("2"),
            enter_trend_er=Decimal("0.3"),
            exit_trend_er=Decimal("0.2"),
        ),
        candidates_tried=4,
        in_sample=BacktestReport(1, 1, Decimal("100"), "is"),
        out_of_sample=BacktestReport(2, 1, Decimal("101"), "oos"),
        window=window,
        oos_return=Decimal("0.01"),
        buy_and_hold_return=Decimal("0.005"),
    )
    multi = MultiWindowReport(
        folds=(fold,),
        starting_equity=Decimal("100000"),
        notes="notes",
    )
    result = build_job_result(
        run_type="multi_window",
        robot="regime",
        source="catalog",
        multi_window=multi,
    )
    summary = summary_from_result(result)
    assert summary["multi_window"]["profitable"] == "1/1"
    assert summary["multi_window"]["beats_buy_and_hold"] is True
