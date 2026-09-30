from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.strategy import Strategy

from nautilus_lab.application.risk import (
    TradeStats,
    evaluate_entry,
    resolve_risk_fraction,
    size_spread,
    stop_distance,
)
from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.decision_trace import Outcome, TraceStep, is_warmup
from nautilus_lab.domain.drawdown_cooldown import PeakState, advance, on_refusal
from nautilus_lab.domain.marking import OpenLot, marked_equity
from nautilus_lab.domain.pairs.pairs_trading import PairsTrading
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.ports import DecisionLogPort
from nautilus_lab.domain.position_plan import (
    Holding,
    holding_from_signed_qty,
    plan_for_signal,
)
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.infrastructure.nautilus.two_leg_decisions import (
    TwoLegDecisionLog,
    account_marks,
    leg_step,
    plan_step,
    refusal_step,
)


class SpreadRobotConfig(StrategyConfig, frozen=True):
    leg_a_id: InstrumentId
    leg_b_id: InstrumentId
    bar_type_a: BarType
    bar_type_b: BarType
    pairs: PairsParams
    risk_per_trade: Decimal = Decimal("0.005")
    stop_pct: Decimal = Decimal("0.01")
    max_daily_loss: Decimal = Decimal("0.02")
    max_drawdown: Decimal = Decimal("0.06")
    max_open_positions: int = 2
    kelly_fraction: Decimal = Decimal("0.25")
    max_var_99: Decimal = Decimal("0.05")
    quote_currency: str = "USDT"
    qty_step_a: Decimal = Decimal("0.001")
    qty_step_b: Decimal = Decimal("0.00001")
    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")
    trade_start_ns: int | None = None
    drawdown_cooldown_days: int = 0


