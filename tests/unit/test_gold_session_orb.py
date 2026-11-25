"""Unit tests for the `gold_session_orb` domain strategy and wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.api.paper_streamer import LivePaperConfig, LivePaperSessionManager
from nautilus_lab.application.dtos import SelectedParams
from nautilus_lab.application.param_grid import iter_grid
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import is_warmup
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.gold_session_orb import GoldSessionOrb, GoldSessionOrbParams
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.infrastructure.settings import Settings


def _bar(
    ts_utc: datetime,
    close: str,
    *,
    high: str | None = None,
    low: str | None = None,
    open_: str | None = None,
) -> OhlcvBar:
    c = Decimal(close)
    o = Decimal(open_) if open_ is not None else c
    h = Decimal(high) if high is not None else max(o, c) + Decimal("2")
    lo = Decimal(low) if low is not None else min(o, c) - Decimal("2")
    return OhlcvBar(
        instrument_id="PAXGUSDT-PERP.SIM",
        ts_utc=ts_utc,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=Decimal("100"),
    )


def _warm_uptrend(robot: GoldSessionOrb, *, count: int = 12) -> None:
    """Warm up ATR and trend EMA on an uptrend ending on Wednesday 2026-01-14 23:00 UTC."""
    end = datetime(2026, 1, 14, 23, 0, tzinfo=UTC)
    start = end - timedelta(hours=count - 1)
    for i in range(count):
        price = Decimal("2600") + Decimal(i) * Decimal("5")
        bar = _bar(
            start + timedelta(hours=i),
            str(price),
            high=str(price + Decimal("5")),
            low=str(price - Decimal("5")),
        )
        robot.on_bar(bar)


def _warm_downtrend(robot: GoldSessionOrb, *, count: int = 12) -> None:
    """Warm up ATR and trend EMA on a downtrend ending on Wednesday 2026-01-14 23:00 UTC."""
    end = datetime(2026, 1, 14, 23, 0, tzinfo=UTC)
    start = end - timedelta(hours=count - 1)
    for i in range(count):
        price = Decimal("2700") - Decimal(i) * Decimal("5")
        bar = _bar(
            start + timedelta(hours=i),
            str(price),
            high=str(price + Decimal("5")),
            low=str(price - Decimal("5")),
        )
        robot.on_bar(bar)


def test_warmup_returns_none_and_records_trace() -> None:
    params = GoldSessionOrbParams(atr_period=5, trend_ema_period=10)
    robot = GoldSessionOrb(instrument_id="PAXGUSDT-PERP.SIM", params=params)
    t0 = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    for i in range(9):
        sig = robot.on_bar(_bar(t0 + timedelta(hours=i), "2650"))
        assert sig is None
        assert is_warmup(robot.last_trace)


def test_long_breakout_in_london_above_ema_emits_buy() -> None:
    params = GoldSessionOrbParams(
        atr_period=5,
        trend_ema_period=10,
        min_box_atr=Decimal("0.2"),
        max_box_atr=Decimal("1.2"),
        buffer_atr=Decimal("0.15"),
        min_asia_bars=3,
    )
    robot = GoldSessionOrb(instrument_id="PAXGUSDT-PERP.SIM", params=params)
    _warm_uptrend(robot, count=12)

    # Asia session on Thu 2026-01-15 (00:00-06:00 GMT): tight box [2652, 2658] (width=6, ATR~10)
    for h in range(4):
        sig = robot.on_bar(
            _bar(
                datetime(2026, 1, 15, h, 0, tzinfo=UTC),
                "2655",
                high="2658",
                low="2652",
            )
        )
        assert sig is None
    assert robot.box_high == Decimal("2658")
    assert robot.box_low == Decimal("2652")

    # London open (08:00 GMT): close breaks cleanly above box_high + 0.15 * ATR and EMA
    sig = robot.on_bar(
        _bar(
            datetime(2026, 1, 15, 8, 0, tzinfo=UTC),
            "2668",
            high="2670",
            low="2657",
        )
    )
    assert sig is not None
    assert sig.side is SignalSide.BUY
    assert sig.instrument_id == "PAXGUSDT-PERP.SIM"


def test_trend_ema_blocks_counter_trend_breakout() -> None:
    params = GoldSessionOrbParams(
        atr_period=5,
        trend_ema_period=10,
        min_box_atr=Decimal("0.2"),
        max_box_atr=Decimal("1.5"),
        buffer_atr=Decimal("0.1"),
        min_asia_bars=3,
    )
    robot = GoldSessionOrb(instrument_id="PAXGUSDT-PERP.SIM", params=params)
    _warm_downtrend(robot, count=12)  # ends near 2645, EMA is well above ~2665

    # Asia box below EMA: [2620, 2626]
    for h in range(4):
        assert (
            robot.on_bar(
                _bar(
                    datetime(2026, 1, 15, h, 0, tzinfo=UTC),
                    "2623",
                    high="2626",
                    low="2620",
                )
            )
            is None
        )

    # London closes at 2635: above box_high + buffer, but still below EMA -> blocked
    sig = robot.on_bar(
        _bar(
            datetime(2026, 1, 15, 8, 0, tzinfo=UTC),
            "2635",
            high="2636",
            low="2625",
        )
    )
    assert sig is None
    assert robot.last_trace[-1].result == "no_breakout"


def test_short_breakout_respects_allow_short_flag() -> None:
    from dataclasses import replace

    base_params = GoldSessionOrbParams(
        atr_period=5,
        trend_ema_period=10,
        min_box_atr=Decimal("0.2"),
        max_box_atr=Decimal("1.5"),
        buffer_atr=Decimal("0.15"),
        min_asia_bars=3,
        allow_short=False,
    )
    long_only = GoldSessionOrb(
        instrument_id="PAXGUSDT-PERP.SIM",
        params=base_params,
    )
    both_sides = GoldSessionOrb(
        instrument_id="PAXGUSDT-PERP.SIM",
        params=replace(base_params, allow_short=True),
    )
    _warm_downtrend(long_only, count=12)
    _warm_downtrend(both_sides, count=12)

    for h in range(4):
        bar = _bar(datetime(2026, 1, 15, h, 0, tzinfo=UTC), "2642", high="2645", low="2639")
        long_only.on_bar(bar)
        both_sides.on_bar(bar)

    breakdown = _bar(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), "2630", high="2640", low="2629")
    assert long_only.on_bar(breakdown) is None
    sig = both_sides.on_bar(breakdown)
    assert sig is not None
    assert sig.side is SignalSide.SELL


def test_box_width_filter_blocks_dead_and_exhausted_asia_boxes() -> None:
    params = GoldSessionOrbParams(
        atr_period=5,
        trend_ema_period=10,
        min_box_atr=Decimal("0.3"),
        max_box_atr=Decimal("0.8"),
        buffer_atr=Decimal("0.1"),
        min_asia_bars=3,
    )
    # Dead box: width=0.5 << 0.3 * ATR
    dead_robot = GoldSessionOrb(instrument_id="PAXGUSDT-PERP.SIM", params=params)
    _warm_uptrend(dead_robot, count=12)
    for h in range(4):
        dead_robot.on_bar(
            _bar(datetime(2026, 1, 15, h, 0, tzinfo=UTC), "2655", high="2655.25", low="2654.75")
        )
    assert (
        dead_robot.on_bar(
            _bar(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), "2670", high="2672", low="2655")
        )
        is None
    )
    assert dead_robot.last_trace[-1].result == "box_width_out_of_range"

    # Exhausted box: width=40 >> 0.8 * ATR
    exhausted_robot = GoldSessionOrb(instrument_id="PAXGUSDT-PERP.SIM", params=params)
    _warm_uptrend(exhausted_robot, count=12)
    for h in range(4):
        exhausted_robot.on_bar(
            _bar(datetime(2026, 1, 15, h, 0, tzinfo=UTC), "2675", high="2695", low="2655")
        )
    assert (
        exhausted_robot.on_bar(
            _bar(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), "2720", high="2722", low="2690")
        )
        is None
    )
    assert exhausted_robot.last_trace[-1].result == "box_width_out_of_range"


def test_max_one_entry_per_london_day_and_next_day_reset() -> None:
    params = GoldSessionOrbParams(
        atr_period=5,
        trend_ema_period=10,
        min_box_atr=Decimal("0.2"),
        max_box_atr=Decimal("1.5"),
        buffer_atr=Decimal("0.1"),
        min_asia_bars=3,
    )
    robot = GoldSessionOrb(instrument_id="PAXGUSDT-PERP.SIM", params=params)
    _warm_uptrend(robot, count=12)

    for h in range(4):
        robot.on_bar(_bar(datetime(2026, 1, 15, h, 0, tzinfo=UTC), "2655", high="2658", low="2652"))

    first = robot.on_bar(
        _bar(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), "2668", high="2670", low="2657")
    )
    assert first is not None
    assert first.side is SignalSide.BUY

    # Broker protective stop flattens position on the same London trading day.
    robot.sync_holding(SignalSide.FLAT)
    second_same_day = robot.on_bar(
        _bar(datetime(2026, 1, 15, 10, 0, tzinfo=UTC), "2675", high="2677", low="2666")
    )
    assert second_same_day is None
    assert robot.last_trace[-1].result == "daily_limit_reached"

    # Next London trading day (Fri 2026-01-16): new Asia box + London breakout works again.
    for h in range(4):
        robot.on_bar(_bar(datetime(2026, 1, 16, h, 0, tzinfo=UTC), "2676", high="2679", low="2673"))
    next_day = robot.on_bar(
        _bar(datetime(2026, 1, 16, 8, 0, tzinfo=UTC), "2690", high="2692", low="2678")
    )
    assert next_day is not None
    assert next_day.side is SignalSide.BUY


def test_time_stop_and_weekend_flatten_emit_flat() -> None:
    # 1. Time-stop after max_hold_bars=3
    params = GoldSessionOrbParams(
        atr_period=5,
        trend_ema_period=10,
        min_box_atr=Decimal("0.2"),
        max_box_atr=Decimal("1.5"),
        buffer_atr=Decimal("0.1"),
        max_hold_bars=3,
        min_asia_bars=3,
    )
    robot = GoldSessionOrb(instrument_id="PAXGUSDT-PERP.SIM", params=params)
    _warm_uptrend(robot, count=12)
    for h in range(4):
        robot.on_bar(_bar(datetime(2026, 1, 15, h, 0, tzinfo=UTC), "2655", high="2658", low="2652"))
    entry = robot.on_bar(
        _bar(datetime(2026, 1, 15, 8, 0, tzinfo=UTC), "2668", high="2670", low="2657")
    )
    assert entry is not None
    assert entry.side is SignalSide.BUY

    assert robot.on_bar(_bar(datetime(2026, 1, 15, 9, 0, tzinfo=UTC), "2669")) is None
    assert robot.on_bar(_bar(datetime(2026, 1, 15, 10, 0, tzinfo=UTC), "2670")) is None
    exit_sig = robot.on_bar(_bar(datetime(2026, 1, 15, 11, 0, tzinfo=UTC), "2671"))
    assert exit_sig is not None
    assert exit_sig.side is SignalSide.FLAT
    assert "time stop" in exit_sig.reason

    # 2. Weekend flatten before max_hold_bars (Fri 2026-01-16 22:00 UTC = 17:00 EST -> WEEKEND)
    weekend_robot = GoldSessionOrb(
        instrument_id="PAXGUSDT-PERP.SIM",
        params=GoldSessionOrbParams(
            atr_period=5,
            trend_ema_period=10,
            min_box_atr=Decimal("0.2"),
            max_box_atr=Decimal("1.5"),
            buffer_atr=Decimal("0.1"),
            max_hold_bars=24,
            min_asia_bars=3,
        ),
    )
    _warm_uptrend(weekend_robot, count=12)
    for h in range(4):
        weekend_robot.on_bar(
            _bar(datetime(2026, 1, 16, h, 0, tzinfo=UTC), "2655", high="2658", low="2652")
        )
    entry2 = weekend_robot.on_bar(
        _bar(datetime(2026, 1, 16, 14, 0, tzinfo=UTC), "2668", high="2670", low="2657")
    )
    assert entry2 is not None
    assert entry2.side is SignalSide.BUY
    wknd_exit = weekend_robot.on_bar(_bar(datetime(2026, 1, 16, 22, 0, tzinfo=UTC), "2667"))
    assert wknd_exit is not None
    assert wknd_exit.side is SignalSide.FLAT
    assert "weekend" in wknd_exit.reason


def test_invalid_params_rejected() -> None:
    with pytest.raises(InvalidRiskError):
        GoldSessionOrbParams(atr_period=1)
    with pytest.raises(InvalidRiskError):
        GoldSessionOrbParams(trend_ema_period=1)
    with pytest.raises(InvalidRiskError):
        GoldSessionOrbParams(min_box_atr=Decimal("0.9"), max_box_atr=Decimal("0.5"))
    with pytest.raises(InvalidRiskError):
        GoldSessionOrbParams(buffer_atr=Decimal("-0.1"))
    with pytest.raises(InvalidRiskError):
        GoldSessionOrbParams(max_hold_bars=0)
    with pytest.raises(InvalidRiskError):
        GoldSessionOrbParams(min_asia_bars=0)


def test_settings_param_grid_and_live_paper_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOLD_ORB_ATR_PERIOD", "20")
    monkeypatch.setenv("GOLD_ORB_TREND_EMA_PERIOD", "150")
    monkeypatch.setenv("GOLD_ORB_MIN_BOX_ATR", "0.25")
    monkeypatch.setenv("GOLD_ORB_MAX_BOX_ATR", "1.0")
    monkeypatch.setenv("GOLD_ORB_BUFFER_ATR", "0.30")
    monkeypatch.setenv("GOLD_ORB_MAX_HOLD_BARS", "18")
    monkeypatch.setenv("GOLD_ORB_ALLOW_SHORT", "true")
    monkeypatch.setenv("GOLD_ORB_MIN_ASIA_BARS", "4")
    cfg = Settings(_env_file=None)  # type: ignore[call-arg]
    params = cfg.gold_session_orb_params()
    assert params.atr_period == 20
    assert params.trend_ema_period == 150
    assert params.min_box_atr == Decimal("0.25")
    assert params.max_box_atr == Decimal("1.0")
    assert params.buffer_atr == Decimal("0.30")
    assert params.max_hold_bars == 18
    assert params.allow_short is True
    assert params.min_asia_bars == 4

    base = SelectedParams(
        fast_ema=10,
        slow_ema=20,
        donchian_period=20,
        bb_period=20,
        bb_k=Decimal("2"),
        enter_trend_er=Decimal("0.30"),
        exit_trend_er=Decimal("0.20"),
    )
    grid = list(iter_grid(RobotName.GOLD_SESSION_ORB, base))
    assert len(grid) == 9
    assert {p.gold_orb_max_box_atr for p in grid} == {
        Decimal("2.5"),
        Decimal("3.5"),
        Decimal("4.5"),
    }
    assert {p.gold_orb_buffer_atr for p in grid} == {
        Decimal("0.0"),
        Decimal("0.15"),
        Decimal("0.30"),
    }
    assert len({p.label() for p in grid}) == 9

    session = LivePaperSessionManager(
        LivePaperConfig(
            symbol="PAXGUSDT-PERP",
            interval="1h",
            robot="gold_session_orb",
            gold_session_orb=params,
        )
    )
    assert isinstance(session._robot_instance, GoldSessionOrb)
