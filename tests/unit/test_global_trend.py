from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import Verdict
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.global_trend import (
    GlobalTrendGate,
    GlobalTrendParams,
    MaKind,
    TrendState,
    WarmupPolicy,
    timeframe_hours,
)
from nautilus_lab.domain.signals import SignalSide

_START = datetime(2024, 1, 1, tzinfo=UTC)


def _bar(close: Decimal, hour: int) -> OhlcvBar:
    """A 1h bar that CLOSES at `_START + (hour + 1)h`."""
    return OhlcvBar(
        instrument_id="SOL/USDT.SIM",
        ts_utc=_START + timedelta(hours=hour + 1),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1"),
    )


def _feed_days(gate: GlobalTrendGate, closes: list[int], *, start_hour: int = 0) -> int:
    """Feed 24 hourly bars per day, every bar of day `i` closing at `closes[i]`."""
    hour = start_hour
    for close in closes:
        for _ in range(24):
            gate.update(_bar(Decimal(close), hour))
            hour += 1
    return hour


def _gate(**kwargs: object) -> GlobalTrendGate:
    base: dict[str, object] = {"enabled": True, "period": 5, "band_pct": Decimal("0.02")}
    base.update(kwargs)
    return GlobalTrendGate(GlobalTrendParams(**base))  # type: ignore[arg-type]


def test_off_by_default_and_allows_everything() -> None:
    params = GlobalTrendParams()
    assert not params.enabled
    assert params.warmup_span() == timedelta(0)
    gate = GlobalTrendGate(params)
    gate.update(_bar(Decimal("100"), 0))
    for side in (SignalSide.BUY, SignalSide.SELL):
        verdict = gate.evaluate(side)
        assert verdict.allowed
        assert verdict.steps == ()


def test_daily_close_is_used_only_after_the_day_ends() -> None:
    gate = _gate()
    _feed_days(gate, [100] * 5)
    # Five full days fed, but the fifth is only complete once the next day's first bar
    # arrives: the 1h bar closing at 00:00 still belongs to the day before.
    assert gate.completed_buckets == 4
    assert gate.ma() is None
    gate.update(_bar(Decimal("100"), 5 * 24))
    assert gate.completed_buckets == 5
    assert gate.ma() == Decimal("100")


def test_bull_market_blocks_new_shorts_only() -> None:
    gate = _gate()
    _feed_days(gate, [100, 102, 104, 106, 108, 115])
    assert gate.state is TrendState.BULL
    assert gate.evaluate(SignalSide.BUY).allowed
    short = gate.evaluate(SignalSide.SELL)
    assert not short.allowed
    assert short.code == "global_trend"
    assert short.steps[0].verdict is Verdict.BLOCK
    assert short.steps[0].result == "against global trend"


def test_bear_market_blocks_new_longs_only() -> None:
    gate = _gate()
    _feed_days(gate, [200, 196, 192, 188, 184, 170])
    assert gate.state is TrendState.BEAR
    assert gate.evaluate(SignalSide.SELL).allowed
    assert not gate.evaluate(SignalSide.BUY).allowed


def test_pullback_inside_the_band_keeps_the_bull_state() -> None:
    gate = _gate(band_pct=Decimal("0.05"))
    _feed_days(gate, [100, 100, 100, 100, 100, 110])
    assert gate.state is TrendState.BULL
    # A pullback to just under the MA (still within -5%) does not flip the gate.
    _feed_days(gate, [99], start_hour=6 * 24)
    assert gate.ma() is not None
    assert gate.state is TrendState.BULL
    assert not gate.evaluate(SignalSide.SELL).allowed


def test_a_break_below_the_band_flips_to_bear() -> None:
    gate = _gate(band_pct=Decimal("0.02"))
    hour = _feed_days(gate, [100, 100, 100, 100, 100, 110])
    assert gate.state is TrendState.BULL
    gate.update(_bar(Decimal("90"), hour))
    assert gate.state is TrendState.BEAR
    assert gate.evaluate(SignalSide.SELL).allowed
    assert not gate.evaluate(SignalSide.BUY).allowed


def test_inside_the_band_before_any_break_is_neutral() -> None:
    gate = _gate(band_pct=Decimal("0.05"))
    _feed_days(gate, [100] * 6)
    assert gate.state is TrendState.NEUTRAL
    assert gate.evaluate(SignalSide.BUY).allowed
    assert gate.evaluate(SignalSide.SELL).allowed


def test_warmup_allow_lets_entries_through() -> None:
    gate = _gate()
    gate.update(_bar(Decimal("100"), 0))
    verdict = gate.evaluate(SignalSide.SELL)
    assert verdict.allowed
    assert verdict.steps[0].result == "warming up"
    assert verdict.steps[0].verdict is Verdict.PASS


def test_warmup_block_refuses_entries() -> None:
    gate = _gate(warmup=WarmupPolicy.BLOCK)
    gate.update(_bar(Decimal("100"), 0))
    verdict = gate.evaluate(SignalSide.BUY)
    assert not verdict.allowed
    assert verdict.code == "global_trend"


def test_flat_is_never_blocked() -> None:
    gate = _gate()
    _feed_days(gate, [100, 102, 104, 106, 108, 115])
    assert gate.evaluate(SignalSide.FLAT).allowed


def test_ema_variant_reaches_a_state() -> None:
    gate = _gate(ma=MaKind.EMA)
    _feed_days(gate, [100, 102, 104, 106, 108, 115])
    assert gate.ma() is not None
    assert gate.state is TrendState.BULL


def test_weekly_buckets_start_on_monday() -> None:
    gate = _gate(timeframe="1w", period=2)
    # 2024-01-01 is a Monday: two full weeks + the first bar of the third.
    _feed_days(gate, [100] * 14)
    gate.update(_bar(Decimal("100"), 14 * 24))
    assert gate.completed_buckets == 2
    assert gate.ma() == Decimal("100")


def test_string_settings_are_coerced() -> None:
    params = GlobalTrendParams(enabled=True, ma="ema", warmup="block")  # type: ignore[arg-type]
    assert params.ma is MaKind.EMA
    assert params.warmup is WarmupPolicy.BLOCK
    assert params.label() == "1d/ema200/band0.02/block"


def test_warmup_bars_cover_the_ma_in_bars_of_the_run() -> None:
    params = GlobalTrendParams(enabled=True)
    assert params.warmup_span() == timedelta(days=201)
    assert params.warmup_bars(timedelta(hours=1)) == 201 * 24
    assert params.warmup_bars(timedelta(hours=4)) == 201 * 6
    assert GlobalTrendParams().warmup_bars(timedelta(hours=1)) == 0


@pytest.mark.parametrize(
    ("timeframe", "hours"), [("4h", 4), ("1d", 24), ("3d", 72), ("1w", 168), (" 1D ", 24)]
)
def test_timeframe_hours(timeframe: str, hours: int) -> None:
    assert timeframe_hours(timeframe) == hours


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeframe": "1m"},
        {"timeframe": "0d"},
        {"timeframe": "daily"},
        {"period": 1},
        {"band_pct": Decimal("-0.01")},
        {"band_pct": Decimal("1")},
    ],
)
def test_invalid_params_fail(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidRiskError):
        GlobalTrendParams(**kwargs)  # type: ignore[arg-type]


def test_bad_enum_strings_fail() -> None:
    with pytest.raises(ValueError):
        GlobalTrendParams(ma="wma")  # type: ignore[arg-type]
