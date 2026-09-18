"""Circuit-breaker refusals must survive into the report, not die as a log line.

Before this, a blocked entry was a `log.warning` and nothing more, so a finished
run could sit exactly on `MAX_DRAWDOWN` and still not say which breaker had fired
or how often. `RiskDecision.reason` already had the answer; these tests pin that it
now reaches the report and the CLI instead of being discarded.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import (
    BacktestReport,
    MultiWindowReport,
    SelectedParams,
    WalkForwardFold,
)
from nautilus_lab.application.risk import RiskBreachTally
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.interfaces.cli import _breach_line, _multi_window_breach_line

_TS = datetime(2025, 1, 1, tzinfo=UTC)

_LIMITS = RiskLimits(
    risk_per_trade=Decimal("0.005"),
    stop_pct=Decimal("0.01"),
    max_daily_loss=Decimal("0.02"),
    max_drawdown=Decimal("0.06"),
    max_open_positions=1,
)


def test_a_tally_counts_each_reason_separately() -> None:
    tally = RiskBreachTally()
    tally.record("daily loss circuit breaker")
    tally.record("max drawdown circuit breaker")
    tally.record("daily loss circuit breaker")

    assert tally.summary() == (
        ("daily loss circuit breaker", 2),
        ("max drawdown circuit breaker", 1),
    )
    assert tally.total == 3
    assert tally.tripped is True


def test_an_untouched_tally_reports_nothing_rather_than_zeroes() -> None:
    """A clean run and an unmeasured run must not be confusable in the output."""
    tally = RiskBreachTally()
    assert tally.summary() == ()
    assert tally.total == 0
    assert tally.tripped is False


def test_record_returns_the_running_total() -> None:
    tally = RiskBreachTally()
    assert tally.record("max drawdown circuit breaker") == 1
    assert tally.record("max drawdown circuit breaker") == 2


def test_first_trip_order_is_preserved_not_sorted() -> None:
    """The order is the run's story, and answers "which breaker fired first"."""
    tally = RiskBreachTally()
    tally.record("max drawdown circuit breaker")
    tally.record("daily loss circuit breaker")
    first_reason = next(reason for reason, _ in tally.summary())
    assert first_reason == "max drawdown circuit breaker"


def test_the_reasons_recorded_are_the_real_ones_from_evaluate_entry() -> None:
    """The tally must be fed by `evaluate_entry`, not by invented labels."""
    from nautilus_lab.application.risk import evaluate_entry

    # Down 10% on the day AND 10% off the peak breaches both daily-loss (2%) and
    # drawdown (6%). Daily loss is checked first, so it is the reason recorded —
    # this is the checker's precedence, and it decides which breaker the report
    # names.
    both = AccountSnapshot(
        equity=Decimal("90000"),
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("100000"),
        open_positions=0,
        recent_returns=(),
    )
    decision = evaluate_entry(both, _LIMITS)
    assert decision.allowed is False
    assert decision.reason == "daily loss circuit breaker"

    tally = RiskBreachTally()
    tally.record(decision.reason)
    assert tally.summary() == (("daily loss circuit breaker", 1),)


def test_drawdown_is_the_reason_when_the_day_itself_is_flat() -> None:
    """Peak-to-trough drawdown with a flat day must name the drawdown breaker."""
    from nautilus_lab.application.risk import evaluate_entry

    gross_only = AccountSnapshot(
        equity=Decimal("90000"),
        peak_equity=Decimal("100000"),
        day_start_equity=Decimal("90000"),
        open_positions=0,
        recent_returns=(),
    )
    decision = evaluate_entry(gross_only, _LIMITS)
    assert decision.allowed is False
    assert decision.reason == "max drawdown circuit breaker"


def test_breach_line_is_silent_when_no_entry_was_blocked() -> None:
    assert _breach_line("cost", _report(())) is None


def test_breach_line_reports_counts_and_the_blocked_total() -> None:
    line = _breach_line(
        "cost",
        _report((("max drawdown circuit breaker", 12), ("daily loss circuit breaker", 3))),
    )
    assert line is not None
    assert "blocked=15" in line
    assert "max drawdown circuit breaker=12" in line
    assert "daily loss circuit breaker=3" in line


def test_multi_window_line_sums_the_same_reason_across_folds() -> None:
    report = _multi_window(
        [
            (("max drawdown circuit breaker", 2),),
            (("max drawdown circuit breaker", 5), ("daily loss circuit breaker", 1)),
        ]
    )
    line = _multi_window_breach_line(report)
    assert line is not None
    assert "max drawdown circuit breaker=7" in line
    assert "daily loss circuit breaker=1" in line
    assert "blocked=8" in line


def test_multi_window_line_is_silent_when_no_fold_tripped() -> None:
    assert _multi_window_breach_line(_multi_window([(), ()])) is None


def _report(breaches: tuple[tuple[str, int], ...]) -> BacktestReport:
    return BacktestReport(
        fills=1,
        positions=1,
        ending_balance=Decimal("100000"),
        notes="test",
        risk_breaches=breaches,
    )


def _multi_window(fold_breaches: list[tuple[tuple[str, int], ...]]) -> MultiWindowReport:
    """A real report built from folds that carry only the fields under test."""
    # A real window per fold: the dataclass validates that IS precedes OOS, so a
    # degenerate all-equal window would raise rather than exercise the code.
    windows = [
        WalkForwardWindow(
            in_sample_start=_TS + timedelta(days=8 * index),
            in_sample_end=_TS + timedelta(days=8 * index + 6),
            out_of_sample_start=_TS + timedelta(days=8 * index + 6),
            out_of_sample_end=_TS + timedelta(days=8 * index + 8),
        )
        for index in range(len(fold_breaches))
    ]
    return MultiWindowReport(
        folds=tuple(
            WalkForwardFold(
                index=index,
                # Only `label()` is ever read from this; the values are inert here.
                selected=SelectedParams(
                    fast_ema=10,
                    slow_ema=20,
                    donchian_period=20,
                    bb_period=20,
                    bb_k=Decimal("2"),
                    enter_trend_er=Decimal("0.30"),
                    exit_trend_er=Decimal("0.20"),
                ),
                candidates_tried=1,
                in_sample=_report(()),
                out_of_sample=_report(breaches),
                window=window,
            )
            for index, (breaches, window) in enumerate(zip(fold_breaches, windows, strict=True))
        ),
        starting_equity=Decimal("100000"),
        notes="test",
    )


@pytest.mark.parametrize("count", [1, 2])
def test_tally_survives_being_recorded_repeatedly(count: int) -> None:
    tally = RiskBreachTally()
    for _ in range(count):
        tally.record("portfolio VaR 99% circuit breaker")
    assert tally.summary() == (("portfolio VaR 99% circuit breaker", count),)
