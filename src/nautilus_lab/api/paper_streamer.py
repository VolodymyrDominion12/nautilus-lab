"""Real-time paper trading session manager with live market data streaming.

Coordinates:
- Ingesting live klines from Binance WebSocket (or synthetic fallback for offline/testing)
- Feeding closed bars to the domain robot without lookahead bias
- Tracking active position (entry price, size, mark price, floating PnL)
- Visualizing and executing Stop-Loss (SL) and Take-Profit (TP) triggers
- Maintaining equity curve history and fills ledger
- Broadcasting updates via FastAPI WebSockets to the frontend terminal

Shared rules with the backtest (not a second, looser rulebook):
- the robot is built from the same parameters the research runs use, and an unknown
  robot name fails closed instead of silently becoming `regime`;
- a signal is turned into exit/entry intent by `domain.position_plan`: an opposite or
  FLAT signal always exits, and only the new entry goes through `evaluate_entry`;
- equity for sizing and for the breakers is balance plus the open position marked at
  the last price (`domain.marking`);
- a closed candle is fed to the robot once, in order (`validate_bar`), and the robot is
  warmed on recent closed history before it may trade.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

from nautilus_lab.application.risk import (
    evaluate_entry,
    size_position,
)
from nautilus_lab.domain.adaptive_ema import AdaptiveEmaParams, AdaptiveEmaRouter
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.buy_and_hold import HOLD_ROBOT, BuyAndHold
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.errors import InvalidBarError
from nautilus_lab.domain.formulaic_lgbm_strategy import FormulaicLgbmStrategy
from nautilus_lab.domain.ports import DecisionLogPort
from nautilus_lab.domain.position_plan import Holding, plan_for_signal
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.vpin import BarVpin
from nautilus_lab.domain.vpin_momentum import VpinMomentum
from nautilus_lab.infrastructure.lightgbm_classifier import HeuristicDirectionClassifier
from nautilus_lab.infrastructure.live_paper_journal import (
    FILL,
    SESSION_RESUME,
    SESSION_START,
    SESSION_STOP,
    SNAPSHOT,
    LivePaperJournal,
    ResumableSession,
)
from nautilus_lab.infrastructure.provenance import code_manifest

if TYPE_CHECKING:
    from nautilus_lab.api.market_feed import FeedHub

logger = logging.getLogger(__name__)

BINANCE_WS_STREAM_URL = "wss://stream.binance.com:9443/ws"

#: Robots the live terminal can build. Anything else is refused: the terminal used to
#: fall back to `regime` for an unknown name while the UI kept showing the name asked for.
LIVE_PAPER_ROBOTS: frozenset[str] = frozenset(
    {"regime", "ema", "adaptive_ema", "vpin_momentum", "formulaic_lgbm", HOLD_ROBOT}
)

#: Closed candles replayed into the robot before a session may trade. Regime needs ~150
#: bars before it emits anything; starting cold meant hours of silence on 1m bars.
WARMUP_BARS = 300

#: Loads recent closed bars for warm-up: (symbol, interval, count) -> bars, oldest first.
HistoryLoader = Callable[[str, str, int], Awaitable[list[OhlcvBar]]]


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
    # Same parameters and breakers the research runs use; the API fills them from
    # Settings so the terminal rehearses the configuration that was actually tested.
    fast_ema: int = 10
    slow_ema: int = 20
    regime: RegimeParams = field(default_factory=RegimeParams)
    adaptive: AdaptiveEmaParams = field(default_factory=AdaptiveEmaParams)
    max_daily_loss: Decimal = Decimal("0.02")
    max_drawdown: Decimal = Decimal("0.06")
    # Identity of the session in a portfolio of several: a stable human name
    # ("regime-eth"), the hypothesis it tests, and where it was started from.
    name: str = ""
    notes: str = ""
    created_from: str = "ui"


def default_session_name(robot: str, symbol: str, interval: str) -> str:
    """`regime-eth`, `ema-btc-15m`: stable names for sessions nobody named."""
    base = symbol.upper().removesuffix("USDT").lower() or symbol.lower()
    name = f"{robot}-{base}"
    return name if interval == "1h" else f"{name}-{interval}"


def parse_kline_message(raw: str | bytes) -> dict[str, Any] | None:
    """Keyword arguments for `process_kline_update` from one Binance kline message."""
    data = json.loads(raw)
    kline = data.get("k") if isinstance(data, dict) else None
    if not isinstance(kline, dict):
        return None
    return {
        "time_sec": int(kline["t"]) // 1000,
        "open_price": Decimal(str(kline["o"])),
        "high_price": Decimal(str(kline["h"])),
        "low_price": Decimal(str(kline["l"])),
        "close_price": Decimal(str(kline["c"])),
        "volume": Decimal(str(kline["v"])),
        "is_closed": bool(kline["x"]),
        "taker_buy_volume": Decimal(str(kline["V"])) if "V" in kline else None,
    }


def _plain(value: object) -> object:
    """JSON-safe copy: Decimals become strings (never floats), dataclasses become dicts."""
    if isinstance(value, Decimal):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    return value


def _coerce_like(default: object, raw: object) -> object:
    """Rebuild a journalled value with the type of the field's default."""
    if isinstance(default, bool):
        return raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true"}
    if isinstance(default, Decimal):
        return Decimal(str(raw))
    if isinstance(default, int):
        return int(str(raw))
    return raw


