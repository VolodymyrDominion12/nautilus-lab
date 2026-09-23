"""Real-time paper trading session manager with live market data streaming.

Coordinates:
- Ingesting live klines from Binance WebSocket (or synthetic fallback for offline/testing)
- Feeding closed bars to the domain robot without lookahead bias
- Tracking active position (entry price, size, mark price, floating PnL)
- Visualizing and executing Stop-Loss (SL) and Take-Profit (TP) triggers
- Maintaining equity curve history and fills ledger
- Broadcasting updates via FastAPI WebSockets to the frontend terminal
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import WebSocket

from nautilus_lab.application.risk import (
    size_position,
)
from nautilus_lab.domain.adaptive_ema import AdaptiveEmaParams, AdaptiveEmaRouter
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.signals import SignalSide

logger = logging.getLogger(__name__)

BINANCE_WS_STREAM_URL = "wss://stream.binance.com:9443/ws"


@dataclass
class LivePaperConfig:
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    robot: str = "regime"
    starting_equity: Decimal = Decimal("10000")
    risk_per_trade: Decimal = Decimal("0.01")  # 1% per trade
    stop_pct: Decimal = Decimal("0.015")  # 1.5% stop loss
    take_profit_multiple: Decimal = Decimal("2.0")  # 2x stop distance = 3%
    mode: str = "paper"  # "paper" or "live_guarded"
    auto_trade: bool = True
    maker_fee: Decimal = Decimal("0.0002")
    taker_fee: Decimal = Decimal("0.0005")
    qty_step: Decimal = Decimal("0.001")


@dataclass
class LivePosition:
    symbol: str
    side: str  # "LONG" or "SHORT"
    qty: str
    entry_price: str
    entry_time: str
    mark_price: str
    unrealized_pnl: str
    unrealized_pnl_pct: str
    stop_loss: str | None = None
    take_profit: str | None = None


@dataclass
class LiveFill:
    id: str
    ts: str
    symbol: str
    side: str  # "BUY" or "SELL"
    qty: str
    price: str
    fee: str
    realized_pnl: str
    reason: str  # "signal_entry", "stop_loss", "take_profit", "manual_close"


@dataclass
class LiveBar:
    time: int  # Unix timestamp in seconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


@dataclass
class LiveEquityPoint:
    time: int
    equity: float
    realized_pnl: float
    unrealized_pnl: float


class LivePaperSessionManager:
    """Manages an active real-time paper trading session."""

    def __init__(self, config: LivePaperConfig | None = None) -> None:
        self.config = config or LivePaperConfig()
        self.is_active = False
        self.starting_equity = self.config.starting_equity
        self.balance = self.config.starting_equity
        self.realized_pnl = Decimal("0")
        self.fees_paid = Decimal("0")
        self.position: LivePosition | None = None
        self._pos_entry_price = Decimal("0")
        self._pos_qty = Decimal("0")
        self._pos_side = ""
        self._pos_sl: Decimal | None = None
        self._pos_tp: Decimal | None = None
        self.fills: list[LiveFill] = []
        self.equity_history: list[LiveEquityPoint] = []
        self.recent_bars: list[LiveBar] = []
        self.subscribers: set[WebSocket] = set()
        self._ws_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._robot_instance: Any = None
        self._last_mark_price: Decimal | None = None
        self.status_message = "Idle"
        self._init_robot()

    def _init_robot(self) -> None:
        name = self.config.robot.lower()
        if name == "ema":
            self._robot_instance = EmaCrossover(
                instrument_id=self.config.symbol,
                fast_period=10,
                slow_period=20,
            )
        elif name == "adaptive_ema":
            self._robot_instance = AdaptiveEmaRouter(
                instrument_id=self.config.symbol,
                params=AdaptiveEmaParams(),
            )
        else:
            self._robot_instance = RegimeRouter(
                instrument_id=self.config.symbol,
                params=RegimeParams(),
            )

    @property
    def current_equity(self) -> Decimal:
        floating = self.unrealized_pnl
        return self.balance + floating

    @property
    def unrealized_pnl(self) -> Decimal:
        if not self.position or not self._last_mark_price:
            return Decimal("0")
        if self._pos_side == "LONG":
            return (self._last_mark_price - self._pos_entry_price) * self._pos_qty
        if self._pos_side == "SHORT":
            return (self._pos_entry_price - self._last_mark_price) * self._pos_qty
        return Decimal("0")

    def to_state_dict(self) -> dict[str, Any]:
        """Snapshot of the session for REST or WebSocket message."""
        floating = self.unrealized_pnl
        equity = self.current_equity
        return {
            "is_active": self.is_active,
            "mode": self.config.mode,
            "config": {
                "symbol": self.config.symbol,
                "interval": self.config.interval,
                "robot": self.config.robot,
                "starting_equity": str(self.config.starting_equity),
                "risk_per_trade": str(self.config.risk_per_trade),
                "stop_pct": str(self.config.stop_pct),
                "take_profit_multiple": str(self.config.take_profit_multiple),
                "auto_trade": self.config.auto_trade,
            },
            "starting_equity": str(self.starting_equity),
            "current_balance": str(self.balance),
            "current_equity": str(equity),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(floating),
            "fees_paid": str(self.fees_paid),
            "position": asdict(self.position) if self.position else None,
            "fills": [asdict(f) for f in self.fills[-50:]],
            "equity_history": [asdict(p) for p in self.equity_history[-100:]],
            "recent_bars": [asdict(b) for b in self.recent_bars[-100:]],
            "last_price": str(self._last_mark_price) if self._last_mark_price else None,
            "last_update_ts": datetime.now(UTC).isoformat(),
            "status_message": self.status_message,
        }

    async def broadcast_state(self) -> None:
        """Broadcast state to all active subscribers."""
        if not self.subscribers:
            return
        payload = {"type": "STATE_UPDATE", "data": self.to_state_dict()}
        message = json.dumps(payload)
        dead = []
        for ws in self.subscribers:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subscribers.discard(ws)

    async def broadcast_bar(self, bar: LiveBar) -> None:
        """Broadcast single bar update for responsive chart rendering."""
        if not self.subscribers:
            return
        payload = {
            "type": "BAR_UPDATE",
            "data": asdict(bar),
            "last_price": str(self._last_mark_price) if self._last_mark_price else None,
            "unrealized_pnl": str(self.unrealized_pnl),
            "current_equity": str(self.current_equity),
            "position": asdict(self.position) if self.position else None,
        }
        message = json.dumps(payload)
        dead = []
        for ws in self.subscribers:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subscribers.discard(ws)

    def process_kline_update(
        self,
        *,
        time_sec: int,
        open_price: Decimal,
        high_price: Decimal,
        low_price: Decimal,
        close_price: Decimal,
        volume: Decimal,
        is_closed: bool,
        taker_buy_volume: Decimal | None = None,
    ) -> list[str]:
        """Process incoming kline update. Returns list of triggered event descriptions."""
        events: list[str] = []
        self._last_mark_price = close_price

        # Update or append bar
        current_bar = LiveBar(
            time=time_sec,
            open=float(open_price),
            high=float(high_price),
            low=float(low_price),
            close=float(close_price),
            volume=float(volume),
            is_closed=is_closed,
        )
        if self.recent_bars and self.recent_bars[-1].time == time_sec:
            self.recent_bars[-1] = current_bar
        else:
            self.recent_bars.append(current_bar)
            if len(self.recent_bars) > 500:
                self.recent_bars.pop(0)

        # 1. Check Stop Loss / Take Profit for open position
        if self.position is not None:
            # Update floating PnL display
            float_pnl = self.unrealized_pnl
            notional = self._pos_entry_price * self._pos_qty
            float_pct = (float_pnl / notional * Decimal("100")) if notional > 0 else Decimal("0")
            self.position.mark_price = str(close_price)
            self.position.unrealized_pnl = str(float_pnl)
            self.position.unrealized_pnl_pct = f"{float_pct:.2f}%"

            # Check stops against bar extremes
            if self._pos_side == "LONG":
                if self._pos_sl is not None and low_price <= self._pos_sl:
                    events.append(self._close_position_internal(self._pos_sl, "stop_loss"))
                elif self._pos_tp is not None and high_price >= self._pos_tp:
                    events.append(self._close_position_internal(self._pos_tp, "take_profit"))
            elif self._pos_side == "SHORT":
                if self._pos_sl is not None and high_price >= self._pos_sl:
                    events.append(self._close_position_internal(self._pos_sl, "stop_loss"))
                elif self._pos_tp is not None and low_price <= self._pos_tp:
                    events.append(self._close_position_internal(self._pos_tp, "take_profit"))

        # 2. On bar close: evaluate domain robot signal
        if is_closed:
            bar_obj = OhlcvBar(
                instrument_id=self.config.symbol,
                ts_utc=datetime.fromtimestamp(time_sec, tz=UTC),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
                taker_buy_base_volume=taker_buy_volume,
            )

            # Record equity snapshot
            eq = self.current_equity
            self.equity_history.append(
                LiveEquityPoint(
                    time=time_sec,
                    equity=float(eq),
                    realized_pnl=float(self.realized_pnl),
                    unrealized_pnl=float(self.unrealized_pnl),
                )
            )
            if len(self.equity_history) > 500:
                self.equity_history.pop(0)

            if self.is_active and self.config.auto_trade:
                signal = self._robot_instance.on_bar(bar_obj)
                if signal is not None:
                    events.append(f"Robot signal: {signal.side.value}")
                    if self.position is None:
                        if signal.side is SignalSide.BUY:
                            events.append(self._open_position_internal("LONG", close_price))
                        elif signal.side is SignalSide.SELL:
                            events.append(self._open_position_internal("SHORT", close_price))
                    elif signal.side is SignalSide.FLAT:
                        events.append(self._close_position_internal(close_price, "signal_exit"))

        return events

    def _open_position_internal(self, side: str, price: Decimal) -> str:
        """Open a virtual position."""
        if price <= Decimal("0"):
            return "Failed to open: invalid price"

        # Risk parameters
        risk_fraction = self.config.risk_per_trade
        stop_pct = self.config.stop_pct
        stop_dist = price * stop_pct
        if stop_dist <= Decimal("0"):
            stop_dist = price * Decimal("0.01")

        qty = size_position(
            equity=self.balance,
            price=price,
            stop_distance=stop_dist,
            risk_fraction=risk_fraction,
            qty_step=self.config.qty_step,
        )
        if qty <= Decimal("0"):
            msg = f"Skipped entry {side}: sized quantity is 0"
            self.status_message = msg
            return msg

        entry_fee = price * qty * self.config.taker_fee
        self.balance -= entry_fee
        self.fees_paid += entry_fee

        tp_distance = stop_dist * self.config.take_profit_multiple
        if side == "LONG":
            sl_price = price - stop_dist
            tp_price = price + tp_distance
        else:
            sl_price = price + stop_dist
            tp_price = price - tp_distance

        self._pos_side = side
        self._pos_entry_price = price
        self._pos_qty = qty
        self._pos_sl = sl_price
        self._pos_tp = tp_price

        self.position = LivePosition(
            symbol=self.config.symbol,
            side=side,
            qty=str(qty),
            entry_price=str(price),
            entry_time=datetime.now(UTC).strftime("%H:%M:%S"),
            mark_price=str(price),
            unrealized_pnl="0.00",
            unrealized_pnl_pct="0.00%",
            stop_loss=str(sl_price),
            take_profit=str(tp_price),
        )

        fill = LiveFill(
            id=str(uuid.uuid4())[:8],
            ts=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            symbol=self.config.symbol,
            side="BUY" if side == "LONG" else "SELL",
            qty=str(qty),
            price=str(price),
            fee=f"{entry_fee:.4f}",
            realized_pnl="0.00",
            reason=f"Open {side} (SL: {sl_price:.2f}, TP: {tp_price:.2f})",
        )
        self.fills.append(fill)
        msg = f"Opened {side} {qty} @ {price} (SL={sl_price:.2f}, TP={tp_price:.2f})"
        self.status_message = msg
        return msg

    def _close_position_internal(self, exit_price: Decimal, reason: str) -> str:
        """Close virtual position and realize PnL."""
        if not self.position:
            return "No open position to close"

        qty = self._pos_qty
        entry_price = self._pos_entry_price
        side = self._pos_side

        if side == "LONG":
            raw_pnl = (exit_price - entry_price) * qty
        else:
            raw_pnl = (entry_price - exit_price) * qty

        exit_fee = exit_price * qty * self.config.taker_fee
        net_pnl = raw_pnl - exit_fee

        self.balance += net_pnl
        self.realized_pnl += net_pnl
        self.fees_paid += exit_fee

        fill = LiveFill(
            id=str(uuid.uuid4())[:8],
            ts=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            symbol=self.config.symbol,
            side="SELL" if side == "LONG" else "BUY",
            qty=str(qty),
            price=str(exit_price),
            fee=f"{exit_fee:.4f}",
            realized_pnl=f"{net_pnl:+.2f}",
            reason=reason,
        )
        self.fills.append(fill)

        msg = f"Closed {side} {qty} @ {exit_price} | PnL: {net_pnl:+.2f} ({reason})"
        self.status_message = msg
        self.position = None
        self._pos_entry_price = Decimal("0")
        self._pos_qty = Decimal("0")
        self._pos_side = ""
        self._pos_sl = None
        self._pos_tp = None
        return msg

    def close_position_manual(self) -> str:
        """Manually flatten position at current mark price."""
        if not self.position:
            return "No active position"
        mark = self._last_mark_price or self._pos_entry_price
        return self._close_position_internal(mark, "manual_close")

    def update_stops(self, stop_loss: Decimal | None, take_profit: Decimal | None) -> str:
        """Update Stop Loss and Take Profit levels."""
        if not self.position:
            return "No active position to update stops"
        self._pos_sl = stop_loss
        self._pos_tp = take_profit
        self.position.stop_loss = str(stop_loss) if stop_loss else None
        self.position.take_profit = str(take_profit) if take_profit else None
        msg = f"Updated stops: SL={stop_loss}, TP={take_profit}"
        self.status_message = msg
        return msg

    async def start(self, config: LivePaperConfig) -> None:
        """Start the live paper session."""
        self.config = config
        self.is_active = True
        self.starting_equity = config.starting_equity
        self.balance = config.starting_equity
        self.realized_pnl = Decimal("0")
        self.fees_paid = Decimal("0")
        self.position = None
        self._pos_entry_price = Decimal("0")
        self._pos_qty = Decimal("0")
        self._pos_side = ""
        self._pos_sl = None
        self._pos_tp = None
        self.fills.clear()
        self.equity_history.clear()
        self._stop_event.clear()
        self._init_robot()
        self.status_message = f"Live Paper active ({config.symbol}, {config.robot})"

        # Start WebSocket receiver task
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        self._ws_task = asyncio.create_task(self._run_binance_stream())
        await self.broadcast_state()

    async def stop(self) -> None:
        """Stop the live paper session."""
        self.is_active = False
        self._stop_event.set()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        self.status_message = "Session stopped"
        await self.broadcast_state()

    async def _run_binance_stream(self) -> None:
        """Connect to Binance public WebSocket stream and parse klines."""
        import websockets

        stream_name = f"{self.config.symbol.lower()}@kline_{self.config.interval}"
        url = f"{BINANCE_WS_STREAM_URL}/{stream_name}"
        logger.info("Connecting to Binance WS: %s", url)

        backoff = 1
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    backoff = 1
                    logger.info("Connected to Binance stream %s", stream_name)
                    while not self._stop_event.is_set():
                        raw_msg = await ws.recv()
                        data = json.loads(raw_msg)
                        kline = data.get("k")
                        if not kline:
                            continue

                        time_sec = int(kline["t"]) // 1000
                        open_p = Decimal(str(kline["o"]))
                        high_p = Decimal(str(kline["h"]))
                        low_p = Decimal(str(kline["l"]))
                        close_p = Decimal(str(kline["c"]))
                        volume_p = Decimal(str(kline["v"]))
                        is_closed = bool(kline["x"])
                        taker_buy_vol = Decimal(str(kline.get("V", 0))) if "V" in kline else None

                        events = self.process_kline_update(
                            time_sec=time_sec,
                            open_price=open_p,
                            high_price=high_p,
                            low_price=low_p,
                            close_price=close_p,
                            volume=volume_p,
                            is_closed=is_closed,
                            taker_buy_volume=taker_buy_vol,
                        )

                        # Broadcast bar update
                        if self.recent_bars:
                            await self.broadcast_bar(self.recent_bars[-1])

                        if events or is_closed:
                            await self.broadcast_state()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Binance WS error: %s. Reconnecting in %ss...", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


# Global singleton instance for the FastAPI application
LIVE_PAPER_SESSION = LivePaperSessionManager()
