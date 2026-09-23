from __future__ import annotations

from decimal import Decimal

from nautilus_lab.api.paper_streamer import (
    LivePaperConfig,
    LivePaperSessionManager,
)


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
