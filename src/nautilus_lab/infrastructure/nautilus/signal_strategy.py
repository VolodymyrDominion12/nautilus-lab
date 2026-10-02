from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol, cast

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType, OrderBookDepth10, TradeTick
from nautilus_trader.model.enums import AggressorSide, OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.strategy import Strategy

from nautilus_lab.application.decision_narrative import render_narrative
from nautilus_lab.application.decision_trace_codec import (
    legacy_indicators,
    legacy_states,
    record_to_dict,
)
from nautilus_lab.application.risk import (
    RiskBreachTally,
    TradeStats,
    evaluate_entry,
    resolve_risk_fraction,
    size_position,
    stop_distance,
)
from nautilus_lab.domain.adaptive_ema import AdaptiveEmaParams, AdaptiveEmaRouter
from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.decision_log import DecisionRecord
from nautilus_lab.domain.decision_trace import (
    Outcome,
    RecordKind,
    Stage,
    TraceStep,
    TraceValue,
    Verdict,
    blocked_by_label,
    pct_distance,
    step,
)
from nautilus_lab.domain.drawdown_cooldown import PeakState, advance, on_refusal
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.entry_filters import EntryFilter, EntryFilterParams
from nautilus_lab.domain.formulaic_lgbm_strategy import FormulaicLgbmStrategy
from nautilus_lab.domain.marking import OpenLot, marked_equity
from nautilus_lab.domain.meta_label_strategy import MetaLabelStrategy
from nautilus_lab.domain.ml_obi_strategy import MlObiStrategy
from nautilus_lab.domain.ports import DecisionLogPort
from nautilus_lab.domain.position_plan import (
    Holding,
    PositionPlan,
    holding_from_signed_qty,
    plan_for_signal,
    without_reversal,
)
from nautilus_lab.domain.ratchet_stop import RatchetState, initial_ratchet, step_ratchet
from nautilus_lab.domain.regime import RegimeParams, RobotName, require_backtest_support
from nautilus_lab.domain.regime_router import RegimeRouter, parse_legs
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.volatility import VolModel
from nautilus_lab.domain.vpin import BarVpin, VpinModel
from nautilus_lab.domain.vpin_momentum import VpinMomentum
from nautilus_lab.infrastructure.lightgbm_classifier import (
    LightGBMDirectionClassifier,
    LightGBMSuccessClassifier,
    require_model_path,
)
from nautilus_lab.infrastructure.nautilus.bar_convert import to_domain_snapshot
from nautilus_lab.infrastructure.vol_forecast import build_vol_forecaster


class SingleLegRobot(Protocol):
    def on_bar(self, bar: OhlcvBar) -> Signal | None: ...


@dataclass(frozen=True, slots=True)
class _EntryRefusal:
    """Why `_entry_allowed` refused a new entry, in the decision-log vocabulary.

    `code` is a closed token (`max_daily_loss`, `max_drawdown`, `order_working`,
    `sizing`, …) that `blocked_by_label` turns into the structured `blocked_by`
    string; `reason` is the human sentence; `value`/`limit` say how close the
    breaker was — the same shape the live paper terminal records.
    """

    code: str
    reason: str
    value: Decimal | None = None
    limit: Decimal | None = None
    #: The order that made `order_working` refuse, so the log can name it.
    order_id: str | None = None
    order_side: str | None = None


class SignalRobotConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    robot: str = "regime"
    fast_period: int = 10
    slow_period: int = 20
    er_period: int = 20
    trend_ema_period: int = 40
    slope_lookback: int = 10
    enter_trend_er: Decimal = Decimal("0.30")
    exit_trend_er: Decimal = Decimal("0.20")
    donchian_period: int = 20
    bb_period: int = 20
    bb_k: Decimal = Decimal("2")
    regime_confirmation_bars: int = 1
    #: regime's range leg: False = the upper band takes profit instead of shorting.
    range_allow_short: bool = True
    risk_per_trade: Decimal = Decimal("0.005")
    stop_pct: Decimal = Decimal("0.01")
    atr_stop_multiplier: Decimal = Decimal("2")
    max_daily_loss: Decimal = Decimal("0.02")
    max_drawdown: Decimal = Decimal("0.06")
    max_open_positions: int = 1
    kelly_fraction: Decimal = Decimal("0.25")
    max_var_99: Decimal = Decimal("0.05")
    quote_currency: str = "USDT"
    qty_step: Decimal = Decimal("0.001")
    use_bar_vpin: bool = False
    use_tick_vpin: bool = False
    vpin_bucket_volume: Decimal = Decimal("1000")
    vpin_toxic_threshold: Decimal = Decimal("0.7")
    #: Enabled legs of regime / adaptive_ema / meta_label's primary ("" = all).
    regime_legs: str = ""
    use_hawkes: bool = False
    hawkes_baseline: Decimal = Decimal("0.1")
    hawkes_alpha: Decimal = Decimal("0.5")
    hawkes_beta: Decimal = Decimal("1.0")
    hawkes_toxic_threshold: Decimal = Decimal("2.0")
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
    formulaic_model_path: str | None = None
    formulaic_threshold: Decimal = Decimal("0.55")
    meta_label_model_path: str | None = None
    meta_label_threshold: Decimal = Decimal("0.55")
    adaptive_period: int = 40
    adaptive_er_period: int = 20
    adaptive_selectivity: Decimal = Decimal("0.5")
    adaptive_slope_lookback: int = 10
    adaptive_range_allow_short: bool = False
    adaptive_range_exit_at_mean: bool = False
    adaptive_min_bb_width_pct: Decimal = Decimal("0")
    adaptive_hold_trend_in_range: bool = True
    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    vol_model: VolModel = VolModel.HAR
    vol_refit_every: int = 24
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")
    use_ratchet: bool = False
    ratchet_arm_pct: Decimal = Decimal("0.0125")
    use_protective_stop: bool = True
    # Bars that close before this timestamp (ns) only warm indicators; see
    # BacktestRequest.trade_start.
    trade_start_ns: int | None = None
    drawdown_cooldown_days: int = 0
    ml_obi_model_path: str | None = None
    ml_obi_threshold: Decimal = Decimal("0.55")
    # Entry gates (domain/entry_filters.py). All off = the behaviour before they existed.
    filter_htf_trend: bool = False
    filter_htf_ema_period: int = 200
    filter_htf_slope_lookback: int = 24
    filter_vol_expansion: bool = False
    filter_vol_fast_period: int = 24
    filter_vol_slow_period: int = 300
    filter_min_vol_ratio: Decimal = Decimal("1")
    no_instant_reverse: bool = False


