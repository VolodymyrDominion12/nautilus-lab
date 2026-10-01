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


def test_range_mean_reversion_disables_short_when_configured() -> None:
    from nautilus_lab.domain.mean_reversion import RangeMeanReversion
    from nautilus_lab.domain.signals import SignalSide

    # With allow_short=False, hitting upper band emits FLAT (take profit), not SELL
    mr = RangeMeanReversion(
        instrument_id="ETH/USDT.SIM", period=5, band_k=Decimal("1.5"), allow_short=False
    )
    # 5 flat bars then 1 spike above upper band
    bars = _bars(_closes("100", "100", "100", "100", "100", "120"))
    signals = [mr.on_bar(b) for b in bars]
    # The spike bar should produce FLAT take profit, not SELL
    last_sig = signals[-1]
    assert last_sig is not None
    assert last_sig.side == SignalSide.FLAT
    assert "take profit" in last_sig.reason


def test_range_mean_reversion_respects_min_band_width() -> None:
    from nautilus_lab.domain.mean_reversion import RangeMeanReversion

    # Tiny variance: band width is around 0.2%, but min required is 5%
    mr = RangeMeanReversion(
        instrument_id="ETH/USDT.SIM",
        period=5,
        band_k=Decimal("2"),
        min_band_width_pct=Decimal("0.05"),
    )
    bars = _bars(_closes("100", "100.1", "100", "100.1", "100", "99.7"))
    signals = [mr.on_bar(b) for b in bars]
    assert signals[-1] is None, "entry must be suppressed when band width is too narrow"


def test_range_mean_reversion_exit_at_mean() -> None:
    from nautilus_lab.domain.mean_reversion import RangeMeanReversion
    from nautilus_lab.domain.signals import SignalSide

    # With exit_at_mean=True, exit_factor is 0.2 rather than 0.5.
    mr_mean = RangeMeanReversion(
        instrument_id="ETH/USDT.SIM",
        period=5,
        band_k=Decimal("1.5"),
        exit_at_mean=True,
    )
    # Warm up with values around 100, then drop to trigger lower band, then rebound near mean
    # Closes: 100, 100, 100, 100, 100 (mean 100, stdev 0)
    # 70 (mean 94, stdev 12, lower 70 -> buy)
    # 93 (mean ~92.6, abs(93 - 92.6) = 0.4 <= 0.2 * 2 * stdev -> flat)
    bars = _bars(_closes("100", "100", "100", "100", "100", "70", "93"))
    sigs = [mr_mean.on_bar(b) for b in bars]
    buy_sig = sigs[-2]
    flat_sig = sigs[-1]
    assert buy_sig is not None
    assert buy_sig.side == SignalSide.BUY
    assert flat_sig is not None
    assert flat_sig.side == SignalSide.FLAT
    assert "mean revert complete" in flat_sig.reason


def test_adaptive_ema_router_holds_trend_long_in_range() -> None:
    from nautilus_lab.domain.signals import SignalSide

    # Build router with hold_trend_in_range=True (default)
    router = AdaptiveEmaRouter(
        instrument_id="ETH/USDT.SIM",
        params=AdaptiveEmaParams(
            base_period=5,
            er_period=4,
            slope_lookback=2,
            donchian_period=5,
            hold_trend_in_range=True,
        ),
    )
    # 1. Warm-up bars
    # 2. Strong trend bars upwards to trigger UPTREND and Donchian BUY
    # 3. Series of sideways bars that drop ER into RANGE, but stay above EMA
    trend_bars = _bars(
        _trend(15, start="100", step="2")  # warm up + uptrend
        + _closes("130", "131", "130", "131", "130")  # sideways consolidation
    )
    signals = [router.on_bar(b) for b in trend_bars]
    # Check that we got a BUY signal during the trend
    buy_signals = [s for s in signals if s is not None and s.side == SignalSide.BUY]
    assert len(buy_signals) > 0, "should produce buy signal during breakout"
    # When entering range, router should NOT have emitted FLAT
    # The last signal during sideways above EMA should not be FLAT
    last_signal = signals[-1]
    assert last_signal is None or last_signal.side != SignalSide.FLAT


def test_settings_adaptive_ema_params_forwarding() -> None:
    from nautilus_lab.infrastructure.settings import Settings

    s = Settings(
        adaptive_range_allow_short=True,
        adaptive_range_exit_at_mean=True,
        adaptive_min_bb_width_pct=Decimal("0.04"),
        adaptive_hold_trend_in_range=False,
    )
    p = s.adaptive_ema_params()
    assert p.range_allow_short is True
    assert p.range_exit_at_mean is True
    assert p.min_bb_width_pct == Decimal("0.04")
    assert p.hold_trend_in_range is False
