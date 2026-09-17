"""adaptive_ema: the scalar form of "selectivity" (input-dependent smoothing).

The experiments these tests pin:

- `selectivity = 0` must reproduce the fixed-alpha EMA **exactly**. That is what makes
  the grid's zero column a real control: if it drifted, "adaptive beat fixed" could be
  an artefact of two different filters rather than of adaptivity.
- The step must actually move with the efficiency ratio, otherwise the idea is untested.
- The regime gate must keep the same hysteresis as `regime`, since the filter is
  supposed to be the only difference between the two robots.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.adaptive_ema import (
    AdaptiveEma,
    AdaptiveEmaParams,
    AdaptiveEmaRouter,
    efficiency_ratio_of,
)
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.ema import ExponentialMovingAverage
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.regime import MarketRegime


def _closes(*values: str) -> list[Decimal]:
    return [Decimal(value) for value in values]


def _trend(count: int, *, start: str = "100", step: str = "1") -> list[Decimal]:
    price = Decimal(start)
    increment = Decimal(step)
    series: list[Decimal] = []
    for _ in range(count):
        series.append(price)
        price += increment
    return series


def _bars(closes: list[Decimal]) -> list[OhlcvBar]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars: list[OhlcvBar] = []
    for index, close in enumerate(closes):
        bars.append(
            OhlcvBar(
                instrument_id="ETH/USDT.SIM",
                ts_utc=start + timedelta(hours=index),
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("10"),
            ),
        )
    return bars


def test_selectivity_zero_matches_the_fixed_alpha_ema_exactly() -> None:
    closes = _trend(80) + _closes("150", "149", "148", "152", "160", "161", "159")
    params = AdaptiveEmaParams(base_period=10, er_period=5, selectivity=Decimal("0"))
    adaptive = AdaptiveEma(params)
    fixed = ExponentialMovingAverage(10)

    compared = 0
    for close in closes:
        adaptive.update(close)
        fixed.update(close)
        if fixed.initialized:
            assert adaptive.value == fixed.value
            compared += 1

    assert compared > 50, "the comparison never ran over a meaningful stretch"


def test_base_step_is_the_standard_ema_step() -> None:
    engine = AdaptiveEma(AdaptiveEmaParams(base_period=10))
    assert engine.alpha_base == Decimal(2) / Decimal(11)


def test_alpha_moves_with_the_efficiency_ratio() -> None:
    engine = AdaptiveEma(
        AdaptiveEmaParams(base_period=10, er_period=5, selectivity=Decimal("1")),
    )
    for close in _trend(20):
        engine.update(close)
    # A clean trend (ER = 1) steps faster than the base; pure noise (ER = 0) steps slower.
    fast = engine.effective_alpha(Decimal("1"))
    slow = engine.effective_alpha(Decimal("0"))
    assert fast > engine.alpha_base > slow
    assert slow >= Decimal("0.001")
    assert fast <= Decimal("0.999")


def test_selectivity_zero_keeps_alpha_constant_on_every_bar() -> None:
    engine = AdaptiveEma(
        AdaptiveEmaParams(base_period=5, er_period=5, selectivity=Decimal("0")),
    )
    seen: set[Decimal] = set()
    for close in _trend(30) + _closes("29", "31", "28", "33"):
        snapshot = engine.update(close)
        if snapshot is not None:
            seen.add(snapshot.alpha)
    assert seen == {engine.alpha_base}


def test_efficiency_ratio_of_a_perfect_trend_is_one() -> None:
    assert efficiency_ratio_of(tuple(_trend(10))) == Decimal("1")
    # Straight up then straight back to the start: net movement 0, path walked 10.
    round_trip = _trend(6) + _closes("104", "103", "102", "101", "100")
    assert efficiency_ratio_of(tuple(round_trip)) == 0


def test_snapshot_appears_only_after_warmup() -> None:
    params = AdaptiveEmaParams(base_period=10, er_period=5, slope_lookback=5)
    engine = AdaptiveEma(params)
    snapshots = [engine.update(close) for close in _trend(12)]
    assert snapshots[0] is None
    assert snapshots[-1] is None, "the slope window needs slope_lookback + 1 EMA values"
    snapshot = None
    for close in _trend(10, start="200"):
        snapshot = engine.update(close)
    assert snapshot is not None
    assert snapshot.regime is MarketRegime.UPTREND


def test_hysteresis_holds_the_regime_between_the_two_thresholds() -> None:
    params = AdaptiveEmaParams(
        base_period=3,
        er_period=3,
        slope_lookback=1,
        selectivity=Decimal("0"),
        enter_trend_er=Decimal("0.30"),
        exit_trend_er=Decimal("0.20"),
    )
    engine = AdaptiveEma(params)
    # A trending series enters the trend regime through real bars (ER = 1).
    for close in _trend(12):
        engine.update(close)
    assert engine.regime is MarketRegime.UPTREND
    # The band itself is checked by feeding the thresholds directly: hitting an ER of
    # exactly 0.25 with crafted prices would test arithmetic, not the gate. The gate is
    # a pure function — `update()` is what stores its result.
    assert engine.next_regime(Decimal("0.25"), Decimal("1")) is MarketRegime.UPTREND
    assert engine.next_regime(Decimal("0.25"), Decimal("-1")) is MarketRegime.DOWNTREND
    assert engine.next_regime(Decimal("0.25"), Decimal("0")) is MarketRegime.RANGE
    # Below exit_trend_er the trend is released; from RANGE the higher threshold applies.
    assert engine.next_regime(Decimal("0.10"), Decimal("1")) is MarketRegime.RANGE
    assert engine.next_regime(Decimal("0.35"), Decimal("1")) is MarketRegime.UPTREND


def test_invalid_params_fail_closed() -> None:
    with pytest.raises(InvalidRiskError, match="selectivity"):
        AdaptiveEmaParams(selectivity=Decimal("1.5"))
    with pytest.raises(InvalidRiskError, match="base_period"):
        AdaptiveEmaParams(base_period=1)
    with pytest.raises(InvalidRiskError, match="enter_trend_er"):
        AdaptiveEmaParams(enter_trend_er=Decimal("0.1"), exit_trend_er=Decimal("0.2"))


def test_router_warms_up_silently_then_reports_a_regime_change() -> None:
    router = AdaptiveEmaRouter(
        instrument_id="ETH/USDT.SIM",
        params=AdaptiveEmaParams(base_period=5, er_period=4, slope_lookback=2),
    )
    warm_up = _bars(_trend(15))
    assert all(router.on_bar(bar) is None for bar in warm_up), "warm-up must not trade"

    turning = _bars(_trend(30, start="200") + _trend(30, start="170", step="-1"))
    signals = [router.on_bar(bar) for bar in turning]
    assert any(
        signal is not None and signal.reason.startswith("regime change") for signal in signals
    )


def test_router_rejects_non_positive_prices() -> None:
    router = AdaptiveEmaRouter(
        instrument_id="ETH/USDT.SIM",
        params=AdaptiveEmaParams(base_period=3, er_period=3, slope_lookback=1),
    )
    with pytest.raises(InvalidRiskError, match="close must be > 0"):
        router.on_bar(_bars(_closes("0"))[0])
