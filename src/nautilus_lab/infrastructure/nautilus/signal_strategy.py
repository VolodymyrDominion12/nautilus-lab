from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType, OrderBookDepth10, TradeTick
from nautilus_trader.model.enums import AggressorSide, OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.strategy import Strategy

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
from nautilus_lab.domain.drawdown_cooldown import PeakState, advance, on_refusal
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.formulaic_lgbm_strategy import FormulaicLgbmStrategy
from nautilus_lab.domain.marking import OpenLot, marked_equity
from nautilus_lab.domain.meta_label_strategy import MetaLabelStrategy
from nautilus_lab.domain.ml_obi_strategy import MlObiStrategy
from nautilus_lab.domain.position_plan import (
    Holding,
    holding_from_signed_qty,
    plan_for_signal,
)
from nautilus_lab.domain.ratchet_stop import RatchetState, initial_ratchet, step_ratchet
from nautilus_lab.domain.regime import RegimeParams, RobotName, require_backtest_support
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.volatility import VolModel
from nautilus_lab.domain.vpin import BarVpin, VpinModel
from nautilus_lab.domain.vpin_momentum import VpinMomentum
from nautilus_lab.infrastructure.lightgbm_classifier import (
    HeuristicDirectionClassifier,
    LightGBMDirectionClassifier,
    LightGBMSuccessClassifier,
    require_model_path,
)
from nautilus_lab.infrastructure.nautilus.bar_convert import to_domain_snapshot
from nautilus_lab.infrastructure.vol_forecast import build_vol_forecaster


class SingleLegRobot(Protocol):
    def on_bar(self, bar: OhlcvBar) -> Signal | None: ...


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
    risk_per_trade: Decimal = Decimal("0.005")
    stop_pct: Decimal = Decimal("0.01")
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


