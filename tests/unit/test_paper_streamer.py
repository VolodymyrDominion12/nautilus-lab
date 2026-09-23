from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.api.paper_streamer import (
    LivePaperConfig,
    LivePaperSessionManager,
)
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.signals import Signal, SignalSide


def test_paper_streamer_initial_state() -> None:
    config = LivePaperConfig(
        symbol="BTCUSDT",
        starting_equity=Decimal("10000"),
        risk_per_trade=Decimal("0.01"),
        stop_pct=Decimal("0.02"),
    )
    manager = LivePaperSessionManager(config)
    assert not manager.is_active
    assert manager.balance == Decimal("10000")
    assert manager.current_equity == Decimal("10000")
    assert manager.position is None
    assert len(manager.fills) == 0


def test_paper_streamer_manual_position_and_stops() -> None:
    config = LivePaperConfig(
        symbol="BTCUSDT",
        starting_equity=Decimal("10000"),
        risk_per_trade=Decimal("0.02"),  # $200 risk
        stop_pct=Decimal("0.02"),  # 2% stop = $1,000 on $50,000 price
        take_profit_multiple=Decimal("2.0"),  # 4% TP
        qty_step=Decimal("0.001"),
    )
    manager = LivePaperSessionManager(config)
    manager.is_active = True

    # 1. Simulate opening LONG position
    events = manager._open_position_internal("LONG", Decimal("50000"))
    assert "Opened LONG" in events
    assert manager.position is not None
    assert manager.position.side == "LONG"
    assert manager.position.entry_price == "50000"
    assert Decimal(manager.position.stop_loss or "0") == Decimal("49000")  # 50,000 - 1,000
    assert Decimal(manager.position.take_profit or "0") == Decimal("52000")  # 50,000 + 2,000
    assert len(manager.fills) == 1
    assert manager.fills[0].side == "BUY"

    # 2. Simulate price moving up within bounds (not hitting TP yet)
    manager.process_kline_update(
        time_sec=1000,
        open_price=Decimal("50000"),
        high_price=Decimal("51000"),
        low_price=Decimal("49800"),
        close_price=Decimal("50500"),
        volume=Decimal("10"),
        is_closed=False,
    )
    assert manager.position is not None
    assert Decimal(manager.unrealized_pnl) > Decimal("0")
    assert manager.current_equity > manager.starting_equity

    # 3. Simulate price hitting Stop Loss (low breaches 49,000)
    sl_events = manager.process_kline_update(
        time_sec=1060,
        open_price=Decimal("50000"),
        high_price=Decimal("50100"),
        low_price=Decimal("48900"),  # Breaches 49000
        close_price=Decimal("49200"),
        volume=Decimal("15"),
        is_closed=False,
    )
    assert any("stop_loss" in ev for ev in sl_events)
    assert manager.position is None
    assert len(manager.fills) == 2
    assert manager.fills[1].reason == "stop_loss"
    assert Decimal(manager.realized_pnl) < Decimal("0")


def test_paper_streamer_take_profit_hit() -> None:
    config = LivePaperConfig(
        symbol="ETHUSDT",
        starting_equity=Decimal("10000"),
        risk_per_trade=Decimal("0.02"),
        stop_pct=Decimal("0.02"),
        take_profit_multiple=Decimal("2.0"),
    )
    manager = LivePaperSessionManager(config)
    manager.is_active = True

    # Open LONG @ 3,000 (SL: 2,940, TP: 3,120)
    manager._open_position_internal("LONG", Decimal("3000"))
    assert manager.position is not None

    # High hits 3,150 -> TP should trigger at 3,120
    tp_events = manager.process_kline_update(
        time_sec=2000,
        open_price=Decimal("3050"),
        high_price=Decimal("3150"),
        low_price=Decimal("3040"),
        close_price=Decimal("3130"),
        volume=Decimal("50"),
        is_closed=False,
    )
    assert any("take_profit" in ev for ev in tp_events)
    assert manager.position is None
    assert len(manager.fills) == 2
    assert manager.fills[1].reason == "take_profit"
    assert Decimal(manager.realized_pnl) > Decimal("0")
    assert manager.current_equity > manager.starting_equity


def test_paper_streamer_manual_close_and_update_stops() -> None:
    config = LivePaperConfig(
        symbol="BTCUSDT",
        starting_equity=Decimal("10000"),
    )
    manager = LivePaperSessionManager(config)
    manager.is_active = True

    manager._open_position_internal("LONG", Decimal("60000"))
    assert manager.position is not None

    # Update stops
    manager.update_stops(stop_loss=Decimal("59500"), take_profit=Decimal("63000"))
    assert manager.position.stop_loss == "59500"
    assert manager.position.take_profit == "63000"

    # Manual close
    msg = manager.close_position_manual()
    assert "Closed LONG" in msg
    assert manager.position is None
    assert len(manager.fills) == 2
    assert manager.fills[1].reason == "manual_close"