class SignalRobot(Strategy):  # type: ignore[misc]
    """Thin Nautilus adapter: domain signal -> risk -> sized order."""

    def __init__(
        self,
        config: SignalRobotConfig,
        *,
        taker_buy_base_volume_by_ns: Mapping[int, Decimal] | None = None,
        decision_log: DecisionLogPort | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(config)
        self.decision_log = decision_log
        self.session_id = session_id
        self._robot = _build_robot(config)
        self._limits = RiskLimits(
            risk_per_trade=config.risk_per_trade,
            stop_pct=config.stop_pct,
            max_daily_loss=config.max_daily_loss,
            max_drawdown=config.max_drawdown,
            max_open_positions=config.max_open_positions,
            kelly_fraction=config.kelly_fraction,
            max_var_99=config.max_var_99,
            atr_stop_multiplier=config.atr_stop_multiplier,
        )
        self._overlay = RiskOverlay(
            use_vol_scaling=config.use_vol_scaling,
            vol_scaling_target=config.vol_scaling_target,
            use_fractional_kelly=config.use_fractional_kelly,
            kelly_min_trades=config.kelly_min_trades,
            use_cvar_breaker=config.use_cvar_breaker,
            max_cvar_99=config.max_cvar_99,
            use_ratchet=config.use_ratchet,
            ratchet_arm_pct=config.ratchet_arm_pct,
            use_protective_stop=config.use_protective_stop,
        )
        self._entry_filter = EntryFilter(
            EntryFilterParams(
                htf_trend=config.filter_htf_trend,
                htf_ema_period=config.filter_htf_ema_period,
                htf_slope_lookback=config.filter_htf_slope_lookback,
                vol_expansion=config.filter_vol_expansion,
                vol_fast_period=config.filter_vol_fast_period,
                vol_slow_period=config.filter_vol_slow_period,
                min_vol_ratio=config.filter_min_vol_ratio,
                no_instant_reverse=config.no_instant_reverse,
            )
        )
        self._previous_ts: datetime | None = None
        self._day_start_equity: Decimal | None = None
        self._peak_equity: Decimal | None = None
        self._peak_state: PeakState | None = None
        self._last_equity_ts: datetime | None = None
        self._day: date | None = None
        self._daily_returns: list[Decimal] = []
        self._equity_curve: list[Decimal] = []
        self._turnover: Decimal = Decimal("0")
        self._returns: list[Decimal] = []
        self._previous_equity: Decimal | None = None
        self._exposure_bars: int = 0
        # Last price the strategy saw (bar close, or book mid). Open positions are
        # marked against it, so equity includes what they are worth right now.
        self._last_mark: Decimal | None = None
        # Resting reduce-only stop for the open position, and the distance the next
        # entry was sized against (consumed when that entry's position opens).
        self._stop_order_id: object | None = None
        self._entry_order_id: object | None = None
        self._pending_stop_distance: Decimal | None = None
        self._trade_stats = TradeStats()
        self._breaches = RiskBreachTally()
        self._atr = AverageTrueRange(14)
        # The forecaster is built once and fed one closed bar at a time; the arch
        # models refit on their own cadence rather than on every bar (see
        # infrastructure/vol_forecast.py for why that cadence is explicit).
        self._vol = build_vol_forecaster(
            self._overlay,
            model=config.vol_model,
            refit_every_bars=config.vol_refit_every,
        )
        self._previous_close: Decimal | None = None
        self._ratchet: RatchetState | None = None
        # Trade-lifecycle state for the decision log (docs/28). An intrabar stop-out is
        # logged against the account and regime the last bar decided on, not the flat
        # book it leaves behind; the stop level travels in `states.stop_loss` so the
        # trade page can draw it; the entry fill records what the venue actually did.
        self._last_account: dict[str, TraceValue] | None = None
        self._last_regime: str = ""
        self._current_bar_ts: datetime | None = None
        self._protective_level: Decimal | None = None
        self._entry_fill_price: Decimal | None = None
        self._entry_fill_qty: Decimal | None = None
        self._entry_fee: Decimal = Decimal("0")
        self._entry_decision_price: Decimal | None = None
        self._entry_decision_ts: datetime | None = None
        self._overlay_steps: list[TraceStep] = []
        self._header_written = False
        # Real per-bar taker split, keyed by bar event timestamp. It travels as a
        # constructor argument rather than a config field because it is data, not a
        # parameter: it must not show up in a strategy config dump, and it is only
        # known once the bars for this run were loaded.
        self._taker_buy_by_ns = (
            None if taker_buy_base_volume_by_ns is None else dict(taker_buy_base_volume_by_ns)
        )
        self._last_tick_ts: datetime | None = None
        self._last_vol_forecast: Decimal | None = None

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)
        if self.config.use_tick_vpin or self.config.use_hawkes:
            self.subscribe_trade_ticks(self.config.instrument_id)
        if self.config.robot == RobotName.ML_OBI.value:
            self.subscribe_order_book_depth(self.config.instrument_id, depth=10)

    def on_trade_tick(self, tick: TradeTick) -> None:
        if not hasattr(self._robot, "on_trade_tick"):
            return

        ts_utc = datetime.fromtimestamp(tick.ts_event / 1_000_000_000, tz=UTC)
        if self._last_tick_ts is None:
            dt_seconds = Decimal("0")
        else:
            dt = (ts_utc - self._last_tick_ts).total_seconds()
            dt_seconds = Decimal(str(dt))
        self._last_tick_ts = ts_utc

        is_buy = tick.aggressor_side == AggressorSide.BUYER
        volume = _as_decimal(tick.size)

        # We rely on structural subtyping (duck typing) since SingleLegRobot
        # doesn't enforce on_trade_tick
        self._robot.on_trade_tick(is_buy=is_buy, volume=volume, dt_seconds=dt_seconds)

    def on_bar(self, bar: Bar) -> None:
        domain_bar = _to_domain_bar(bar, str(self.config.instrument_id))
        if self._taker_buy_by_ns is not None:
            taker_buy = self._taker_buy_by_ns.get(int(bar.ts_event))
            if taker_buy is not None:
                # Enrich before validating so the `taker <= volume` invariant covers the
                # join too: a stale flow series must fail here, not skew the feature.
                domain_bar = replace(domain_bar, taker_buy_base_volume=taker_buy)
        validate_bar(domain_bar, previous_ts=self._previous_ts, now=domain_bar.ts_utc)
        self._previous_ts = domain_bar.ts_utc
        self._atr.update(domain_bar)
        # Fed on every closed bar, warm-up included, so its windows are full by the time
        # the first signal is acted on (same rule as the robot's own legs, B2).
        self._entry_filter.update(domain_bar)
        self._last_vol_forecast = self._vol.update(domain_bar, self._previous_close)
        self._previous_close = domain_bar.close

        signal = self._robot.on_bar(domain_bar)
        self._last_mark = domain_bar.close
        self._current_bar_ts = domain_bar.ts_utc
        self._overlay_steps = []

        trace = getattr(self._robot, "last_trace", ())
        steps = list(trace) if isinstance(trace, (tuple, list)) else []

        if self._warming_up(int(bar.ts_event)):
            self._record_decision_log(domain_bar, signal, Outcome.WARMUP, steps)
            return
        self._track_equity(domain_bar.ts_utc)

        if self._apply_ratchet(domain_bar):
            self._record_decision_log(
                domain_bar, signal, Outcome.RATCHET_EXIT, steps, None, self._overlay_steps
            )
            return

        outcome, blocked_by, execution_steps = self._process_signal(signal, domain_bar.close)
        if outcome is Outcome.NO_SIGNAL and signal is None and _vetoed(steps):
            outcome = Outcome.SIGNAL_VETOED
        self._record_decision_log(
            domain_bar, signal, outcome, steps, blocked_by, self._overlay_steps + execution_steps
        )

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        if not hasattr(self._robot, "on_book"):
            return
        snapshot = to_domain_snapshot(depth, str(self.config.instrument_id))
        signal = self._robot.on_book(snapshot)

        # Book robots have no OhlcvBar, so the ratchet overlay is not applied here; the
        # protective stop still is (it rests on the venue, not in this callback).
        mid_price = (snapshot.bids[0].price + snapshot.asks[0].price) / Decimal("2")
        self._last_mark = mid_price
        if self._warming_up(int(depth.ts_event)):
            return
        self._track_equity(snapshot.ts_utc)

        # Book robots write no per-bar decision record: DecisionRecord requires a bar,
        # and book robots never trigger on_bar in the backtest.
        self._process_signal(signal, mid_price)

    def _place_protective_stop(self, entry_order: object) -> Decimal | None:
        """Rest a reduce-only stop behind a fully filled entry order.

        Driven by the entry's own fill, not by `PositionOpened`: on a NETTING account a
        re-entry after a stop-out reuses the closed position and arrives as
        `PositionChanged`, so a stop hung on `PositionOpened` protected only the first
        trade of a run (the integration test caught a -5,689 USDT open loss that way).
        The order also carries its side, quantity and average fill price, so the
        position cache does not have to be up to date when this runs.
        """
        distance = self._pending_stop_distance
        self._pending_stop_distance = None
        if not self._overlay.use_protective_stop or distance is None or distance <= 0:
            return None
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            return None
        entry_price = _as_decimal(getattr(entry_order, "avg_px", 0))
        quantity = getattr(entry_order, "filled_qty", None)
        if entry_price <= 0 or quantity is None or _as_decimal(quantity) <= 0:
            return None
        is_long = getattr(entry_order, "side", None) == OrderSide.BUY
        trigger = entry_price - distance if is_long else entry_price + distance
        if trigger <= 0:
            self.log.warning(f"Protective stop skipped: trigger {trigger} is not a price")
            return None
        self._cancel_protective_stop()
        stop = self.order_factory.stop_market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL if is_long else OrderSide.BUY,
            quantity=quantity,
            trigger_price=instrument.make_price(trigger),
            reduce_only=True,
        )
        self.submit_order(stop)
        self._stop_order_id = stop.client_order_id
        self._protective_level = _as_decimal(instrument.make_price(trigger))
        return self._protective_level

    def on_position_closed(self, event: object) -> None:
        """Book the trade for the Kelly stats, whoever closed it (signal, ratchet, stop)."""
        if getattr(event, "instrument_id", None) != self.config.instrument_id:
            return
        realized = getattr(event, "realized_pnl", None)
        if realized is not None:
            self._trade_stats.record(_as_decimal(realized))
        # Not the ratchet: on a reversal this event lands after the new entry armed it.
        self._cancel_protective_stop()
        self._protective_level = None

    def on_order_filled(self, event: object) -> None:
        client_order_id = getattr(event, "client_order_id", None)
        if self._stop_order_id is not None and client_order_id == self._stop_order_id:
            self._stop_order_id = None
            self.log.info("Protective stop filled; position closed at the stop")
            self._record_stop_fill(client_order_id, event)
            return
        if self._entry_order_id is None or client_order_id != self._entry_order_id:
            return
        commission = getattr(event, "commission", None)
        if commission is not None:
            self._entry_fee += _as_decimal(commission)
        order = self.cache.order(client_order_id)
        if order is None or not order.is_closed:
            return  # partial fill: wait for the rest, then protect the whole size
        self._entry_order_id = None
        trigger = self._place_protective_stop(order)
        self._record_entry_fill(order, event, trigger)

    def _record_entry_fill(self, order: object, event: object, trigger: Decimal | None) -> None:
        """The entry filled: log the venue's price, size, fee, slippage and the stop level.

        The bar record that submitted the order only knows the bar's close. The fill is
        what the account actually got, and in a bar backtest it can land a whole bar
        later (the 2026-09-29 sweep: `FLAT` + "order already working" on the bar after
        every entry). Logging the fill time against the decision time makes that delay,
        and the slippage it costs, visible per trade.
        """
        price = _as_decimal(getattr(order, "avg_px", 0))
        qty = _as_decimal(getattr(order, "filled_qty", 0))
        is_long = getattr(order, "side", None) == OrderSide.BUY
        self._entry_fill_price = price if price > 0 else None
        self._entry_fill_qty = qty if qty > 0 else None
        fee = self._entry_fee
        self._entry_fee = Decimal("0")
        if self.decision_log is None or self.session_id is None or price <= 0:
            return
        ts = _event_ts(event)
        decision_price = self._entry_decision_price
        slippage_bps = (
            (price - decision_price) / decision_price * Decimal("10000") * (1 if is_long else -1)
            if decision_price is not None and decision_price > 0
            else None
        )
        delay_s = (
            int((ts - self._entry_decision_ts).total_seconds())
            if self._entry_decision_ts is not None
            else None
        )
        steps: list[TraceStep] = [
            step(
                Stage.EXECUTION,
                "fill",
                Verdict.EMIT,
                result="entry_filled",
                values={
                    "side": "LONG" if is_long else "SHORT",
                    "qty": qty,
                    "fill_price": price,
                    "decision_price": decision_price,
                    "slippage_bps": slippage_bps,
                    "fee": fee if fee > 0 else None,
                    "fill_delay_s": delay_s,
                },
                note="slippage_bps > 0 = filled worse than the decision bar's close",
            )
        ]
        if trigger is not None:
            steps.append(
                step(
                    Stage.EXECUTION,
                    "protective_stop",
                    Verdict.EMIT,
                    result="stop_placed",
                    values={
                        "stop_loss": trigger,
                        "risk_per_unit": abs(price - trigger),
                        "risk_pct": pct_distance(trigger, price),
                    },
                )
            )
        record = DecisionRecord(
            bar_end_utc=ts,
            robot=self.config.robot.lower(),
            instrument_id=str(self.config.instrument_id),
            close_price=price,
            regime=self._last_regime,
            signal=None,
            signal_reason=None,
            indicators={},
            states={"stop_loss": str(trigger)} if trigger is not None else {},
            session_id=self.session_id,
            kind=RecordKind.INTRABAR,
            account=self._account_snapshot(),
            steps=tuple(steps),
            outcome=Outcome.ENTRY_FILLED.value,
            config_hash=self._config_hash(),
        )
        record = replace(record, narrative=render_narrative(record_to_dict(record)))
        self.decision_log.log(record)

    def _record_stop_fill(self, client_order_id: object, event: object) -> None:
        """The protective stop filled: record it as an intrabar `STOP_LOSS` decision.

        The stop is a resting reduce-only order the engine triggers mid-bar; without
        this record a research backtest's decision log never shows the exit, so the
        reconstructed trade is read as still-open or as a reversal on the next entry.

        `qty` is converted to `Decimal` for the same reason `price` is: Nautilus hands
        back a `Quantity`, and a raw one inside a `TraceStep` is not a `TraceValue` —
        `json.dumps` then refuses the whole record, so the JSONL writer logged
        "Object of type Quantity is not JSON serializable" and **dropped the exit**
        (seen in the 2026-09-29 sweep: 101 lost records across one 1h run).
        """
        if self.decision_log is None or self.session_id is None:
            return
        order = self.cache.order(client_order_id)
        if order is None:
            return
        price = _as_decimal(getattr(order, "avg_px", 0))
        qty = getattr(order, "filled_qty", None)
        qty_value = None if qty is None else _as_decimal(qty)
        if price <= 0:
            return
        # The stop closes the side opposite the one it is placed on: SELL exits a LONG.
        position_side = "LONG" if getattr(order, "side", None) == OrderSide.SELL else "SHORT"
        ts = _event_ts(event)
        entry = self._entry_fill_price
        gross_pnl = (
            (price - entry) * qty_value * (1 if position_side == "LONG" else -1)
            if entry is not None and qty_value is not None
            else None
        )
        self._entry_fill_price = None
        self._entry_fill_qty = None
        record = DecisionRecord(
            bar_end_utc=ts,
            robot=self.config.robot.lower(),
            instrument_id=str(self.config.instrument_id),
            close_price=price,
            # The regime and account the position was held under: after the stop the
            # book is flat, and a snapshot taken now would say so.
            regime=self._last_regime,
            signal=None,
            signal_reason=None,
            indicators={},
            states={"stop_loss": str(price)},
            session_id=self.session_id,
            kind=RecordKind.INTRABAR,
            account=self._last_account or self._account_snapshot(),
            steps=(
                step(
                    Stage.INTRABAR,
                    "stop_loss",
                    Verdict.EMIT,
                    result="stop_loss",
                    values={
                        "level": price,
                        "side": position_side,
                        "qty": qty_value,
                        "entry_price": entry,
                        "gross_pnl": gross_pnl,
                    },
                ),
            ),
            outcome=Outcome.STOP_LOSS.value,
            config_hash=self._config_hash(),
        )
        record = replace(record, narrative=render_narrative(record_to_dict(record)))
        self.decision_log.log(record)

    def _warming_up(self, ts_event_ns: int) -> bool:
        start = self.config.trade_start_ns
        return start is not None and ts_event_ns < start

    def _track_equity(self, ts_utc: datetime) -> None:
        equity = self._equity()
        if equity is not None:
            self._update_equity_path(ts_utc, equity)
            self._equity_curve.append(equity)
            if self._previous_equity is not None and self._previous_equity > 0:
                self._returns.append((equity - self._previous_equity) / self._previous_equity)
            self._previous_equity = equity
            if not self._is_flat():
                self._exposure_bars += 1

    @staticmethod
    def _plan_step(held: Holding, exit_position: bool, wants_entry: bool) -> TraceStep:
        """The position-plan verdict, mirroring the live paper terminal's step."""
        if exit_position and wants_entry:
            result = "exit_and_enter"
        elif exit_position:
            result = "exit"
        elif wants_entry:
            result = "enter"
        else:
            result = "noop"
        return step(
            Stage.PLAN,
            "position_plan",
            Verdict.PASS,
            result=result,
            values={"holding": held.value, "exit": exit_position, "entry": wants_entry},
        )

    def _account_snapshot(self) -> dict[str, TraceValue]:
        """The account the gates decided on, before this bar's execution changes it.

        Same shape the live paper terminal records (`decision_trace/1`), so the
        narrative and the digest read both without branching.
        """
        equity = self._equity()
        day_start = self._day_start_equity
        peak = self._peak_equity
        day_loss_pct = (
            (day_start - equity) / day_start * Decimal("100")
            if day_start is not None and equity is not None and day_start > 0
            else None
        )
        drawdown_pct = (
            (peak - equity) / peak * Decimal("100")
            if peak is not None and equity is not None and peak > 0
            else None
        )
        holding = self._holding()
        snapshot: dict[str, TraceValue] = {
            "position": holding.value.upper(),
            "equity": equity,
            "day_loss_pct": day_loss_pct,
            "drawdown_pct": drawdown_pct,
        }
        lots = self._open_lots()
        if lots and self._last_mark is not None:
            qty = sum((abs(lot.signed_qty) for lot in lots), Decimal("0"))
            entry = sum((lot.avg_price * abs(lot.signed_qty) for lot in lots), Decimal("0")) / qty
            unrealized = sum(
                ((self._last_mark - lot.avg_price) * lot.signed_qty for lot in lots),
                Decimal("0"),
            )
            snapshot["qty"] = qty
            snapshot["entry_price"] = entry
            snapshot["unrealized_pnl"] = unrealized
        return {k: v for k, v in snapshot.items() if v is not None}

    def _config_hash(self) -> str:
        """Short, stable id of the parameters this run traded with (same config -> same hash)."""
        payload = json.dumps(self.config.dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def _process_signal(
        self, signal: Signal | None, current_price: Decimal
    ) -> tuple[Outcome, str | None, list[TraceStep]]:
        """Exit first (never gated by risk), then — only if allowed — enter.

        The risk layer guards new exposure. An opposite or FLAT signal closes what we
        hold even when every breaker is tripped; see `domain/position_plan.py` for why
        the old "gate first, return on refusal" order froze losing positions.

        Returns the plan/gate/execution steps alongside the outcome, so a research
        backtest's decision log answers "why" with the same detail as a paper session
        (`decision_trace/1`, docs/28).
        """
        if signal is None:
            return Outcome.NO_SIGNAL, None, []
        held = self._holding()
        plan = plan_for_signal(held, signal.side)
        steps: list[TraceStep] = [self._plan_step(held, plan.exit_position, plan.wants_entry)]
        if plan.is_noop:
            return Outcome.HOLD_NOOP, None, steps

        plan, vetoed_by = self._gate_entry(plan, signal.side, steps)
        if plan.is_noop:
            return Outcome.SIGNAL_VETOED, vetoed_by, steps

        # An order from an earlier bar has not filled yet (with a venue latency > 0 a bar
        # backtest fills a market order one bar later, see `_latency_model` in
        # backtest_runner). Acting now would stack a second close on the first:
        # the 2026-09-29 ema BTC log shows a reversal at 15:59, then at 16:59 the same SHORT
        # "closed" again while the first close was in flight — and `_flatten` also dropped
        # the pending entry's id, so that entry filled with no protective stop and no
        # ENTRY_FILLED record. Wait for the fill; the next bar decides on the real book.
        working = self._working_order_id()
        if working is not None:
            steps.append(
                step(
                    Stage.GATE,
                    "execution.order_working",
                    Verdict.INFO,
                    result="order in flight: wait",
                    values={"order_id": str(working)},
                    note="an earlier order has not filled yet; no exit or entry is stacked on it",
                )
            )
            return Outcome.PENDING_FILL, None, steps

        # Gate the entry BEFORE the exit is submitted: the exit's own close order would
        # otherwise count as "an order already working" and block the entry it precedes.
        entry: tuple[Decimal, Decimal] | None = None
        refusal: _EntryRefusal | None = None
        if plan.wants_entry:
            result = self._entry_allowed(current_price, reversing=plan.exit_position)
            if isinstance(result, _EntryRefusal):
                refusal = result
            else:
                entry = result

        if plan.exit_position:
            exit_qty = sum((abs(lot.signed_qty) for lot in self._open_lots()), Decimal("0"))
            self._flatten()
            steps.append(
                step(
                    Stage.EXECUTION,
                    "paper_broker",
                    Verdict.EMIT,
                    result="exit",
                    values={"side": held.value.upper(), "qty": exit_qty, "price": current_price},
                )
            )
            if not plan.wants_entry:
                return Outcome.EXIT, None, steps

        if refusal is not None and refusal.code == "order_working":
            # Not a refusal in the risk sense: the order this robot already sent (usually
            # last bar's entry) has not filled yet. Counting it as "blocked" inflated the
            # sweep's ENTRY_BLOCKED_RISK by one bar per trade.
            steps.append(
                step(
                    Stage.GATE,
                    "execution.order_working",
                    Verdict.INFO,
                    result="order not filled yet",
                    values={"order_id": refusal.order_id, "order_side": refusal.order_side},
                    note="an earlier order is still in flight; no new entry is stacked on it",
                )
            )
            return (Outcome.EXIT if plan.exit_position else Outcome.PENDING_FILL), None, steps

        if refusal is not None:
            blocked_by = blocked_by_label(refusal.code)
            steps.append(
                step(
                    Stage.GATE,
                    blocked_by,
                    Verdict.BLOCK,
                    result=refusal.reason,
                    values={"value": refusal.value},
                    thresholds={"limit": refusal.limit},
                )
            )
            return Outcome.ENTRY_BLOCKED_RISK, blocked_by, steps

        if entry is None:
            return Outcome.NO_SIGNAL, None, steps

        qty, distance = entry
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.log.error("Instrument missing from cache; skip order")
            return Outcome.NO_SIGNAL, None, steps
        desired_buy = signal.side is SignalSide.BUY
        side = "LONG" if desired_buy else "SHORT"
        order = self.order_factory.market(
            self.config.instrument_id,
            OrderSide.BUY if desired_buy else OrderSide.SELL,
            instrument.make_qty(qty),
        )
        self._pending_stop_distance = distance
        self._entry_order_id = order.client_order_id
        self._entry_decision_price = current_price
        self._entry_decision_ts = self._current_bar_ts
        self._entry_fee = Decimal("0")
        self.submit_order(order)
        self._turnover += current_price * qty
        self._arm_ratchet(current_price, SignalSide.BUY if desired_buy else SignalSide.SELL)
        steps.append(
            step(
                Stage.EXECUTION,
                "paper_broker",
                Verdict.EMIT,
                result="entry",
                values={
                    "side": side,
                    "qty": qty,
                    "price": current_price,
                    "stop_distance": distance,
                },
            )
        )

        if plan.exit_position:
            return Outcome.REVERSE, None, steps
        return Outcome.ENTRY_OPENED, None, steps

    def _gate_entry(
        self, plan: PositionPlan, side: SignalSide, steps: list[TraceStep]
    ) -> tuple[PositionPlan, str | None]:
        """Apply the reversal rule and the entry filters to the entry half of `plan`.

        Exits are never touched: a blocked reversal still closes what we hold. Returns
        the (possibly reduced) plan and, when an entry filter refused, `filter.<gate>`.
        """
        params = self._entry_filter.params
        if params.no_instant_reverse:
            reduced = without_reversal(plan)
            if reduced != plan:
                steps.append(
                    step(
                        Stage.PLAN,
                        "no_instant_reverse",
                        Verdict.MODIFY,
                        result="exit only",
                        note="opposite signal closes the position; the reverse entry waits",
                    )
                )
                plan = reduced
        if not plan.wants_entry:
            return plan, None
        verdict = self._entry_filter.evaluate(side)
        steps.extend(verdict.steps)
        if verdict.allowed:
            return plan, None
        return (
            PositionPlan(exit_position=plan.exit_position, wants_entry=False),
            f"filter.{verdict.code}",
        )

    def _entry_allowed(
        self, current_price: Decimal, *, reversing: bool
    ) -> tuple[Decimal, Decimal] | _EntryRefusal:
        """(qty, stop distance) for a new entry, or a structured `_EntryRefusal`."""
        equity = self._equity()
        if equity is None:
            self.log.error("No account equity; skip entry (fail closed)")
            return _EntryRefusal("equity", "No account equity")
        snapshot = AccountSnapshot(
            equity=equity,
            peak_equity=self._peak_equity or equity,
            day_start_equity=self._day_start_equity or equity,
            # A reversal exits first, so the entry lands on a flat book.
            open_positions=0 if reversing or self._is_flat() else 1,
            recent_returns=tuple(self._returns[-30:]),
        )
        decision = evaluate_entry(snapshot, self._limits, self._overlay)
        if not decision.allowed:
            self._breaches.record(decision.reason)
            self._note_refusal(decision.reason)
            self.log.warning(f"Risk blocked entry: {decision.reason}")
            return _EntryRefusal(
                decision.code or "unknown", decision.reason, decision.value, decision.limit
            )

        # An order that is accepted but not yet filled leaves the portfolio flat, so the
        # next signal would stack another entry on top of the pending one. On book-driven
        # robots that ran a 1x-capped size up to ~4x notional (ml_obi), because book
        # updates arrive far faster than the 50ms fill latency. One live entry at a time.
        working = self._working_order_id()
        if working is not None:
            self._breaches.record("order already working")
            order = self.cache.order(working)
            side = getattr(order, "side", None) if order is not None else None
            return _EntryRefusal(
                "order_working",
                "order already working",
                order_id=str(working),
                order_side=None if side is None else ("BUY" if side == OrderSide.BUY else "SELL"),
            )

        distance = stop_distance(current_price, self._limits, atr=self._atr.value)
        risk_fraction = resolve_risk_fraction(
            self._limits,
            self._overlay,
            stats=self._trade_stats,
            forecast_vol=self._last_vol_forecast,
        )
        qty = size_position(
            equity=equity,
            price=current_price,
            stop_distance=distance,
            risk_fraction=risk_fraction,
            qty_step=self.config.qty_step,
        )
        if qty <= 0:
            self.log.warning("Sized quantity is 0; skip order")
            return _EntryRefusal("sizing", "sized quantity is 0")
        return qty, distance

    def on_stop(self) -> None:
        self._flatten()

    @staticmethod
    def _record_regime(signal: Signal | None, steps: list[TraceStep]) -> str:
        if signal is not None and getattr(signal, "regime", None) is not None:
            return getattr(signal.regime, "value", "UNKNOWN")
        for item in steps:
            if item.stage is Stage.REGIME and item.result:
                return item.result
        if steps and all(item.stage is Stage.WARMUP for item in steps):
            return "WARMUP"
        # A robot without a regime classifier (ema, formulaic_lgbm, …) has no regime to
        # report; "UNKNOWN" on every bar read as "the classifier failed" in the digest.
        return ""

    def _write_run_header(self, bar: OhlcvBar) -> None:
        """Once per run, before the first record: the parameters every record used to repeat.

        Dated with the first bar (not the wall clock): the writer files by record date, and
        a header dated today would sort after a backtest's history as its "newest" row.
        """
        if self._header_written or self.decision_log is None or self.session_id is None:
            return
        self._header_written = True
        record = DecisionRecord(
            bar_end_utc=bar.ts_utc,
            robot=self.config.robot.lower(),
            instrument_id=bar.instrument_id,
            close_price=bar.close,
            regime="",
            signal=None,
            signal_reason=None,
            indicators={},
            states={},
            session_id=self.session_id,
            kind=RecordKind.RUN_HEADER,
            outcome=Outcome.RUN_HEADER.value,
            config_hash=self._config_hash(),
            params={k: str(v) for k, v in self.config.dict().items()},
        )
        record = replace(record, narrative=render_narrative(record_to_dict(record)))
        self.decision_log.log(record)

    def _record_decision_log(
        self,
        bar: OhlcvBar,
        signal: Signal | None,
        outcome: Outcome,
        steps: list[TraceStep],
        blocked_by: str | None = None,
        execution_steps: list[TraceStep] | None = None,
    ) -> None:
        if self.decision_log is None or self.session_id is None:
            return
        self._write_run_header(bar)

        all_steps = tuple(steps) + tuple(execution_steps or ())
        regime = self._record_regime(signal, steps)
        account = self._account_snapshot()
        states: dict[str, object] = dict(legacy_states(all_steps))
        stop_level = self._current_stop_level()
        if stop_level is not None and outcome not in _CLOSING_OUTCOMES:
            states["stop_loss"] = str(stop_level)
        self._last_account = account
        if regime not in ("", "WARMUP"):
            self._last_regime = regime
        record = DecisionRecord(
            bar_end_utc=bar.ts_utc,
            robot=self.config.robot.lower(),
            instrument_id=bar.instrument_id,
            close_price=bar.close,
            regime=regime,
            signal=signal.side.value if signal else None,
            signal_reason=signal.reason if signal else None,
            indicators=legacy_indicators(all_steps),
            states=states,
            session_id=self.session_id,
            bar={"o": bar.open, "h": bar.high, "l": bar.low, "c": bar.close, "v": bar.volume},
            account=account,
            steps=all_steps,
            outcome=outcome.value,
            blocked_by=blocked_by,
            # Fills are not traced per-bar in backtest decisions: they live in BacktestReport.
            fill_ids=(),
            config_hash=self._config_hash(),
        )
        record = replace(record, narrative=render_narrative(record_to_dict(record)))
        self.decision_log.log(record)

    def _current_stop_level(self) -> Decimal | None:
        """The stop that binds the open position: the tighter of the venue stop and the ratchet."""
        if self._is_flat():
            return None
        levels = [
            level
            for level in (
                self._protective_level,
                self._ratchet.stop_price if self._ratchet is not None else None,
            )
            if level is not None
        ]
        if not levels:
            return None
        return max(levels) if self._holding() is Holding.LONG else min(levels)

    @property
    def equity_curve(self) -> tuple[Decimal, ...]:
        return tuple(self._equity_curve)

    @property
    def turnover(self) -> Decimal:
        return self._turnover

    @property
    def exposure_pct(self) -> Decimal | None:
        bars = len(self._equity_curve)
        if bars == 0:
            return None
        return Decimal(self._exposure_bars) / Decimal(bars)

    @property
    def risk_breaches(self) -> tuple[tuple[str, int], ...]:
        """Circuit-breaker refusals by reason, in the order they first fired."""
        return self._breaches.summary()

    def _flatten(self) -> None:
        """Cancel resting orders (the protective stop among them), then close."""
        self._ratchet = None
        self._pending_stop_distance = None
        self._entry_order_id = None
        self._cancel_protective_stop()
        if not self._is_flat():
            self.close_all_positions(self.config.instrument_id)

    def _cancel_protective_stop(self) -> None:
        stop_id = self._stop_order_id
        self._stop_order_id = None
        if stop_id is None:
            return
        order = self.cache.order(stop_id)
        if order is not None and not order.is_closed:
            self.cancel_order(order)

    def _apply_ratchet(self, bar: OhlcvBar) -> bool:
        """Run the overlay stop. True = flattened this bar; skip the robot's action."""
        if not self._overlay.use_ratchet:
            return False
        if self._is_flat() or self._ratchet is None:
            self._ratchet = None
            return False
        params = self._overlay.ratchet_params(stop_pct=self._limits.stop_pct)
        previous = self._ratchet
        self._ratchet, hit = step_ratchet(self._ratchet, bar, params)
        level = previous.stop_price if self._ratchet is None else self._ratchet.stop_price
        moved = self._ratchet is not None and self._ratchet.stop_price != previous.stop_price
        self._overlay_steps.append(
            step(
                Stage.PLAN,
                "ratchet",
                Verdict.EMIT if hit else Verdict.INFO,
                result="exit" if hit else ("tightened" if moved else "hold"),
                values={
                    "stop": level,
                    "prior_stop": previous.stop_price,
                    "armed": previous.armed if self._ratchet is None else self._ratchet.armed,
                    "close": bar.close,
                    "adverse": bar.low if previous.side is SignalSide.BUY else bar.high,
                    "dist_to_stop_pct": pct_distance(bar.close, level),
                },
                thresholds={"entry_price": previous.entry_price},
                note=(
                    "stop touched: flatten at this close (the exit is a market order, "
                    "not a fill at the stop level)"
                    if hit
                    else None
                ),
            )
        )
        if not hit:
            return False
        held = self._holding()
        exit_qty = sum((abs(lot.signed_qty) for lot in self._open_lots()), Decimal("0"))
        self._flatten()
        self._overlay_steps.append(
            step(
                Stage.EXECUTION,
                "paper_broker",
                Verdict.EMIT,
                result="exit",
                values={"side": held.value.upper(), "qty": exit_qty, "price": bar.close},
            )
        )
        return True

    def _arm_ratchet(self, entry_price: Decimal, side: SignalSide) -> None:
        if not self._overlay.use_ratchet:
            return
        self._ratchet = initial_ratchet(
            entry_price=entry_price,
            side=side,
            params=self._overlay.ratchet_params(stop_pct=self._limits.stop_pct),
            atr_distance=self._atr.value,
        )

    def _is_flat(self) -> bool:
        return bool(self.portfolio.is_flat(self.config.instrument_id))

    def _open_lots(self) -> list[OpenLot]:
        instrument_id = str(self.config.instrument_id)
        return [
            OpenLot(
                instrument_id=instrument_id,
                signed_qty=_as_decimal(position.signed_qty),
                avg_price=_as_decimal(position.avg_px_open),
            )
            for position in self.cache.positions_open(instrument_id=self.config.instrument_id)
        ]

    def _holding(self) -> Holding:
        return holding_from_signed_qty(
            sum((lot.signed_qty for lot in self._open_lots()), Decimal("0"))
        )

    def _has_working_order(self) -> bool:
        return self._working_order_id() is not None

    def _working_order_id(self) -> object | None:
        """True while a non-stop order for this instrument is submitted but not closed.

        `cache.orders_open()` alone is not enough: in a backtest an order is INFLIGHT
        (sitting in the risk/exec engine) well before it is OPEN, and `Portfolio` only
        shows a position once the fill lands. With 100ms book updates against 50ms fill
        latency the strategy saw `flat=True` while two of its own orders were still in
        flight and stacked thirteen entries into one second — roughly 4x the 1x notional
        cap that `size_position` is supposed to enforce.

        The resting protective stop is open for the whole life of a position; counting
        it would block every reversal, so it is excluded by id.
        """
        instrument_id = self.config.instrument_id
        stop_id = self._stop_order_id
        for order in self.cache.orders_open(instrument_id=instrument_id):
            if order.client_order_id != stop_id:
                return cast(object, order.client_order_id)
        inflight = self.cache.client_order_ids_inflight(instrument_id=instrument_id)
        return next((oid for oid in inflight if oid != stop_id), None)

    def _equity(self) -> Decimal | None:
        """Account balance plus open positions marked at the last price seen.

        On a MARGIN account `balance_total` moves only on realized PnL and fees, so on
        its own it hides every open loss from the curve and from the breakers.
        """
        quote = Currency.from_str(self.config.quote_currency)
        account = self.cache.account_for_venue(self.config.instrument_id.venue)
        if account is None:
            return None
        total = account.balance_total(quote)
        if total is None:
            return None
        balance = _as_decimal(total)
        if self._last_mark is None:
            return balance
        return marked_equity(
            balance,
            self._open_lots(),
            {str(self.config.instrument_id): self._last_mark},
        )

    def _update_equity_path(self, ts_utc: datetime, equity: Decimal) -> None:
        day = ts_utc.date()
        if self._day != day:
            if (
                self._day is not None
                and self._day_start_equity is not None
                and self._day_start_equity > 0
            ):
                self._daily_returns.append(
                    (equity - self._day_start_equity) / self._day_start_equity
                )
            self._day = day
            self._day_start_equity = equity
        state = self._peak_state or PeakState(peak=equity)
        self._peak_state = advance(
            state,
            equity=equity,
            now=ts_utc,
            cooldown_days=self.config.drawdown_cooldown_days,
        )
        self._peak_equity = self._peak_state.peak
        self._last_equity_ts = ts_utc

    def _note_refusal(self, reason: str) -> None:
        if self._peak_state is not None and self._last_equity_ts is not None:
            self._peak_state = on_refusal(self._peak_state, reason=reason, now=self._last_equity_ts)

    @property
    def daily_returns(self) -> tuple[Decimal, ...]:
        return tuple(self._daily_returns)


#: Outcomes after which the bar's position is being closed: no stop level is carried.
_CLOSING_OUTCOMES = frozenset({Outcome.EXIT, Outcome.RATCHET_EXIT})


def _vetoed(steps: list[TraceStep]) -> bool:
    """True when a filter or strategy step inside the robot blocked its own signal."""
    return any(
        item.verdict is Verdict.BLOCK and item.stage in (Stage.FILTER, Stage.STRATEGY)
        for item in steps
    )


def _event_ts(event: object) -> datetime:
    ts_ns = getattr(event, "ts_event", None)
    if ts_ns is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(int(ts_ns) / 1_000_000_000, tz=UTC)


def _build_robot(config: SignalRobotConfig) -> SingleLegRobot:
    robot = RobotName(config.robot)
    require_backtest_support(robot)
    instrument_id = str(config.instrument_id)
    if robot is RobotName.EMA:
        return EmaCrossover(
            instrument_id=instrument_id,
            fast_period=config.fast_period,
            slow_period=config.slow_period,
        )
    if robot is RobotName.VPIN_MOMENTUM:
        vpin: VpinModel | None = None
        if config.use_tick_vpin:
            from nautilus_lab.domain.vpin import TickVpin

            vpin = TickVpin(
                bucket_volume=config.vpin_bucket_volume,
                toxic_threshold=config.vpin_toxic_threshold,
            )
        else:
            vpin = BarVpin(
                bucket_volume=config.vpin_bucket_volume,
                toxic_threshold=config.vpin_toxic_threshold,
            )
        return VpinMomentum(
            instrument_id=instrument_id,
            vpin=vpin,
            ema_period=config.vpin_momentum_ema_period,
            atr_multiple=config.vpin_momentum_atr_multiple,
        )
    if robot is RobotName.FORMULAIC_LGBM:
        classifier = _build_classifier(config.formulaic_model_path, robot="formulaic_lgbm")
        return FormulaicLgbmStrategy(
            instrument_id=instrument_id,
            classifier=classifier,
            threshold=config.formulaic_threshold,
        )
    if robot is RobotName.ADAPTIVE_EMA:
        return AdaptiveEmaRouter(
            instrument_id=instrument_id,
            params=AdaptiveEmaParams(
                base_period=config.adaptive_period,
                er_period=config.adaptive_er_period,
                selectivity=config.adaptive_selectivity,
                slope_lookback=config.adaptive_slope_lookback,
                enter_trend_er=config.enter_trend_er,
                exit_trend_er=config.exit_trend_er,
                donchian_period=config.donchian_period,
                bb_period=config.bb_period,
                bb_k=config.bb_k,
                range_allow_short=config.adaptive_range_allow_short,
                range_exit_at_mean=config.adaptive_range_exit_at_mean,
                min_bb_width_pct=config.adaptive_min_bb_width_pct,
                hold_trend_in_range=config.adaptive_hold_trend_in_range,
            ),
            legs=parse_legs(config.regime_legs),
        )
    if robot is RobotName.META_LABEL:
        model_path = require_model_path(config.meta_label_model_path, robot="meta_label")
        return MetaLabelStrategy(
            instrument_id=instrument_id,
            primary=_regime_primary(config, instrument_id),
            classifier=LightGBMSuccessClassifier(model_path=model_path),
            threshold=config.meta_label_threshold,
        )
    if robot is RobotName.ML_OBI:
        classifier = _build_classifier(config.ml_obi_model_path, robot="ml_obi")
        return MlObiStrategy(
            instrument_id=instrument_id,
            classifier=classifier,
            threshold=config.ml_obi_threshold,
        )
    return _regime_primary(config, instrument_id)


def _regime_primary(config: SignalRobotConfig, instrument_id: str) -> RegimeRouter:
    vpin: VpinModel | None = None
    if config.use_tick_vpin:
        from nautilus_lab.domain.vpin import TickVpin

        vpin = TickVpin(
            bucket_volume=config.vpin_bucket_volume,
            toxic_threshold=config.vpin_toxic_threshold,
        )
    elif config.use_bar_vpin:
        vpin = BarVpin(
            bucket_volume=config.vpin_bucket_volume,
            toxic_threshold=config.vpin_toxic_threshold,
        )

    hawkes = None
    if config.use_hawkes:
        from nautilus_lab.domain.hawkes import ExponentialHawkes

        hawkes = ExponentialHawkes(
            baseline=config.hawkes_baseline,
            alpha=config.hawkes_alpha,
            beta=config.hawkes_beta,
            toxic_threshold=config.hawkes_toxic_threshold,
        )

    return RegimeRouter(
        instrument_id=instrument_id,
        params=RegimeParams(
            er_period=config.er_period,
            trend_ema_period=config.trend_ema_period,
            slope_lookback=config.slope_lookback,
            enter_trend_er=config.enter_trend_er,
            exit_trend_er=config.exit_trend_er,
            donchian_period=config.donchian_period,
            bb_period=config.bb_period,
            bb_k=config.bb_k,
            confirmation_bars=config.regime_confirmation_bars,
            range_allow_short=config.range_allow_short,
        ),
        vpin=vpin,
        hawkes=hawkes,
        legs=parse_legs(config.regime_legs),
    )


def _build_classifier(model_path: str | None, *, robot: str) -> LightGBMDirectionClassifier:
    """Fail closed without a booster (audit A3).

    The old fallback to `HeuristicDirectionClassifier` let `formulaic_lgbm`/`ml_obi`
    trade a hand-written OBI rule under the ML robot's name: 80 fills on 1h bars with
    no model at all, reported as that robot's result. `meta_label` already refused.
    """
    return LightGBMDirectionClassifier(model_path=require_model_path(model_path, robot=robot))


def _to_domain_bar(bar: Bar, instrument_id: str) -> OhlcvBar:
    ts = datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=UTC)
    return OhlcvBar(
        instrument_id=instrument_id,
        ts_utc=ts,
        open=_as_decimal(bar.open),
        high=_as_decimal(bar.high),
        low=_as_decimal(bar.low),
        close=_as_decimal(bar.close),
        volume=_as_decimal(bar.volume),
    )


def _as_decimal(value: object) -> Decimal:
    converter = getattr(value, "as_decimal", None)
    if callable(converter):
        converted = converter()
        return converted if isinstance(converted, Decimal) else Decimal(str(converted))
    return Decimal(str(value))
