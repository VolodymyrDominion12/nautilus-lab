"""Tests for the multi-window out-of-sample aggregate.

The aggregate is the part that a single split cannot give: how often the robot earned
money across folds, how far the folds disagree, and whether it beat simply holding the
instrument. These tests pin the arithmetic, including the cases where the answer must
be "unknown" rather than a guess.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from nautilus_lab.application.dtos import (
    BacktestReport,
    BacktestRequest,
    MultiWindowReport,
    WalkForwardFold,
    selected_from_request,
)
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.walk_forward import WalkForwardWindow

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 6, 1, tzinfo=UTC)


def _window() -> WalkForwardWindow:
    return WalkForwardWindow(
        in_sample_start=_START,
        in_sample_end=datetime(2024, 3, 1, tzinfo=UTC),
        out_of_sample_start=datetime(2024, 3, 1, tzinfo=UTC),
        out_of_sample_end=_END,
    )


def _fold(
    index: int,
    *,
    oos_return: Decimal | None,
    buy_and_hold: Decimal | None,
    fills: int = 10,
) -> WalkForwardFold:
    request = BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id="ETH/USDT.SIM",
        bar_count=100,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
    )
    return WalkForwardFold(
        index=index,
        selected=selected_from_request(request),
        candidates_tried=6,
        in_sample=BacktestReport(
            fills=fills, positions=0, ending_balance=Decimal("100000"), notes="is"
        ),
        out_of_sample=BacktestReport(
            fills=fills, positions=0, ending_balance=Decimal("100000"), notes="oos"
        ),
        window=_window(),
        oos_return=oos_return,
        buy_and_hold_return=buy_and_hold,
    )


def _report(folds: list[WalkForwardFold]) -> MultiWindowReport:
    return MultiWindowReport(
        folds=tuple(folds),
        starting_equity=Decimal("100000"),
        notes="test",
    )


def test_aggregate_counts_profitable_folds_and_spread() -> None:
    report = _report(
        [
            _fold(0, oos_return=Decimal("0.06"), buy_and_hold=Decimal("-0.17"), fills=163),
            _fold(1, oos_return=Decimal("-0.01"), buy_and_hold=Decimal("0.04"), fills=69),
            _fold(2, oos_return=Decimal("-0.06"), buy_and_hold=Decimal("-0.29"), fills=53),
            _fold(3, oos_return=Decimal("0.04"), buy_and_hold=Decimal("0.53"), fills=56),
        ]
    )

    assert report.profitable_folds == 2
    assert report.mean_oos_return == Decimal("0.0075")
    assert report.median_oos_return == Decimal("0.015")
    assert report.worst_oos_return == Decimal("-0.06")
    assert report.best_oos_return == Decimal("0.06")
    assert report.total_oos_fills == 341


def test_aggregate_compares_against_buy_and_hold() -> None:
    better = _report(
        [
            _fold(0, oos_return=Decimal("0.10"), buy_and_hold=Decimal("0.01")),
            _fold(1, oos_return=Decimal("0.08"), buy_and_hold=Decimal("0.02")),
        ]
    )
    worse = _report(
        [
            _fold(0, oos_return=Decimal("0.01"), buy_and_hold=Decimal("0.10")),
            _fold(1, oos_return=Decimal("-0.02"), buy_and_hold=Decimal("0.08")),
        ]
    )

    assert better.beats_buy_and_hold() is True
    assert worse.beats_buy_and_hold() is False


def test_verdict_is_unknown_without_measurable_returns() -> None:
    """Never claim a verdict that the data cannot support."""
    report = _report([_fold(0, oos_return=None, buy_and_hold=None)])

    assert report.oos_returns == ()
    assert report.mean_oos_return is None
    assert report.median_oos_return is None
    assert report.worst_oos_return is None
    assert report.best_oos_return is None
    assert report.beats_buy_and_hold() is None
    assert "n/a" in report.summary_line()


def test_summary_line_states_the_comparison() -> None:
    report = _report(
        [
            _fold(0, oos_return=Decimal("0.01"), buy_and_hold=Decimal("0.53")),
            _fold(1, oos_return=Decimal("-0.05"), buy_and_hold=Decimal("-0.29")),
        ]
    )

    line = report.summary_line()
    assert "folds=2" in line
    assert "profitable=1/2" in line
    assert "does not beat buy&hold" in line
