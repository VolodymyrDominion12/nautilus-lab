from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import BacktestReport
from nautilus_lab.application.score import UNRANKABLE, in_sample_score
from nautilus_lab.domain.metrics import BacktestMetrics, SelectionMetric, compute_metrics

START = Decimal("100000")


def _report(ending: str, *, max_dd: str, sharpe: str | None) -> BacktestReport:
    return BacktestReport(
        fills=10,
        positions=5,
        ending_balance=Decimal(ending),
        notes="",
        metrics=BacktestMetrics(
            fees_paid=Decimal("0"),
            max_drawdown=Decimal(max_dd),
            turnover=Decimal("0"),
            sharpe_like=None if sharpe is None else Decimal(sharpe),
        ),
    )


def test_pnl_picks_the_bigger_return_even_through_a_deep_hole() -> None:
    risky = _report("112000", max_dd="0.30", sharpe="0.01")
    steady = _report("108000", max_dd="0.03", sharpe="0.05")
    assert in_sample_score(risky) > in_sample_score(steady)


def test_calmar_and_sharpe_prefer_the_steady_candidate() -> None:
    risky = _report("112000", max_dd="0.30", sharpe="0.01")
    steady = _report("108000", max_dd="0.03", sharpe="0.05")
    for metric in (SelectionMetric.CALMAR, SelectionMetric.SHARPE):
        assert in_sample_score(steady, metric=metric, starting_equity=START) > in_sample_score(
            risky, metric=metric, starting_equity=START
        )


def test_unmeasurable_runs_rank_last_on_ratio_metrics() -> None:
    no_sharpe = _report("150000", max_dd="0.01", sharpe=None)
    assert in_sample_score(no_sharpe, metric=SelectionMetric.SHARPE) == UNRANKABLE
    missing = BacktestReport(fills=0, positions=0, ending_balance=None, notes="")
    assert (
        in_sample_score(missing, metric=SelectionMetric.CALMAR, starting_equity=START) == UNRANKABLE
    )


def test_calmar_floors_a_near_zero_drawdown() -> None:
    barely_traded = _report("100100", max_dd="0", sharpe="0.1")
    # 0.1% return over the 0.5% floor, not over zero.
    assert in_sample_score(
        barely_traded, metric=SelectionMetric.CALMAR, starting_equity=START
    ) == Decimal("0.001") / Decimal("0.005")


def test_calmar_needs_the_starting_equity() -> None:
    with pytest.raises(ValueError, match="starting equity"):
        in_sample_score(_report("1", max_dd="0.1", sharpe="0"), metric=SelectionMetric.CALMAR)


def test_annualized_sharpe_scales_by_sqrt_periods() -> None:
    curve = tuple(Decimal(value) for value in ("100", "101", "100.5", "102", "101.5", "103"))
    per_bar = compute_metrics(
        starting_equity=Decimal("100"),
        equity_curve=curve,
        fees_paid=Decimal("0"),
        turnover=Decimal("0"),
    )
    hourly = compute_metrics(
        starting_equity=Decimal("100"),
        equity_curve=curve,
        fees_paid=Decimal("0"),
        turnover=Decimal("0"),
        periods_per_year=8760,
    )
    assert per_bar.sharpe_annualized is None
    assert hourly.sharpe_like is not None and hourly.sharpe_annualized is not None
    ratio = hourly.sharpe_annualized / hourly.sharpe_like
    assert abs(ratio - Decimal("93.5949")) < Decimal("0.001")  # sqrt(8760)
