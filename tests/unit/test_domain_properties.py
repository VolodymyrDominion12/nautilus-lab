"""Property-based tests of the domain invariants (docs/27 E-2.7).

The example tests next to each module pin the cases someone thought of. These state
the rules themselves and let Hypothesis look for the input that breaks them: equity is
balance plus open PnL, an exit is never blocked by the entry logic, a quantile stays
inside the sample, walk-forward folds never see the future, and a position size never
risks more than the configured fraction or buys more than 1x notional.

Inputs use bounded Decimals with few places, so every expected value is exact: an
assertion failure is a rule broken, not a rounding artefact.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

pytest.importorskip("hypothesis")
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from nautilus_lab.application.risk import evaluate_entry, size_position
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidRiskError, InvalidWindowError
from nautilus_lab.domain.marking import (
    OpenLot,
    lot_unrealized_pnl,
    marked_equity,
    unrealized_pnl,
)
from nautilus_lab.domain.position_plan import (
    Holding,
    holding_from_signed_qty,
    plan_for_signal,
)
from nautilus_lab.domain.quantiles import empirical_quantile
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.walk_forward import (
    anchored_window,
    rolling_windows,
    split_by_window,
)

INSTRUMENTS = ("BTCUSDT.BINANCE", "ETHUSDT.BINANCE", "SOLUSDT.BINANCE")
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _decimals(low: str, high: str, places: int = 4) -> Any:
    return st.decimals(
        min_value=Decimal(low),
        max_value=Decimal(high),
        places=places,
        allow_nan=False,
        allow_infinity=False,
    )


PRICES = _decimals("0.0001", "100000")
QTYS = _decimals("-50", "50")
FRACTIONS = _decimals("0.0001", "1")
PROBABILITIES = _decimals("0.0001", "0.9999")
SAMPLES = st.lists(_decimals("-1000", "1000", places=2), min_size=1, max_size=60)


@st.composite
def _lots(draw: Callable[[Any], Any]) -> OpenLot:
    return OpenLot(
        instrument_id=draw(st.sampled_from(INSTRUMENTS)),
        signed_qty=draw(QTYS),
        avg_price=draw(PRICES),
    )


LOTS = st.lists(_lots(), max_size=8)
MARKS = st.dictionaries(st.sampled_from(INSTRUMENTS), PRICES)


# --- marking --------------------------------------------------------------------------


@given(balance=_decimals("-1000000", "1000000"), lots=LOTS, marks=MARKS)
def test_equity_is_balance_plus_open_pnl_of_marked_lots(
    balance: Decimal, lots: list[OpenLot], marks: dict[str, Decimal]
) -> None:
    expected = balance + sum(
        (
            (marks[lot.instrument_id] - lot.avg_price) * lot.signed_qty
            for lot in lots
            if lot.instrument_id in marks
        ),
        Decimal("0"),
    )
    assert marked_equity(balance, lots, marks) == expected


@given(lots=LOTS, marks=MARKS)
def test_unmarked_lots_are_valued_at_entry(lots: list[OpenLot], marks: dict[str, Decimal]) -> None:
    priced = [lot for lot in lots if lot.instrument_id in marks]
    assert unrealized_pnl(lots, marks) == unrealized_pnl(priced, marks)
    assert unrealized_pnl(lots, {}) == 0


@given(lots=LOTS, marks=MARKS, seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_open_pnl_does_not_depend_on_lot_order(
    lots: list[OpenLot], marks: dict[str, Decimal], seed: int
) -> None:
    shuffled = list(lots)
    random.Random(seed).shuffle(shuffled)
    assert unrealized_pnl(shuffled, marks) == unrealized_pnl(lots, marks)


@given(lot=_lots(), mark=PRICES)
def test_short_pnl_mirrors_long_pnl(lot: OpenLot, mark: Decimal) -> None:
    mirrored = OpenLot(lot.instrument_id, -lot.signed_qty, lot.avg_price)
    assert lot_unrealized_pnl(mirrored, mark) == -lot_unrealized_pnl(lot, mark)
    if lot.signed_qty > 0:
        assert (lot_unrealized_pnl(lot, mark) >= 0) == (mark >= lot.avg_price)


# --- position plan (small domain: every case, no sampling needed) --------------------


def _apply(held: Holding, desired: SignalSide) -> Holding:
    """What we hold after the plan runs, assuming the entry was allowed."""
    plan = plan_for_signal(held, desired)
    after = Holding.FLAT if plan.exit_position else held
    if plan.wants_entry:
        assert after is Holding.FLAT, "an entry is only ever planned from flat"
        after = Holding.LONG if desired is SignalSide.BUY else Holding.SHORT
    return after


TARGET = {
    SignalSide.BUY: Holding.LONG,
    SignalSide.SELL: Holding.SHORT,
    SignalSide.FLAT: Holding.FLAT,
}


@pytest.mark.parametrize("held", list(Holding))
@pytest.mark.parametrize("desired", list(SignalSide))
def test_plan_reaches_the_signal_target(held: Holding, desired: SignalSide) -> None:
    assert _apply(held, desired) is TARGET[desired]


@pytest.mark.parametrize("held", list(Holding))
@pytest.mark.parametrize("desired", list(SignalSide))
def test_exit_never_depends_on_the_entry(held: Holding, desired: SignalSide) -> None:
    """Refused entry (risk gate): the position must still end up out of the wrong side."""
    plan = plan_for_signal(held, desired)
    after_refusal = Holding.FLAT if plan.exit_position else held
    assert after_refusal in (Holding.FLAT, TARGET[desired])
    assert plan.is_noop == (held is TARGET[desired])


@given(qty=QTYS)
def test_holding_follows_the_sign_of_the_quantity(qty: Decimal) -> None:
    holding = holding_from_signed_qty(qty)
    assert holding is (Holding.LONG if qty > 0 else Holding.SHORT if qty < 0 else Holding.FLAT)


# --- quantiles ------------------------------------------------------------------------


@given(values=SAMPLES, p=PROBABILITIES)
def test_quantile_stays_inside_the_sample(values: list[Decimal], p: Decimal) -> None:
    q = empirical_quantile(tuple(values), p)
    assert min(values) <= q <= max(values)


@given(values=SAMPLES, p1=PROBABILITIES, p2=PROBABILITIES)
def test_quantile_is_monotone_in_probability(
    values: list[Decimal], p1: Decimal, p2: Decimal
) -> None:
    low, high = sorted((p1, p2))
    assert empirical_quantile(tuple(values), low) <= empirical_quantile(tuple(values), high)


@given(values=SAMPLES, p=PROBABILITIES, shift=_decimals("-1000", "1000", places=2))
def test_quantile_moves_with_a_shift_and_ignores_order(
    values: list[Decimal], p: Decimal, shift: Decimal
) -> None:
    q = empirical_quantile(tuple(values), p)
    assert empirical_quantile(tuple(v + shift for v in values), p) == q + shift
    assert empirical_quantile(tuple(reversed(values)), p) == q


@given(value=_decimals("-1000", "1000"), n=st.integers(1, 30), p=PROBABILITIES)
def test_quantile_of_a_constant_sample_is_the_constant(value: Decimal, n: int, p: Decimal) -> None:
    assert empirical_quantile((value,) * n, p) == value


# --- walk-forward ---------------------------------------------------------------------


def _bars(count: int, gaps: list[int]) -> tuple[OhlcvBar, ...]:
    """Strictly increasing UTC timestamps with irregular gaps (missing candles)."""
    price = Decimal("100")
    ts, bars = T0, []
    for i in range(count):
        ts += timedelta(minutes=gaps[i % len(gaps)])
        bars.append(OhlcvBar("BTCUSDT.BINANCE", ts, price, price, price, price, Decimal("1")))
    return tuple(bars)


BAR_SERIES = st.builds(
    _bars,
    count=st.integers(min_value=2, max_value=400),
    gaps=st.lists(st.integers(min_value=1, max_value=240), min_size=1, max_size=5),
)
IS_FRACTIONS = _decimals("0.05", "0.95", places=2)


@settings(max_examples=200)
@given(
    bars=BAR_SERIES,
    folds=st.integers(min_value=1, max_value=8),
    fraction=IS_FRACTIONS,
    embargo=st.integers(min_value=0, max_value=20),
)
def test_rolling_folds_never_see_the_future(
    bars: tuple[OhlcvBar, ...], folds: int, fraction: Decimal, embargo: int
) -> None:
    try:
        windows = rolling_windows(
            bars, folds=folds, in_sample_fraction=fraction, embargo_bars=embargo
        )
    except InvalidWindowError:
        return  # refusing an infeasible layout is allowed; any other error is not
    assert len(windows) == folds
    for i, window in enumerate(windows):
        split = split_by_window(bars, window)
        assert split.in_sample[-1].ts_utc < split.out_of_sample[0].ts_utc
        purged = [b for b in bars if window.in_sample_end <= b.ts_utc < window.out_of_sample_start]
        assert len(purged) == embargo, "the embargo gap is exactly `embargo_bars` bars"
        if i:
            previous = windows[i - 1]
            assert previous.out_of_sample_end == window.out_of_sample_start, "OOS blocks tile"
            assert window.in_sample_start > previous.in_sample_start, "selection slides forward"
    assert windows[0].out_of_sample_start > bars[0].ts_utc
    assert windows[-1].out_of_sample_end > bars[-1].ts_utc, "the last bar is reported on"


@given(
    bars=BAR_SERIES,
    fraction=IS_FRACTIONS,
    embargo=st.integers(min_value=0, max_value=20),
)
def test_anchored_split_is_disjoint_and_covers_the_tail(
    bars: tuple[OhlcvBar, ...], fraction: Decimal, embargo: int
) -> None:
    try:
        window = anchored_window(bars, in_sample_fraction=fraction, embargo_bars=embargo)
    except InvalidWindowError:
        return
    split = split_by_window(bars, window)
    assert len(split.in_sample) + embargo + len(split.out_of_sample) == len(bars)
    assert split.out_of_sample[-1] == bars[-1]
    assert split.in_sample[0] == bars[0]


# --- risk sizing ----------------------------------------------------------------------

EQUITY = _decimals("1", "10000000", places=2)
STEPS = st.sampled_from([Decimal("1"), Decimal("0.1"), Decimal("0.001"), Decimal("0.00001")])


@given(
    equity=EQUITY,
    price=PRICES,
    stop=_decimals("0.0001", "10000"),
    fraction=FRACTIONS,
    step=STEPS,
)
def test_size_never_risks_more_than_the_fraction_nor_exceeds_1x(
    equity: Decimal, price: Decimal, stop: Decimal, fraction: Decimal, step: Decimal
) -> None:
    qty = size_position(
        equity=equity, price=price, stop_distance=stop, risk_fraction=fraction, qty_step=step
    )
    assert qty >= 0
    assert (qty / step) == (qty / step).to_integral_value(), "whole lot steps only"
    assert qty * stop <= equity * fraction
    assert qty * price <= equity
    bigger = qty + step
    assert bigger * stop > equity * fraction or bigger * price > equity, "no lot left on the table"


@given(
    equity=EQUITY,
    extra=_decimals("0", "1000000", places=2),
    price=PRICES,
    stop=_decimals("0.0001", "10000"),
    fraction=FRACTIONS,
    step=STEPS,
)
def test_more_equity_never_means_a_smaller_position(
    equity: Decimal, extra: Decimal, price: Decimal, stop: Decimal, fraction: Decimal, step: Decimal
) -> None:
    kwargs = {"price": price, "stop_distance": stop, "risk_fraction": fraction, "qty_step": step}
    assert size_position(equity=equity + extra, **kwargs) >= size_position(equity=equity, **kwargs)


@given(
    equity=_decimals("-100", "100"),
    price=_decimals("-100", "100"),
    stop=_decimals("-100", "100"),
    fraction=_decimals("-1", "2"),
)
def test_size_refuses_out_of_domain_inputs_instead_of_guessing(
    equity: Decimal, price: Decimal, stop: Decimal, fraction: Decimal
) -> None:
    valid = equity > 0 and price > 0 and stop > 0 and 0 < fraction <= 1
    assume(not valid)
    with pytest.raises(InvalidRiskError):
        size_position(
            equity=equity,
            price=price,
            stop_distance=stop,
            risk_fraction=fraction,
            qty_step=Decimal("0.001"),
        )


LIMITS = RiskLimits(
    risk_per_trade=Decimal("0.01"),
    stop_pct=Decimal("0.02"),
    max_daily_loss=Decimal("0.03"),
    max_drawdown=Decimal("0.2"),
)


@given(
    equity=_decimals("-1000", "20000", places=2),
    day_start=_decimals("1", "20000", places=2),
    peak=_decimals("1", "20000", places=2),
    open_positions=st.integers(min_value=0, max_value=3),
)
def test_an_allowed_entry_is_inside_every_breaker(
    equity: Decimal, day_start: Decimal, peak: Decimal, open_positions: int
) -> None:
    snapshot = AccountSnapshot(
        equity=equity, peak_equity=peak, day_start_equity=day_start, open_positions=open_positions
    )
    decision = evaluate_entry(snapshot, LIMITS)
    if decision.allowed:
        assert equity > 0
        assert (day_start - equity) / day_start < LIMITS.max_daily_loss
        assert (peak - equity) / peak < LIMITS.max_drawdown
        assert open_positions <= LIMITS.max_open_positions
    else:
        assert decision.reason
