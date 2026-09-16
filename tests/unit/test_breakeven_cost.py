"""Breakeven-cost: how much cost a run could absorb before PnL hits zero.

Source of the idea: the Transformer-vs-SSM review in the repo root, §3.2/§3.5
(breakeven transaction-cost analysis in arXiv:2603.01820), mapped in
docs/18-transformery-ssm-vidpovidnist.md. These tests pin the two things that
make the number trustworthy: the base is a TWO-SIDED notional from the engine's fills
report (not the strategy's entry-only `turnover`), and "nothing to measure" is None
rather than a confident zero.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from nautilus_lab.application.dtos import (
    BacktestReport,
    MultiWindowReport,
    SelectedParams,
    WalkForwardFold,
)
from nautilus_lab.domain.metrics import (
    BacktestMetrics,
    breakeven_cost,
    compute_metrics,
)
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.nautilus.backtest_runner import _traded_notional


def test_zero_net_pnl_returns_the_paid_rate() -> None:
    # A run that breaks exactly even must report c* == what it actually paid:
    # gross = net + fees = fees, so c* = fees / notional.
    rate = breakeven_cost(
        net_pnl=Decimal("0"),
        fees_paid=Decimal("50"),
        traded_notional=Decimal("100000"),
    )
    assert rate == Decimal("0.0005")


def test_losing_run_gets_a_negative_breakeven() -> None:
    # Lost 200 after paying 50 in fees: even free execution keeps it negative.
    rate = breakeven_cost(
        net_pnl=Decimal("-200"),
        fees_paid=Decimal("50"),
        traded_notional=Decimal("100000"),
    )
    assert rate == Decimal("-0.0015")


def test_no_notional_means_no_number() -> None:
    assert (
        breakeven_cost(
            net_pnl=Decimal("10"),
            fees_paid=Decimal("1"),
            traded_notional=Decimal("0"),
        )
        is None
    )
    assert (
        breakeven_cost(
            net_pnl=None,
            fees_paid=Decimal("1"),
            traded_notional=Decimal("500"),
        )
        is None
    )


def test_paid_cost_rate_is_the_comparison_point() -> None:
    metrics = BacktestMetrics(
        fees_paid=Decimal("40"),
        max_drawdown=Decimal("0.02"),
        turnover=Decimal("1000"),
        sharpe_like=None,
        traded_notional=Decimal("80000"),
        breakeven_cost=Decimal("0.001"),
    )
    assert metrics.paid_cost_rate == Decimal("0.0005")
    assert (
        BacktestMetrics(
            fees_paid=Decimal("0"),
            max_drawdown=Decimal("0"),
            turnover=Decimal("0"),
            sharpe_like=None,
        ).paid_cost_rate
        is None
    )


def test_compute_metrics_wires_notional_and_ending_equity() -> None:
    metrics = compute_metrics(
        starting_equity=Decimal("100000"),
        equity_curve=(Decimal("100000"), Decimal("99000")),
        fees_paid=Decimal("100"),
        turnover=Decimal("50000"),
        traded_notional=Decimal("200000"),
        ending_equity=Decimal("99000"),
    )
    # net = -1000, gross = -1000 + 100 = -900 -> c* = -900 / 200000
    assert metrics.breakeven_cost == Decimal("-0.0045")
    assert metrics.traded_notional == Decimal("200000")


def test_compute_metrics_without_engine_numbers_stays_undefined() -> None:
    metrics = compute_metrics(
        starting_equity=Decimal("100000"),
        equity_curve=(),
        fees_paid=Decimal("0"),
        turnover=Decimal("0"),
    )
    assert metrics.traded_notional == Decimal("0")
    assert metrics.breakeven_cost is None


def test_traded_notional_counts_both_sides() -> None:
    # `turnover` in the strategy counts entries only; breakeven must not be built on it.
    fills = pd.DataFrame(
        {
            "avg_px": [Decimal("100"), Decimal("110"), Decimal("200")],
            "filled_qty": [Decimal("2"), Decimal("2"), Decimal("1")],
        },
    )
    assert _traded_notional(fills) == Decimal("620")


def test_traded_notional_handles_missing_or_odd_columns() -> None:
    assert _traded_notional(pd.DataFrame()) == Decimal("0")
    assert _traded_notional(pd.DataFrame({"foo": [1, 2]})) == Decimal("0")
    # Fallback column names and "0.5 USDT"-style strings.
    fills = pd.DataFrame({"price": ["10.5 USDT"], "quantity": ["2.0"]})
    assert _traded_notional(fills) == Decimal("21.0")


def _metrics(breakeven: Decimal | None, notional: Decimal) -> BacktestMetrics:
    return BacktestMetrics(
        fees_paid=Decimal("10"),
        max_drawdown=Decimal("0.01"),
        turnover=notional,
        sharpe_like=None,
        traded_notional=notional,
        breakeven_cost=breakeven,
    )


def _fold(index: int, metrics: BacktestMetrics | None) -> WalkForwardFold:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    report = BacktestReport(
        fills=1,
        positions=1,
        ending_balance=Decimal("100000"),
        notes="test",
        metrics=metrics,
    )
    return WalkForwardFold(
        index=index,
        selected=SelectedParams(
            fast_ema=10,
            slow_ema=20,
            donchian_period=20,
            bb_period=20,
            bb_k=Decimal("2"),
            enter_trend_er=Decimal("0.3"),
            exit_trend_er=Decimal("0.2"),
        ),
        candidates_tried=1,
        in_sample=report,
        out_of_sample=report,
        window=WalkForwardWindow(
            in_sample_start=start,
            in_sample_end=start + timedelta(days=10),
            out_of_sample_start=start + timedelta(days=11),
            out_of_sample_end=start + timedelta(days=20),
        ),
    )


def test_multi_window_aggregates_only_measured_folds() -> None:
    report = MultiWindowReport(
        folds=(
            _fold(0, _metrics(Decimal("0.001"), Decimal("1000"))),
            _fold(1, _metrics(None, Decimal("0"))),
            _fold(2, _metrics(Decimal("0.003"), Decimal("2000"))),
        ),
        starting_equity=Decimal("100000"),
        notes="test",
    )
    # The unmeasured fold is skipped, not counted as zero.
    assert report.breakeven_costs == (Decimal("0.001"), Decimal("0.003"))
    assert report.mean_breakeven_cost == Decimal("0.002")


def test_multi_window_without_fills_is_undefined() -> None:
    report = MultiWindowReport(
        folds=(_fold(0, None),),
        starting_equity=Decimal("100000"),
        notes="test",
    )
    assert report.breakeven_costs == ()
    assert report.mean_breakeven_cost is None


def test_cli_prints_breakeven_next_to_paid_cost(capsys: pytest.CaptureFixture[str]) -> None:
    from nautilus_lab.interfaces.cli import _print_backtest

    _print_backtest(
        BacktestReport(
            fills=4,
            positions=2,
            ending_balance=Decimal("99000"),
            notes="test",
            metrics=_metrics(Decimal("0.0015"), Decimal("100000")),
        ),
    )
    output = capsys.readouterr().out
    assert "traded_notional=100000" in output
    assert "paid_cost_bps=1.00" in output
    assert "breakeven_cost_bps=15.00" in output