class SpreadRobot(Strategy):  # type: ignore[misc]
    """Thin adapter: spread signal -> risk -> dual-leg market orders."""

    def __init__(
        self,
        config: SpreadRobotConfig,
        *,
        decision_log: DecisionLogPort | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(config)
        self._decisions = TwoLegDecisionLog(
            decision_log=decision_log,
            session_id=session_id,
            robot="pairs",
            instrument_id=str(config.leg_a_id),
            params=config.dict(),
        )
        self._robot = PairsTrading(
            leg_a=str(config.leg_a_id),
            leg_b=str(config.leg_b_id),
            params=config.pairs,
        )
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
        )
        self._last_a: OhlcvBar | None = None
        self._last_b: OhlcvBar | None = None
        self._prev_ts_a: datetime | None = None
        self._prev_ts_b: datetime | None = None
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
        self._entry_equity: Decimal | None = None
        self._exposure_bars: int = 0
        self._trade_stats = TradeStats()
        self._atr_a = AverageTrueRange(14)
        self._atr_b = AverageTrueRange(14)

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type_a)
        self.subscribe_bars(self.config.bar_type_b)

    def on_bar(self, bar: Bar) -> None:
        domain = _to_domain_bar(bar)
        if domain.instrument_id == str(self.config.leg_a_id):
            validate_bar(domain, previous_ts=self._prev_ts_a, now=domain.ts_utc)
            self._prev_ts_a = domain.ts_utc
            self._last_a = domain
            self._atr_a.update(domain)
        elif domain.instrument_id == str(self.config.leg_b_id):
            validate_bar(domain, previous_ts=self._prev_ts_b, now=domain.ts_utc)
            self._prev_ts_b = domain.ts_utc
            self._last_b = domain
            self._atr_b.update(domain)
        else:
            return
        if self._last_a is None or self._last_b is None:
            return
        if self._last_a.ts_utc != self._last_b.ts_utc:
            return

        signal = self._robot.on_bars(self._last_a, self._last_b)
        steps = list(self._robot.last_trace)
        start = self.config.trade_start_ns
        if start is not None and int(bar.ts_event) < start:
            # Warm-up bar: the spread model learns, nothing is traded.
            self._decide(Outcome.WARMUP, steps, signal=None)
            return
        equity = self._equity()
        if equity is not None:
            self._update_equity_path(self._last_a.ts_utc, equity)
            self._equity_curve.append(equity)
            if self._previous_equity is not None and self._previous_equity > 0:
                self._returns.append((equity - self._previous_equity) / self._previous_equity)
            self._previous_equity = equity
            if self._open_legs() > 0:
                self._exposure_bars += 1

        if signal is None:
            self._decide(Outcome.WARMUP if is_warmup(tuple(steps)) else Outcome.NO_SIGNAL, steps)
            return
        side_a = signal.leg_a.side.value
        # Leg A's direction is the spread's direction; leg B always takes the other side.
        # Exit is decided before — and independently of — the risk gate: a refused
        # entry must not keep the opposite spread open (see domain/position_plan.py).
        held = self._holding_a()
        plan = plan_for_signal(held, signal.leg_a.side)
        steps.append(plan_step(held, plan.exit_position, plan.wants_entry))
        if plan.is_noop:
            self._decide(Outcome.HOLD_NOOP, steps, signal=side_a, reason=signal.reason)
            return
        refusal = (
            self._entry_refusal(equity, reversing=plan.exit_position) if plan.wants_entry else None
        )
        if plan.exit_position:
            steps.extend(self._exit_steps())
            self._flatten_both(equity)
            if not plan.wants_entry:
                self._decide(Outcome.EXIT, steps, signal=side_a, reason=signal.reason)
                return
        if refusal is not None or equity is None:
            gate, label = refusal_step(*(refusal or ("equity", "no account equity", None, None)))
            steps.append(gate)
            self._decide(
                Outcome.ENTRY_BLOCKED_RISK,
                steps,
                signal=side_a,
                reason=signal.reason,
                blocked_by=label,
            )
            return

        risk_fraction = resolve_risk_fraction(
            self._limits,
            self._overlay,
            stats=self._trade_stats,
        )
        qty_a, qty_b = size_spread(
            equity=equity,
            price_a=self._last_a.close,
            price_b=self._last_b.close,
            stop_distance_a=stop_distance(self._last_a.close, self._limits, atr=self._atr_a.value),
            risk_fraction=risk_fraction,
            hedge_ratio=signal.leg_b.qty_weight,
            qty_step_a=self.config.qty_step_a,
            qty_step_b=self.config.qty_step_b,
        )
        if qty_a <= 0 or qty_b <= 0:
            # An unhedged half of a spread is a directional bet, not the robot.
            gate, label = refusal_step("sizing", "a leg sized to 0", None, None)
            steps.append(gate)
            self._decide(
                Outcome.ENTRY_SKIPPED_SIZE,
                steps,
                signal=side_a,
                reason=signal.reason,
                blocked_by=label,
            )
            return
        self._submit_leg(self.config.leg_a_id, signal.leg_a.side, self._last_a.close, qty_a)
        self._submit_leg(self.config.leg_b_id, signal.leg_b.side, self._last_b.close, qty_b)
        self._entry_equity = equity
        steps.append(
            leg_step(
                "entry",
                leg="A",
                side="LONG" if signal.leg_a.side is SignalSide.BUY else "SHORT",
                qty=qty_a,
                price=self._last_a.close,
            )
        )
        steps.append(
            leg_step(
                "entry",
                leg="B",
                side="LONG" if signal.leg_b.side is SignalSide.BUY else "SHORT",
                qty=qty_b,
                price=self._last_b.close,
            )
        )
        self._decide(
            Outcome.REVERSE if plan.exit_position else Outcome.ENTRY_OPENED,
            steps,
            signal=side_a,
            reason=signal.reason,
        )

    def _decide(
        self,
        outcome: Outcome,
        steps: list[TraceStep],
        *,
        signal: str | None = None,
        reason: str | None = None,
        blocked_by: str | None = None,
    ) -> None:
        """Write this bar's decision record (no-op when the run has no decision log)."""
        if not self._decisions.enabled or self._last_a is None:
            return
        bar_a = self._last_a
        self._decisions.write(
            ts=bar_a.ts_utc,
            close=bar_a.close,
            outcome=outcome,
            steps=steps,
            account=account_marks(
                holding=self._holding_a(),
                equity=self._equity(),
                day_start=self._day_start_equity,
                peak=self._peak_equity,
                legs_open=self._open_legs(),
            ),
            signal=signal,
            signal_reason=reason,
            blocked_by=blocked_by,
            bar={
                "o": bar_a.open,
                "h": bar_a.high,
                "l": bar_a.low,
                "c": bar_a.close,
                "v": bar_a.volume,
            },
        )

    def _exit_steps(self) -> list[TraceStep]:
        marks = {
            str(self.config.leg_a_id): ("A", self._last_a),
            str(self.config.leg_b_id): ("B", self._last_b),
        }
        out: list[TraceStep] = []
        for lot in self._open_lots():
            leg, last = marks.get(lot.instrument_id, ("?", None))
            out.append(
                leg_step(
                    "exit",
                    leg=leg,
                    side="LONG" if lot.signed_qty > 0 else "SHORT",
                    qty=abs(lot.signed_qty),
                    price=last.close if last is not None else lot.avg_price,
                )
            )
        return out

    def on_stop(self) -> None:
        self._flatten_both(self._equity())

    def _entry_refusal(
        self, equity: Decimal | None, *, reversing: bool
    ) -> tuple[str, str, Decimal | None, Decimal | None] | None:
        """None when the entry may go ahead, else (code, reason, value, limit)."""
        if equity is None:
            self.log.error("No account equity; skip spread order")
            return ("equity", "no account equity", None, None)
        snapshot = AccountSnapshot(
            equity=equity,
            peak_equity=self._peak_equity or equity,
            day_start_equity=self._day_start_equity or equity,
            open_positions=0 if reversing else self._open_legs(),
            recent_returns=tuple(self._returns[-30:]),
        )
        decision = evaluate_entry(snapshot, self._limits, self._overlay)
        if not decision.allowed:
            self._note_refusal(decision.reason)
            self.log.warning(f"Risk blocked spread entry: {decision.reason}")
            return (decision.code or "unknown", decision.reason, decision.value, decision.limit)
        return None

    def _holding_a(self) -> Holding:
        signed = sum(
            (
                lot.signed_qty
                for lot in self._open_lots()
                if lot.instrument_id == str(self.config.leg_a_id)
            ),
            Decimal("0"),
        )
        return holding_from_signed_qty(signed)

    def _open_lots(self) -> list[OpenLot]:
        return [
            OpenLot(
                instrument_id=str(leg),
                signed_qty=_as_decimal(position.signed_qty),
                avg_price=_as_decimal(position.avg_px_open),
            )
            for leg in (self.config.leg_a_id, self.config.leg_b_id)
            for position in self.cache.positions_open(instrument_id=leg)
        ]

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

    def _submit_leg(
        self,
        instrument_id: InstrumentId,
        side: SignalSide,
        price: Decimal,
        qty: Decimal,
    ) -> None:
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return
        order_side = OrderSide.BUY if side is SignalSide.BUY else OrderSide.SELL
        order = self.order_factory.market(instrument_id, order_side, instrument.make_qty(qty))
        self.submit_order(order)
        self._turnover += price * qty

    def _flatten_both(self, equity: Decimal | None) -> None:
        if equity is not None and self._entry_equity is not None and self._open_legs() > 0:
            self._trade_stats.record(equity - self._entry_equity)
            self._entry_equity = None
        self.close_all_positions(self.config.leg_a_id)
        self.close_all_positions(self.config.leg_b_id)

    def _open_legs(self) -> int:
        count = 0
        if not self.portfolio.is_flat(self.config.leg_a_id):
            count += 1
        if not self.portfolio.is_flat(self.config.leg_b_id):
            count += 1
        return count

    def _equity(self) -> Decimal | None:
        quote = Currency.from_str(self.config.quote_currency)
        account = self.cache.account_for_venue(self.config.leg_a_id.venue)
        if account is None:
            return None
        total = account.balance_total(quote)
        if total is None:
            return None
        # Balance moves on realized PnL only (MARGIN account); both open legs are marked
        # at their last close so the curve and the breakers see open losses.
        marks: dict[str, Decimal] = {}
        if self._last_a is not None:
            marks[str(self.config.leg_a_id)] = self._last_a.close
        if self._last_b is not None:
            marks[str(self.config.leg_b_id)] = self._last_b.close
        return marked_equity(_as_decimal(total), self._open_lots(), marks)

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


def _to_domain_bar(bar: Bar) -> OhlcvBar:
    ts = datetime.fromtimestamp(bar.ts_event / 1_000_000_000, tz=UTC)
    instrument_id = str(bar.bar_type.instrument_id)
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
