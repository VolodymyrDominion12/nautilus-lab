from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import Verdict
from nautilus_lab.domain.entry_filters import EntryFilter, EntryFilterParams
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.position_plan import PositionPlan, without_reversal
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.signals import SignalSide


def _bar(close: Decimal, index: int, *, spread: Decimal = Decimal("1")) -> OhlcvBar:
    ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        open=close,
        high=close + spread,
        low=close - spread,
        close=close,
        volume=Decimal("1"),
    )


def _trend_filter() -> EntryFilter:
    return EntryFilter(EntryFilterParams(htf_trend=True, htf_ema_period=5, htf_slope_lookback=3))


def test_defaults_are_all_off_and_allow_everything() -> None:
    params = EntryFilterParams()
    assert not params.any_gate
    assert not params.no_instant_reverse
    gate = EntryFilter(params)
    verdict = gate.evaluate(SignalSide.BUY)
    assert verdict.allowed
    assert verdict.steps == ()


def test_htf_trend_blocks_until_warm() -> None:
    gate = _trend_filter()
    gate.update(_bar(Decimal("100"), 0))
    verdict = gate.evaluate(SignalSide.BUY)
    assert not verdict.allowed
    assert verdict.code == "htf_trend"
    assert verdict.steps[0].verdict is Verdict.BLOCK


def test_htf_trend_allows_with_the_slope_and_blocks_against_it() -> None:
    gate = _trend_filter()
    for index in range(20):
        gate.update(_bar(Decimal(100 + index), index))
    slope = gate.htf_slope()
    assert slope is not None
    assert slope > 0
    assert gate.evaluate(SignalSide.BUY).allowed
    short = gate.evaluate(SignalSide.SELL)
    assert not short.allowed
    assert short.code == "htf_trend"


def test_htf_trend_in_a_falling_market_allows_shorts_only() -> None:
    gate = _trend_filter()
    for index in range(20):
        gate.update(_bar(Decimal(200 - index), index))
    assert gate.evaluate(SignalSide.SELL).allowed
    assert not gate.evaluate(SignalSide.BUY).allowed


def test_flat_is_never_blocked() -> None:
    gate = _trend_filter()
    assert gate.evaluate(SignalSide.FLAT).allowed


def test_vol_expansion_blocks_compressed_ranges() -> None:
    gate = EntryFilter(EntryFilterParams(vol_expansion=True, vol_fast_period=3, vol_slow_period=10))
    for index in range(7):
        gate.update(_bar(Decimal("100"), index, spread=Decimal("2")))
    for index in range(7, 10):
        gate.update(_bar(Decimal("100"), index, spread=Decimal("0.5")))
    ratio = gate.vol_ratio()
    assert ratio is not None
    assert ratio < 1
    verdict = gate.evaluate(SignalSide.BUY)
    assert not verdict.allowed
    assert verdict.code == "vol_expansion"


def test_vol_expansion_allows_expanding_ranges() -> None:
    gate = EntryFilter(EntryFilterParams(vol_expansion=True, vol_fast_period=3, vol_slow_period=10))
    for index in range(7):
        gate.update(_bar(Decimal("100"), index, spread=Decimal("0.5")))
    for index in range(7, 10):
        gate.update(_bar(Decimal("100"), index, spread=Decimal("2")))
    ratio = gate.vol_ratio()
    assert ratio is not None
    assert ratio > 1
    assert gate.evaluate(SignalSide.SELL).allowed


def test_both_gates_report_a_step_each_and_name_the_first_refusal() -> None:
    gate = EntryFilter(
        EntryFilterParams(
            htf_trend=True,
            htf_ema_period=5,
            htf_slope_lookback=3,
            vol_expansion=True,
            vol_fast_period=3,
            vol_slow_period=10,
        )
    )
    for index in range(20):
        gate.update(_bar(Decimal(100 + index), index, spread=Decimal("1")))
    verdict = gate.evaluate(SignalSide.SELL)
    assert [s.component for s in verdict.steps] == ["htf_trend", "vol_expansion"]
    assert verdict.code == "htf_trend"


def test_warmup_bars_follow_the_enabled_gates() -> None:
    assert EntryFilterParams().warmup_bars() == 0
    assert EntryFilterParams(htf_trend=True).warmup_bars() == 224
    assert EntryFilterParams(vol_expansion=True).warmup_bars() == 300


@pytest.mark.parametrize(
    "kwargs",
    [
        {"htf_ema_period": 1},
        {"htf_slope_lookback": 0},
        {"vol_fast_period": 0},
        {"vol_fast_period": 24, "vol_slow_period": 24},
        {"min_vol_ratio": Decimal("0")},
    ],
)
def test_invalid_params_fail(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidRiskError):
        EntryFilterParams(**kwargs)  # type: ignore[arg-type]


def test_without_reversal_keeps_the_exit_and_drops_the_entry() -> None:
    reverse = PositionPlan(exit_position=True, wants_entry=True)
    assert without_reversal(reverse) == PositionPlan(exit_position=True, wants_entry=False)
    for plan in (
        PositionPlan(exit_position=False, wants_entry=True),
        PositionPlan(exit_position=True, wants_entry=False),
        PositionPlan(exit_position=False, wants_entry=False),
    ):
        assert without_reversal(plan) == plan


def _range_router(*, allow_short: bool) -> RegimeRouter:
    params = RegimeParams(
        er_period=5,
        trend_ema_period=5,
        slope_lookback=2,
        bb_period=5,
        bb_k=Decimal("1"),
        range_allow_short=allow_short,
    )
    return RegimeRouter(instrument_id="ETH/USDT.SIM", params=params)


def _flat_then_spike(router: RegimeRouter) -> list[SignalSide]:
    sides: list[SignalSide] = []
    # A choppy, directionless series keeps ER low, so the router stays in RANGE.
    closes = [Decimal(100 + (1 if i % 2 else -1)) for i in range(20)]
    for index, close in enumerate(closes):
        router.on_bar(_bar(close, index, spread=Decimal("0.5")))
    signal = router.on_bar(_bar(Decimal("104"), 20, spread=Decimal("0.5")))
    if signal is not None:
        sides.append(signal.side)
    return sides


def test_regime_range_leg_shorts_the_upper_band_by_default() -> None:
    assert RegimeParams().range_allow_short is True
    assert _flat_then_spike(_range_router(allow_short=True)) == [SignalSide.SELL]


def test_regime_range_leg_without_shorts_takes_profit_instead() -> None:
    assert _flat_then_spike(_range_router(allow_short=False)) == [SignalSide.FLAT]