class SignalRobot(Strategy):  # type: ignore[misc]
    """Thin Nautilus adapter: domain signal -> risk -> sized order."""

    def __init__(
        self,
        config: SignalRobotConfig,
        *,
        taker_buy_base_volume_by_ns: Mapping[int, Decimal] | None = None,
    ) -> None:
        super().__init__(config)
        self._robot = _build_robot(config)
        self._limits = RiskLimits(
            risk_per_trade=config.risk_per_trade,
            stop_pct=config.stop_pct,
            max_daily_loss=config.max_daily_loss,
            max_drawdown=config.max_drawdown,
            max_open_positions=config.max_open_positions,
            kelly_fraction=config.kelly_fraction,
            max_var_99=config.max_var_99,
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
        self._previous_ts: datetime | None = None
        self._day_start_equity: Decimal | None = None
        self._peak_equity: Decimal | None = None
        self._peak_state: PeakState | None = None
        self._last_equity_ts: datetime | None = None
        self._day: date | None = None
        self._equity_curve: list[Decimal] = []
        self._turnover: Decimal = Decimal("0")
        self._returns: list[Decimal] = []
        self._previous_equity: Decimal | None = None
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
        self._last_vol_forecast = self._vol.update(domain_bar, self._previous_close)
        self._previous_close = domain_bar.close

        signal = self._robot.on_bar(domain_bar)
        self._last_mark = domain_bar.close
        if self._warming_up(int(bar.ts_event)):
            return
        self._track_equity(domain_bar.ts_utc)

        if self._apply_ratchet(domain_bar):
            return

        self._process_signal(signal, domain_bar.close)

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
        self._process_signal(signal, mid_price)

    def _place_protective_stop(self, entry_order: object) -> None:
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
            return
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            return
        entry_price = _as_decimal(getattr(entry_order, "avg_px", 0))
        quantity = getattr(entry_order, "filled_qty", None)
        if entry_price <= 0 or quantity is None or _as_decimal(quantity) <= 0:
            return
        is_long = getattr(entry_order, "side", None) == OrderSide.BUY
        trigger = entry_price - distance if is_long else entry_price + distance
        if trigger <= 0:
            self.log.warning(f"Protective stop skipped: trigger {trigger} is not a price")
            return
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

    def on_position_closed(self, event: object) -> None:
        """Book the trade for the Kelly stats, whoever closed it (signal, ratchet, stop)."""
        if getattr(event, "instrument_id", None) != self.config.instrument_id:
            return
        realized = getattr(event, "realized_pnl", None)
        if realized is not None:
            self._trade_stats.record(_as_decimal(realized))
        # Not the ratchet: on a reversal this event lands after the new entry armed it.
        self._cancel_protective_stop()

    def on_order_filled(self, event: object) -> None:
        client_order_id = getattr(event, "client_order_id", None)
        if self._stop_order_id is not None and client_order_id == self._stop_order_id:
            self._stop_order_id = None
            self.log.info("Protective stop filled; position closed at the stop")
            return
        if self._entry_order_id is None or client_order_id != self._entry_order_id:
            return
        order = self.cache.order(client_order_id)
        if order is None or not order.is_closed:
            return  # partial fill: wait for the rest, then protect the whole size
        self._entry_order_id = None
        self._place_protective_stop(order)

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

    def _process_signal(self, signal: Signal | None, current_price: Decimal) -> None:
        """Exit first (never gated by risk), then — only if allowed — enter.

        The risk layer guards new exposure. An opposite or FLAT signal closes what we
        hold even when every breaker is tripped; see `domain/position_plan.py` for why
        the old "gate first, return on refusal" order froze losing positions.
        """
        if signal is None:
            return
        plan = plan_for_signal(self._holding(), signal.side)
        if plan.is_noop:
            return

        # Gate the entry BEFORE the exit is submitted: the exit's own close order would
        # otherwise count as "an order already working" and block the entry it precedes.
        entry: tuple[Decimal, Decimal] | None = None
        if plan.wants_entry:
            entry = self._entry_allowed(current_price, reversing=plan.exit_position)

        if plan.exit_position:
            self._flatten()

        if entry is None:
            return
        qty, distance = entry
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.log.error("Instrument missing from cache; skip order")
            return
        desired_buy = signal.side is SignalSide.BUY
        order = self.order_factory.market(
            self.config.instrument_id,
            OrderSide.BUY if desired_buy else OrderSide.SELL,
            instrument.make_qty(qty),
        )
        self._pending_stop_distance = distance
        self._entry_order_id = order.client_order_id
        self.submit_order(order)
        self._turnover += current_price * qty
        self._arm_ratchet(current_price, SignalSide.BUY if desired_buy else SignalSide.SELL)

    def _entry_allowed(
        self, current_price: Decimal, *, reversing: bool
    ) -> tuple[Decimal, Decimal] | None:
        """(qty, stop distance) for a new entry, or None with the refusal recorded."""
        equity = self._equity()
        if equity is None:
            self.log.error("No account equity; skip entry (fail closed)")
            return None
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
            return None

        # An order that is accepted but not yet filled leaves the portfolio flat, so the
        # next signal would stack another entry on top of the pending one. On book-driven
        # robots that ran a 1x-capped size up to ~4x notional (ml_obi), because book
        # updates arrive far faster than the 50ms fill latency. One live entry at a time.
        if self._has_working_order():
            self._breaches.record("order already working")
            return None

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
            return None
        return qty, distance

    def on_stop(self) -> None:
        self._flatten()

    @property
    def equity_curve(self) -> tuple[Decimal, ...]:
        return tuple(self._equity_curve)

    @property
    def turnover(self) -> Decimal:
        return self._turnover

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
        self._ratchet, hit = step_ratchet(self._ratchet, bar, params)
        if not hit:
            return False
        self._flatten()
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
                return True
        inflight = self.cache.client_order_ids_inflight(instrument_id=instrument_id)
        return any(client_order_id != stop_id for client_order_id in inflight)

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
        classifier = _build_classifier(config.formulaic_model_path)
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
            ),
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
        classifier = _build_classifier(config.ml_obi_model_path)
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
        ),
        vpin=vpin,
        hawkes=hawkes,
    )


def _build_classifier(
    model_path: str | None,
) -> HeuristicDirectionClassifier | LightGBMDirectionClassifier:
    if model_path:
        return LightGBMDirectionClassifier(model_path=model_path)
    return HeuristicDirectionClassifier()


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