def _field_values(cls: type[object], raw: object) -> dict[str, Any]:
    """Keyword arguments for dataclass `cls` from a journalled dict, typed like its defaults."""
    if not isinstance(raw, dict):
        return {}
    template = cls()
    known = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    return {
        str(name): _coerce_like(getattr(template, str(name)), value)
        for name, value in raw.items()
        if name in known
    }


def config_to_dict(config: LivePaperConfig) -> dict[str, Any]:
    """The frozen configuration a session trades with, as written to the journal."""
    result = _plain(config)
    assert isinstance(result, dict)
    return result


def config_from_dict(raw: dict[str, Any]) -> LivePaperConfig:
    """Inverse of `config_to_dict`. Unknown keys are ignored, missing ones default.

    A resumed session must trade with the parameters it *started* with, not with
    whatever `.env` says after a redeploy — otherwise one ledger would mix two robots.
    """
    values = _field_values(LivePaperConfig, raw)
    if "regime" in raw:
        values["regime"] = RegimeParams(**_field_values(RegimeParams, raw["regime"]))
    if "adaptive" in raw:
        values["adaptive"] = AdaptiveEmaParams(**_field_values(AdaptiveEmaParams, raw["adaptive"]))
    return LivePaperConfig(**values)


def _decimal_or_none(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return Decimal(str(raw))


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

    def __init__(
        self,
        config: LivePaperConfig | None = None,
        *,
        history_loader: HistoryLoader | None = None,
        journal: LivePaperJournal | None = None,
        feed_hub: FeedHub | None = None,
        decision_log: DecisionLogPort | None = None,
    ) -> None:
        self.config = config or LivePaperConfig()
        self._history_loader = history_loader
        self.journal = journal
        self.decision_log = decision_log
        #: Failed journal writes since start, and whether the latest write failed. The
        #: health checks and the watchdog read these (api/health.py, docs/27 E-1.6).
        self.journal_errors = 0
        self.journal_failing = False
        #: Shared market data. Several sessions on one symbol+interval read one socket;
        #: without a hub the session opens its own (single-session mode, tests).
        self.feed_hub = feed_hub
        #: Paused = no new entries. Exits, stops and the robot's indicators keep running.
        self.paused = False
        self.session_id: str | None = None
        self.started_at: str | None = None
        self.resumed_at: str | None = None
        #: Last closed bar the restored snapshot had seen. Bars after it arrived while
        #: the process was down; their highs/lows are checked against the stops once.
        self._resume_after_ts: datetime | None = None
        self._last_closed_ts: datetime | None = None
        self._peak_equity = self.config.starting_equity
        self._day_start_equity = self.config.starting_equity
        self._day: object | None = None
        self.risk_refusals: dict[str, int] = {}
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
        if name not in LIVE_PAPER_ROBOTS:
            supported = ", ".join(sorted(LIVE_PAPER_ROBOTS))
            raise ValueError(
                f"live paper cannot build robot {self.config.robot!r}; supported: {supported}. "
                "Refusing rather than substituting a different robot."
            )
        if name == HOLD_ROBOT:
            self._robot_instance = BuyAndHold(instrument_id=self.config.symbol)
        elif name == "ema":
            self._robot_instance = EmaCrossover(
                instrument_id=self.config.symbol,
                fast_period=self.config.fast_ema,
                slow_period=self.config.slow_ema,
            )
        elif name == "adaptive_ema":
            self._robot_instance = AdaptiveEmaRouter(
                instrument_id=self.config.symbol,
                params=self.config.adaptive,
            )
        elif name == "vpin_momentum":
            vpin = BarVpin(
                bucket_volume=Decimal("1000"),
                toxic_threshold=Decimal("0.7"),
            )
            self._robot_instance = VpinMomentum(
                instrument_id=self.config.symbol,
                vpin=vpin,
                ema_period=20,
                atr_multiple=Decimal("1.5"),
            )
        elif name == "formulaic_lgbm":
            # Paper mode uses the heuristic classifier (rule-based fallback) because
            # training a LightGBM model on live data is an offline step. The heuristic
            # still exercises the full signal path: features → threshold gate → entry.
            self._robot_instance = FormulaicLgbmStrategy(
                instrument_id=self.config.symbol,
                classifier=HeuristicDirectionClassifier(),
                threshold=Decimal("0.55"),
            )
        else:  # "regime" and any future additions that default to regime logic
            self._robot_instance = RegimeRouter(
                instrument_id=self.config.symbol,
                params=self.config.regime,
            )
        self._last_closed_ts = None

    def warm_up(self, bars: list[OhlcvBar]) -> int:
        """Feed closed history to the robot without trading. Returns bars consumed."""
        consumed = 0
        for bar in bars:
            if self._accept_closed_bar(bar):
                self._robot_instance.on_bar(bar)
                self._remember_bar(bar)
                consumed += 1
        return consumed

    def _remember_bar(self, bar: OhlcvBar) -> None:
        """Warm-up history also fills the chart, which was empty after every restart."""
        live = LiveBar(
            time=int(bar.ts_utc.timestamp()),
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
            is_closed=True,
        )
        if self.recent_bars and self.recent_bars[-1].time >= live.time:
            return
        self.recent_bars.append(live)
        if len(self.recent_bars) > 500:
            self.recent_bars.pop(0)
        if self._last_mark_price is None:
            self._last_mark_price = bar.close

    def _accept_closed_bar(self, bar: OhlcvBar) -> bool:
        """True once per closed candle, in time order.

        Binance re-sends the final `x=true` kline after a reconnect, and the warm-up
        history overlaps the first live candles; feeding either twice would advance the
        robot's indicators by a bar that did not happen.
        """
        if self._last_closed_ts is not None and bar.ts_utc <= self._last_closed_ts:
            return False
        try:
            validate_bar(bar, previous_ts=self._last_closed_ts, now=bar.ts_utc)
        except InvalidBarError as exc:
            logger.warning("Dropping invalid closed bar %s: %s", bar.ts_utc, exc)
            return False
        self._last_closed_ts = bar.ts_utc
        return True

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
            "paused": self.paused,
            "name": self.config.name,
            "notes": self.config.notes,
            "created_from": self.config.created_from,
            "risk_refusals": dict(self.risk_refusals),
            "last_bar_ts": None
            if self._last_closed_ts is None
            else self._last_closed_ts.isoformat(),
            "session_id": self.session_id,
            "started_at": self.started_at,
            "resumed_at": self.resumed_at,
            "persisted": self.journal is not None,
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

            events.extend(self._check_stops(high_price, low_price))

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

            # The robot sees every closed candle exactly once, trading or not, so its
            # indicators stay in step with the market while auto-trade is off.
            if self._accept_closed_bar(bar_obj):
                self._roll_equity_marks(bar_obj.ts_utc)
                signal = self._robot_instance.on_bar(bar_obj)
                self._record_decision_log(bar_obj, signal)
                if signal is not None and self.is_active and self.config.auto_trade:
                    events.extend(self._apply_signal(signal, close_price))

        if self.is_active and (is_closed or events):
            self._journal_snapshot(
                equity_point=self.equity_history[-1] if is_closed and self.equity_history else None
            )
        return events

    def _record_decision_log(self, bar: OhlcvBar, signal: Signal | None) -> None:
        if self.decision_log is None:
            return

        robot_name = self.config.robot.lower()
        indicators: dict[str, Any] = {}
        states: dict[str, Any] = {}

        if robot_name == "ema":
            indicators["fast"] = self._robot_instance.fast_value
            indicators["slow"] = self._robot_instance.slow_value
        elif robot_name == "vpin_momentum":
            indicators["ema"] = self._robot_instance.last_ema_value
            indicators["atr"] = self._robot_instance.last_atr
            vpin_state = self._robot_instance.last_vpin_state
            if vpin_state:
                states["vpin"] = str(vpin_state.value)
                states["vpin_toxic"] = str(vpin_state.toxic)
        elif hasattr(self._robot_instance, "last_snapshot"):
            snap = self._robot_instance.last_snapshot
            if snap is not None:
                if hasattr(snap, "fast_ema"):
                    indicators["fast"] = snap.fast_ema
                if hasattr(snap, "slow_ema"):
                    indicators["slow"] = snap.slow_ema
                if hasattr(snap, "hawkes"):
                    states["hawkes"] = snap.hawkes
                if hasattr(snap, "vpin"):
                    states["vpin"] = snap.vpin

        # Handle RegimeRouter properties
        last_reg = getattr(self._robot_instance, "last_effective_regime", None)
        if hasattr(self._robot_instance, "last_effective_regime"):
            # RegimeRouter specifics
            states["effective_regime"] = last_reg.value if last_reg else None
            if self._robot_instance.last_vpin_state:
                states["vpin_filter"] = str(self._robot_instance.last_vpin_state.value)
                states["vpin_toxic"] = str(self._robot_instance.last_vpin_state.toxic)
            if self._robot_instance.last_hawkes_state:
                states["hawkes_filter"] = str(self._robot_instance.last_hawkes_state.value)
                states["hawkes_toxic"] = str(self._robot_instance.last_hawkes_state.toxic)

        eff_reg = last_reg.value if last_reg else "UNKNOWN"

        record = DecisionRecord(
            bar_end_utc=bar.ts_utc,
            robot=robot_name,
            instrument_id=bar.instrument_id,
            close_price=bar.close,
            regime=signal.regime.value if signal and signal.regime else eff_reg,
            signal=signal.side.value if signal else None,
            signal_reason=signal.reason if signal else None,
            indicators={k: str(v) for k, v in indicators.items() if v is not None},
            states={k: v for k, v in states.items() if v is not None},
            # The session is the key the log is filed under, so the dashboard can ask for
            # this session's decisions and get only those (routes/live.py).
            session_id=self.session_id,
        )
        self.decision_log.log(record)

    def _check_stops(
        self, high_price: Decimal, low_price: Decimal, *, ts: datetime | None = None
    ) -> list[str]:
        """Close the position if this bar's range touched its stop or target."""
        if self.position is None:
            return []
        if self._pos_side == "LONG":
            if self._pos_sl is not None and low_price <= self._pos_sl:
                return [self._close_position_internal(self._pos_sl, "stop_loss", ts=ts)]
            if self._pos_tp is not None and high_price >= self._pos_tp:
                return [self._close_position_internal(self._pos_tp, "take_profit", ts=ts)]
        elif self._pos_side == "SHORT":
            if self._pos_sl is not None and high_price >= self._pos_sl:
                return [self._close_position_internal(self._pos_sl, "stop_loss", ts=ts)]
            if self._pos_tp is not None and low_price <= self._pos_tp:
                return [self._close_position_internal(self._pos_tp, "take_profit", ts=ts)]
        return []

    def _holding(self) -> Holding:
        if self.position is None:
            return Holding.FLAT
        return Holding.LONG if self._pos_side == "LONG" else Holding.SHORT

    def _apply_signal(self, signal: Signal, price: Decimal) -> list[str]:
        """Exit first (never gated), then enter only if the risk gate allows it."""
        events = [f"Robot signal: {signal.side.value}"]
        plan = plan_for_signal(self._holding(), signal.side)
        if plan.exit_position:
            events.append(self._close_position_internal(price, "signal_exit"))
        if plan.wants_entry and self.paused:
            msg = "Paused: entry skipped"
            self.status_message = msg
            events.append(msg)
        elif plan.wants_entry:
            refusal = self._entry_refusal()
            if refusal is not None:
                self.risk_refusals[refusal] = self.risk_refusals.get(refusal, 0) + 1
                msg = f"Risk blocked entry: {refusal}"
                self.status_message = msg
                events.append(msg)
            else:
                side = "LONG" if signal.side is SignalSide.BUY else "SHORT"
                events.append(self._open_position_internal(side, price))
        return events

    def _limits(self) -> RiskLimits:
        return RiskLimits(
            risk_per_trade=self.config.risk_per_trade,
            stop_pct=self.config.stop_pct,
            max_daily_loss=self.config.max_daily_loss,
            max_drawdown=self.config.max_drawdown,
        )

    def _roll_equity_marks(self, ts: datetime) -> None:
        equity = self.current_equity
        day = ts.date()
        if self._day != day:
            self._day = day
            self._day_start_equity = equity
        self._peak_equity = max(self._peak_equity, equity)

    def _entry_refusal(self) -> str | None:
        equity = self.current_equity
        decision = evaluate_entry(
            AccountSnapshot(
                equity=equity,
                peak_equity=max(self._peak_equity, equity),
                day_start_equity=self._day_start_equity,
                open_positions=0,
            ),
            self._limits(),
        )
        return None if decision.allowed else decision.reason

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

        is_hold = self.config.robot.lower() == HOLD_ROBOT
        if is_hold:
            # The benchmark holds the whole account (entry fee included), no risk fraction.
            step = self.config.qty_step
            raw_qty = self.current_equity / (price * (Decimal("1") + self.config.taker_fee))
            qty = (raw_qty / step).to_integral_value(rounding="ROUND_FLOOR") * step
        else:
            qty = size_position(
                # Marked equity, like the backtest: an open loss shrinks the next size.
                equity=self.current_equity,
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
        sl_price: Decimal | None
        tp_price: Decimal | None
        if is_hold:
            sl_price = tp_price = None
        elif side == "LONG":
            sl_price = price - stop_dist
            tp_price = price + tp_distance
        else:
            sl_price = price + stop_dist
            tp_price = price - tp_distance
        levels = (
            "no stop, benchmark"
            if sl_price is None or tp_price is None
            else f"SL: {sl_price:.2f}, TP: {tp_price:.2f}"
        )

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
            stop_loss=None if sl_price is None else str(sl_price),
            take_profit=None if tp_price is None else str(tp_price),
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
            reason=f"Open {side} ({levels})",
        )
        self.fills.append(fill)
        self._journal_fill(fill)
        msg = f"Opened {side} {qty} @ {price} ({levels})"
        self.status_message = msg
        return msg

    def _close_position_internal(
        self, exit_price: Decimal, reason: str, *, ts: datetime | None = None
    ) -> str:
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
            ts=(ts or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S"),
            symbol=self.config.symbol,
            side="SELL" if side == "LONG" else "BUY",
            qty=str(qty),
            price=str(exit_price),
            fee=f"{exit_fee:.4f}",
            realized_pnl=f"{net_pnl:+.2f}",
            reason=reason,
        )
        self.fills.append(fill)
        self._journal_fill(fill)

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
        msg = self._close_position_internal(mark, "manual_close")
        self._journal_snapshot()
        return msg

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
        self._journal_snapshot()
        return msg

    async def start(self, config: LivePaperConfig, *, session_id: str | None = None) -> None:
        """Start the live paper session. Raises ValueError for a robot it cannot build."""
        previous = self.config
        self.config = config
        try:
            self._init_robot()
        except ValueError:
            self.config = previous
            raise
        self.is_active = True
        self.starting_equity = config.starting_equity
        self.balance = config.starting_equity
        self.realized_pnl = Decimal("0")
        self.fees_paid = Decimal("0")
        self._clear_position()
        self.fills.clear()
        self.equity_history.clear()
        self.risk_refusals.clear()
        self._peak_equity = config.starting_equity
        self._day_start_equity = config.starting_equity
        self._day = None
        self._resume_after_ts = None
        self.paused = False
        self.recent_bars.clear()
        self._last_mark_price = None
        self._stop_event.clear()
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.started_at = datetime.now(UTC).isoformat()
        self.resumed_at = None
        self.status_message = f"Live Paper active ({config.symbol}, {config.robot})"
        self._journal_event(
            SESSION_START,
            {
                "started_at": self.started_at,
                "config": config_to_dict(config),
                # Which code books this ledger (docs/27 E-1.4). A resume after a deploy
                # can run newer code: that is recorded by SESSION_RESUME below.
                "provenance": code_manifest().as_dict(),
            },
        )
        self._journal_snapshot()
        self._launch_stream()
        await self.broadcast_state()

    async def resume(self, session: ResumableSession) -> None:
        """Continue a session the process did not stop on purpose (deploy, crash, reboot).

        The account (balance, fees, breaker marks, open position with its stops) comes
        back from the last snapshot; the robot's indicators are rebuilt by the usual
        warm-up on closed history. Bars that closed while the process was down are
        checked once against the restored stop and target — a stop that was hit during
        the outage is filled at its level, not silently skipped.
        """
        config = config_from_dict(session.config)
        previous = self.config
        self.config = config
        try:
            self._init_robot()
        except ValueError:
            self.config = previous
            raise
        snap = session.snapshot or {}
        self.session_id = session.session_id
        self.started_at = session.started_at
        self.resumed_at = datetime.now(UTC).isoformat()
        self.starting_equity = config.starting_equity
        self.balance = _decimal_or_none(snap.get("balance")) or config.starting_equity
        self.realized_pnl = _decimal_or_none(snap.get("realized_pnl")) or Decimal("0")
        self.fees_paid = _decimal_or_none(snap.get("fees_paid")) or Decimal("0")
        self._peak_equity = _decimal_or_none(snap.get("peak_equity")) or self.balance
        self._day_start_equity = _decimal_or_none(snap.get("day_start_equity")) or self.balance
        raw_day = snap.get("day")
        self._day = date.fromisoformat(raw_day) if isinstance(raw_day, str) and raw_day else None
        self.risk_refusals = {str(k): int(v) for k, v in (snap.get("risk_refusals") or {}).items()}
        self.paused = bool(snap.get("paused", False))
        self._last_mark_price = _decimal_or_none(snap.get("last_mark_price"))
        raw_last = snap.get("last_closed_ts")
        self._resume_after_ts = (
            datetime.fromisoformat(raw_last) if isinstance(raw_last, str) and raw_last else None
        )
        self._clear_position()
        self._restore_position(snap.get("position"))
        self.fills = [LiveFill(**fill) for fill in session.fills]
        self.equity_history = [LiveEquityPoint(**point) for point in session.equity_points]
        self.is_active = True
        self._stop_event.clear()
        self.status_message = (
            f"Live Paper resumed ({config.symbol}, {config.robot}); session {self.session_id}"
        )
        # A deploy resumes the session under new code; one ledger may then span several
        # revisions, and the report has to be able to say where each part came from.
        self._journal_event(
            SESSION_RESUME,
            {"resumed_at": self.resumed_at, "provenance": code_manifest().as_dict()},
        )
        logger.info("Resumed live paper session %s", self.session_id)
        self._launch_stream()
        await self.broadcast_state()

    def _launch_stream(self) -> None:
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        if self.feed_hub is not None:
            self._ws_task = asyncio.create_task(self._join_feed())
        else:
            self._ws_task = asyncio.create_task(self._run_binance_stream())

    async def _join_feed(self) -> None:
        """Warm up on history first, then take live bars from the shared feed.

        In this order, so a live closed bar can never reach the robot before the
        history it follows (`_accept_closed_bar` would then reject the whole warm-up).
        """
        await self._announce_warm_up()
        if self.feed_hub is not None and self.is_active:
            self.feed_hub.subscribe(self)

    async def on_market_update(self, update: Mapping[str, Any]) -> None:
        """One kline message from the feed: book it, then tell the browsers."""
        events = self.process_kline_update(**update)
        if self.recent_bars:
            await self.broadcast_bar(self.recent_bars[-1])
        if events or update.get("is_closed"):
            await self.broadcast_state()

    async def _announce_warm_up(self) -> None:
        warmed = await self._warm_up_from_history()
        if warmed:
            self.status_message = (
                f"Live Paper active ({self.config.symbol}, {self.config.robot}); "
                f"robot warmed on {warmed} closed bars"
            )
            await self.broadcast_state()

    def _clear_position(self) -> None:
        self.position = None
        self._pos_entry_price = Decimal("0")
        self._pos_qty = Decimal("0")
        self._pos_side = ""
        self._pos_sl = None
        self._pos_tp = None

    def _restore_position(self, raw: object) -> None:
        if not isinstance(raw, dict) or raw.get("side") not in {"LONG", "SHORT"}:
            return
        entry = Decimal(str(raw["entry_price"]))
        qty = Decimal(str(raw["qty"]))
        self._pos_side = str(raw["side"])
        self._pos_entry_price = entry
        self._pos_qty = qty
        self._pos_sl = _decimal_or_none(raw.get("stop_loss"))
        self._pos_tp = _decimal_or_none(raw.get("take_profit"))
        mark = self._last_mark_price or entry
        self.position = LivePosition(
            symbol=self.config.symbol,
            side=self._pos_side,
            qty=str(qty),
            entry_price=str(entry),
            entry_time=str(raw.get("entry_time") or ""),
            mark_price=str(mark),
            unrealized_pnl=str(self.unrealized_pnl),
            unrealized_pnl_pct="0.00%",
            stop_loss=None if self._pos_sl is None else str(self._pos_sl),
            take_profit=None if self._pos_tp is None else str(self._pos_tp),
        )

    # ------------------------------------------------------------------ journal
    def _journal_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.journal is None or self.session_id is None:
            return
        try:
            self.journal.append(event_type, self.session_id, payload)
        except OSError as exc:
            # A full disk must not take the trading loop down with it; say so loudly.
            logger.error("Live paper journal write failed (%s): %s", event_type, exc)
            self.status_message = f"Journal write failed: {exc}"
            self.journal_errors += 1
            self.journal_failing = True
        else:
            self.journal_failing = False

    def _journal_fill(self, fill: LiveFill) -> None:
        self._journal_event(FILL, {"fill": asdict(fill)})

    def _journal_snapshot(self, *, equity_point: LiveEquityPoint | None = None) -> None:
        position = None
        if self.position is not None:
            position = {
                "side": self._pos_side,
                "qty": str(self._pos_qty),
                "entry_price": str(self._pos_entry_price),
                "entry_time": self.position.entry_time,
                "stop_loss": None if self._pos_sl is None else str(self._pos_sl),
                "take_profit": None if self._pos_tp is None else str(self._pos_tp),
            }
        self._journal_event(
            SNAPSHOT,
            {
                "balance": str(self.balance),
                "equity": str(self.current_equity),
                "realized_pnl": str(self.realized_pnl),
                "unrealized_pnl": str(self.unrealized_pnl),
                "fees_paid": str(self.fees_paid),
                "peak_equity": str(self._peak_equity),
                "day_start_equity": str(self._day_start_equity),
                "day": self._day.isoformat() if isinstance(self._day, date) else None,
                "risk_refusals": dict(self.risk_refusals),
                "paused": self.paused,
                "last_closed_ts": (
                    None if self._last_closed_ts is None else self._last_closed_ts.isoformat()
                ),
                "last_mark_price": (
                    None if self._last_mark_price is None else str(self._last_mark_price)
                ),
                "position": position,
                "equity_point": None if equity_point is None else asdict(equity_point),
            },
        )

    # ------------------------------------------------------------------ warm-up
    async def _warm_up_from_history(self) -> int:
        if self._history_loader is None:
            return 0
        try:
            bars = await self._history_loader(self.config.symbol, self.config.interval, WARMUP_BARS)
        except Exception as exc:  # network, rate limit: a cold start, not a failure
            logger.warning("Live paper warm-up failed, starting cold: %s", exc)
            return 0
        self._settle_missed_bars(bars)
        return self.warm_up(bars)

    def _settle_missed_bars(self, bars: list[OhlcvBar]) -> list[str]:
        """After a resume: check the stops against bars that closed while we were down."""
        cutoff = self._resume_after_ts
        self._resume_after_ts = None
        if cutoff is None or self.position is None:
            return []
        events: list[str] = []
        for bar in bars:
            if bar.ts_utc <= cutoff or self.position is None:
                continue
            self._last_mark_price = bar.close
            events.extend(self._check_stops(bar.high, bar.low, ts=bar.ts_utc))
        if events:
            self.status_message = "While offline: " + "; ".join(events)
            self._journal_snapshot()
        return events

    async def stop(self) -> None:
        """Stop the live paper session. Only a person does this: a stopped session is
        final in the journal and is not resumed after a restart."""
        was_active = self.is_active
        self.is_active = False
        self._stop_event.set()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        if self.feed_hub is not None:
            self.feed_hub.unsubscribe(self)
        if was_active:
            self._journal_snapshot()
            self._journal_event(SESSION_STOP, {"stopped_at": datetime.now(UTC).isoformat()})
        self.status_message = "Session stopped"
        await self.broadcast_state()

    async def _run_binance_stream(self) -> None:
        """Single-session mode: this session's own socket (no shared feed hub)."""
        import websockets

        await self._announce_warm_up()
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
                        update = parse_kline_message(await ws.recv())
                        if update is not None:
                            await self.on_market_update(update)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Binance WS error: %s. Reconnecting in %ss...", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


async def binance_history_loader(symbol: str, interval: str, count: int) -> list[OhlcvBar]:
    """Recent CLOSED klines from the public REST API, oldest first (no API keys)."""
    from datetime import timedelta

    from nautilus_lab.infrastructure.binance_klines import BinancePublicKlines
    from nautilus_lab.infrastructure.http_resilience import ResilientJsonClient

    seconds = INTERVAL_SECONDS.get(interval)
    if seconds is None:
        return []
    end = datetime.now(UTC)
    start = end - timedelta(seconds=seconds * count)
    feed = BinancePublicKlines(ResilientJsonClient())
    return await asyncio.to_thread(
        feed.fetch,
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        instrument_id=symbol,
    )
