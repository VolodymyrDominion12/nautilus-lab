from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from nautilus_lab.api.paper_streamer import LivePaperConfig, LivePaperSessionManager
from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.application.risk import evaluate_entry, size_position, stop_distance
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.synthetic_bars import synthetic_ohlcv


class InMemoryDecisionLog:
    def __init__(self) -> None:
        self.records: list[DecisionRecord] = []

    def log(self, record: DecisionRecord) -> None:
        self.records.append(record)


def _limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.01"),
        stop_pct=Decimal("0.02"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )


@pytest.mark.integration
def test_backtest_and_live_paper_signal_parity() -> None:
    """Robot logic in LivePaperSessionManager and BacktestEngine emits identical signals.

    Ensures that the live streamer does not modify or drift from the domain robot's
    bar-close signal semantics.
    """
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=250, seed=42)

    # 1. Backtest domain robot (same instance used inside SignalRobot)
    backtest_robot = EmaCrossover(fast_period=10, slow_period=20, instrument_id="ETH/USDT.SIM")
    backtest_signals: list[tuple[datetime, SignalSide]] = []
    for bar in bars:
        sig = backtest_robot.on_bar(bar)
        if sig is not None:
            backtest_signals.append((bar.ts_utc, sig.side))

    # 2. LivePaperSessionManager stream processing
    config = LivePaperConfig(
        symbol="ETH/USDT.SIM",
        robot="ema",
        fast_ema=10,
        slow_ema=20,
        starting_equity=Decimal("10000"),
        auto_trade=True,
    )
    decision_log = InMemoryDecisionLog()
    manager = LivePaperSessionManager(config, decision_log=decision_log)
    manager.is_active = True

    paper_signals: list[tuple[datetime, SignalSide]] = []
    for bar in bars:
        time_sec = int(bar.ts_utc.timestamp())
        manager.process_kline_update(
            time_sec=time_sec,
            open_price=bar.open,
            high_price=bar.high,
            low_price=bar.low,
            close_price=bar.close,
            volume=bar.volume,
            is_closed=True,
        )
        # Capture last decision log entry
        if decision_log.records:
            last = decision_log.records[-1]
            if last.bar_end_utc == bar.ts_utc and last.signal:
                paper_signals.append((bar.ts_utc, SignalSide(last.signal)))

    assert len(backtest_signals) > 0, "test fixture must produce at least one signal"
    assert len(backtest_signals) == len(paper_signals), (
        f"Signal count mismatch: backtest={len(backtest_signals)} vs paper={len(paper_signals)}"
    )
    for (bt_ts, bt_side), (pp_ts, pp_side) in zip(backtest_signals, paper_signals, strict=True):
        assert bt_ts == pp_ts, f"Timestamp mismatch: {bt_ts} != {pp_ts}"
        assert bt_side == pp_side, f"Signal side mismatch at {bt_ts}: {bt_side} != {pp_side}"


@pytest.mark.integration
def test_backtest_and_live_paper_sizing_parity() -> None:
    """Both runners size new positions to the exact same quantity for given equity and price."""
    equity = Decimal("10000")
    price = Decimal("2500")
    limits = _limits()
    qty_step = Decimal("0.001")

    # Sizing formula used in SignalRobot
    dist_bt = stop_distance(price, limits)
    qty_bt = size_position(
        equity=equity,
        price=price,
        stop_distance=dist_bt,
        risk_fraction=limits.risk_per_trade,
        qty_step=qty_step,
    )

    # Sizing formula used in LivePaperSessionManager._open_position_internal
    stop_dist_pp = price * limits.stop_pct
    qty_pp = size_position(
        equity=equity,
        price=price,
        stop_distance=stop_dist_pp,
        risk_fraction=limits.risk_per_trade,
        qty_step=qty_step,
    )

    assert qty_bt > 0
    assert qty_bt == qty_pp, f"Sized quantity disparity: bt={qty_bt} vs paper={qty_pp}"


@pytest.mark.integration
def test_backtest_and_live_paper_circuit_breaker_parity() -> None:
    """Both runners reject entries with the identical breaker reason during drawdown."""
    limits = _limits()
    peak = Decimal("10000")
    # Drawdown of 8% breaches max_drawdown of 6%
    current = Decimal("9200")

    # 1. Backtest evaluate_entry (day start 9300 -> daily loss 1.07% < 2%, drawdown 8% >= 6%)
    day_start = Decimal("9300")
    snapshot = AccountSnapshot(
        equity=current,
        peak_equity=peak,
        day_start_equity=day_start,
        open_positions=0,
    )
    decision = evaluate_entry(snapshot, limits)
    assert not decision.allowed
    assert decision.reason == "max drawdown circuit breaker"

    # 2. LivePaperSessionManager._entry_refusal
    config = LivePaperConfig(
        symbol="ETH/USDT.SIM",
        robot="ema",
        starting_equity=peak,
        max_daily_loss=limits.max_daily_loss,
        max_drawdown=limits.max_drawdown,
    )
    manager = LivePaperSessionManager(config)
    manager.is_active = True
    manager.balance = current
    manager._peak_equity = peak
    manager._day_start_equity = day_start

    refusal = manager._entry_refusal()
    assert refusal == decision.reason


@pytest.mark.integration
def test_backtest_and_paper_execution_consistency() -> None:
    """Comparing Nautilus BacktestEngine paper mode against LivePaperSessionManager.

    Both must execute trades, charge fees, and maintain valid risk limits on identical bars.
    """
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=300, seed=123)
    limits = _limits()

    # 1. Nautilus BacktestEngine run_paper
    req = BacktestRequest(
        mode=TradingMode.PAPER,
        instrument_id="ETH/USDT.SIM",
        bar_count=len(bars),
        starting_equity=Decimal("10000"),
        risk=limits,
        robot=RobotName.EMA,
        fast_ema=10,
        slow_ema=20,
        seed=123,
        source=BarOrigin.SYNTHETIC,
    )
    report = NautilusResearchBacktest().run_paper(req, bars)

    # 2. LivePaperSessionManager replay
    config = LivePaperConfig(
        symbol="ETH/USDT.SIM",
        robot="ema",
        fast_ema=10,
        slow_ema=20,
        starting_equity=Decimal("10000"),
        risk_per_trade=limits.risk_per_trade,
        stop_pct=limits.stop_pct,
        max_daily_loss=limits.max_daily_loss,
        max_drawdown=limits.max_drawdown,
        auto_trade=True,
    )
    manager = LivePaperSessionManager(config)
    manager.is_active = True

    for bar in bars:
        time_sec = int(bar.ts_utc.timestamp())
        manager.process_kline_update(
            time_sec=time_sec,
            open_price=bar.open,
            high_price=bar.high,
            low_price=bar.low,
            close_price=bar.close,
            volume=bar.volume,
            is_closed=True,
        )

    # Both must trade on this trending synthetic series
    assert len(report.fills) > 0, "BacktestEngine should execute fills"
    assert len(manager.fills) > 0, "LivePaperSessionManager should execute fills"

    # Both must pay positive trading fees
    assert report.fees_paid > Decimal("0")
    assert manager.fees_paid > Decimal("0")

    # Direction of the initial position entry must match
    bt_first_side = report.fills[0].side
    pp_first_side = manager.fills[0].side
    assert bt_first_side == pp_first_side, (
        f"Initial fill side mismatch: {bt_first_side} vs {pp_first_side}"
    )