# --- shared rules with the backtest (P1-5) -------------------------------------------


def _signal(side: SignalSide) -> Signal:
    return Signal(
        instrument_id="BTCUSDT",
        side=side,
        bar_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
        reason="test",
    )


def _bars(count: int) -> list[OhlcvBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        OhlcvBar(
            instrument_id="BTCUSDT",
            ts_utc=start + timedelta(minutes=index),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(count)
    ]


def test_unknown_robot_fails_closed_instead_of_becoming_regime() -> None:
    with pytest.raises(ValueError, match="cannot build robot"):
        LivePaperSessionManager(LivePaperConfig(robot="definitely_not_a_robot"))


def test_start_with_unknown_robot_keeps_the_previous_session_config() -> None:
    manager = LivePaperSessionManager(LivePaperConfig(symbol="BTCUSDT"))
    with pytest.raises(ValueError):
        asyncio.run(manager.start(LivePaperConfig(symbol="ETHUSDT", robot="nope")))
    assert manager.config.symbol == "BTCUSDT"
    assert not manager.is_active


def test_opposite_signal_reverses_the_position() -> None:
    manager = LivePaperSessionManager(LivePaperConfig(symbol="BTCUSDT"))
    manager.is_active = True
    manager._open_position_internal("LONG", Decimal("100"))

    manager._apply_signal(_signal(SignalSide.SELL), Decimal("101"))

    assert manager.position is not None
    assert manager.position.side == "SHORT"
    assert [fill.reason for fill in manager.fills][-2] == "signal_exit"


def test_breaker_blocks_the_entry_but_never_the_exit() -> None:
    manager = LivePaperSessionManager(LivePaperConfig(symbol="BTCUSDT"))
    manager.is_active = True
    manager._open_position_internal("LONG", Decimal("100"))
    # A peak far above current equity trips the drawdown breaker.
    manager._peak_equity = manager.current_equity * Decimal("2")

    events = manager._apply_signal(_signal(SignalSide.SELL), Decimal("100"))

    assert manager.position is None, "the long must be closed even with the breaker tripped"
    assert any("Risk blocked entry" in event for event in events)
    assert manager.risk_refusals == {"max drawdown circuit breaker": 1}


def test_closed_bar_reaches_the_robot_once_and_in_order() -> None:
    manager = LivePaperSessionManager(LivePaperConfig(symbol="BTCUSDT"))
    bars = _bars(3)
    assert manager.warm_up(bars) == 3
    # Replayed history (a reconnect re-sends the last closed kline) is ignored.
    assert manager.warm_up(bars[-2:]) == 0
    assert manager._accept_closed_bar(bars[-1]) is False


def test_warm_up_failure_is_a_cold_start_not_a_crash() -> None:
    async def failing(symbol: str, interval: str, count: int) -> list[OhlcvBar]:
        raise OSError("network down")

    manager = LivePaperSessionManager(LivePaperConfig(), history_loader=failing)
    assert asyncio.run(manager._warm_up_from_history()) == 0


# --- new robot coverage: vpin_momentum and formulaic_lgbm -------------------------


def test_vpin_momentum_init_robot_creates_correct_instance() -> None:
    """vpin_momentum must wire a VpinMomentum instance, not fall back to regime."""
    from nautilus_lab.domain.vpin_momentum import VpinMomentum

    manager = LivePaperSessionManager(LivePaperConfig(robot="vpin_momentum"))
    assert isinstance(manager._robot_instance, VpinMomentum)


def test_formulaic_lgbm_init_robot_creates_correct_instance() -> None:
    """formulaic_lgbm must wire a FormulaicLgbmStrategy with the heuristic classifier."""
    from nautilus_lab.domain.formulaic_lgbm_strategy import FormulaicLgbmStrategy

    manager = LivePaperSessionManager(LivePaperConfig(robot="formulaic_lgbm"))
    assert isinstance(manager._robot_instance, FormulaicLgbmStrategy)


def test_vpin_momentum_processes_bar_without_error() -> None:
    """Closed bar fed to vpin_momentum robot must not raise."""
    manager = LivePaperSessionManager(LivePaperConfig(robot="vpin_momentum", symbol="BTCUSDT"))
    bar = _bars(1)[0]
    manager.warm_up([bar])  # must not raise


def test_formulaic_lgbm_processes_bar_without_error() -> None:
    """Closed bar fed to formulaic_lgbm robot must not raise."""
    manager = LivePaperSessionManager(LivePaperConfig(robot="formulaic_lgbm", symbol="BTCUSDT"))
    bars = _bars(60)  # formulaic needs a warm-up window
    manager.warm_up(bars)  # must not raise
