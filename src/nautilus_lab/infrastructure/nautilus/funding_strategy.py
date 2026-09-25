from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType, FundingRateUpdate
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.strategy import Strategy

from nautilus_lab.application.risk import (
    TradeStats,
    evaluate_entry,
    resolve_risk_fraction,
    size_position,
    stop_distance,
)
from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.drawdown_cooldown import PeakState, advance, on_refusal
from nautilus_lab.domain.funding import FundingCashAndCarry, FundingParams, FundingSnapshot
from nautilus_lab.domain.marking import OpenLot, marked_equity
from nautilus_lab.domain.position_plan import (
    Holding,
    holding_from_signed_qty,
    plan_for_signal,
)
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.signals import SignalSide


class FundingRobotConfig(StrategyConfig, frozen=True):
    leg_spot_id: InstrumentId
    leg_perp_id: InstrumentId
    bar_type_spot: BarType
    bar_type_perp: BarType
    params: FundingParams
    risk_per_trade: Decimal = Decimal("0.005")
    stop_pct: Decimal = Decimal("0.01")
    max_daily_loss: Decimal = Decimal("0.02")
    max_drawdown: Decimal = Decimal("0.06")
    max_open_positions: int = 2
    kelly_fraction: Decimal = Decimal("0.25")
    max_var_99: Decimal = Decimal("0.05")
    quote_currency: str = "USDT"
    qty_step_spot: Decimal = Decimal("0.001")
    qty_step_perp: Decimal = Decimal("0.001")
    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")
    trade_start_ns: int | None = None
    drawdown_cooldown_days: int = 0


class FundingRobot(Strategy):  # type: ignore[misc]
    """Delta-neutral cash-and-carry adapter: spot long + perp short on funding rate."""

    def __init__(self, config: FundingRobotConfig) -> None:
        super().__init__(config)
        self._robot = FundingCashAndCarry(
            spot_id=str(config.leg_spot_id),
            perp_id=str(config.leg_perp_id),
            params=config.params,
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
        self._last_spot: OhlcvBar | None = None
        self._last_perp: OhlcvBar | None = None
        self._prev_ts_spot: datetime | None = None
        self._prev_ts_perp: datetime | None = None
        self._day_start_equity: Decimal | None = None
        self._peak_equity: Decimal | None = None
        self._peak_state: PeakState | None = None
        self._last_equity_ts: datetime | None = None
        self._day: date | None = None
        self._equity_curve: list[Decimal] = []
        self._turnover: Decimal = Decimal("0")
        self._returns: list[Decimal] = []
        self._previous_equity: Decimal | None = None
        self._entry_equity: Decimal | None = None
        self._trade_stats = TradeStats()
        self._atr_spot = AverageTrueRange(14)
        self._atr_perp = AverageTrueRange(14)
        self._accumulated_funding: Decimal = Decimal("0")
        self._funding_settlements_count: int = 0
        self._refusal_reasons: dict[str, int] = {}

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type_spot)
        self.subscribe_bars(self.config.bar_type_perp)
        self.subscribe_funding_rates(self.config.leg_perp_id)

    def on_bar(self, bar: Bar) -> None:
        domain = _to_domain_bar(bar)
        if domain.instrument_id == str(self.config.leg_spot_id):
            validate_bar(domain, previous_ts=self._prev_ts_spot, now=domain.ts_utc)
            self._prev_ts_spot = domain.ts_utc
            self._last_spot = domain
            self._atr_spot.update(domain)
        elif domain.instrument_id == str(self.config.leg_perp_id):
            validate_bar(domain, previous_ts=self._prev_ts_perp, now=domain.ts_utc)
            self._prev_ts_perp = domain.ts_utc
            self._last_perp = domain
            self._atr_perp.update(domain)
        else:
            return
        if self._last_spot is None or self._last_perp is None:
            return
        if self._last_spot.ts_utc != self._last_perp.ts_utc:
            return

        start = self.config.trade_start_ns
        if start is not None and int(bar.ts_event) < start:
            return  # warm-up bar

        equity = self._equity()
        if equity is not None:
            self._update_equity_path(self._last_spot.ts_utc, equity)
            self._equity_curve.append(equity)
            if self._previous_equity is not None and self._previous_equity > 0:
                self._returns.append((equity - self._previous_equity) / self._previous_equity)
            self._previous_equity = equity

    def on_funding_rate(self, funding_rate: FundingRateUpdate) -> None:
        rate = _as_decimal(funding_rate.rate)
        # 1. Accrue funding payment on short perpetual position:
        # Short position cash flow: -signed_qty * mark_price * rate (positive when short and rate > 0).
        open_lots = self._open_lots()
        perp_lots = [lot for lot in open_lots if lot.instrument_id == str(self.config.leg_perp_id)]
        signed_perp_qty = sum((lot.signed_qty for lot in perp_lots), Decimal("0"))

        mark_price = self._last_perp.close if self._last_perp is not None else Decimal("0")
        if signed_perp_qty != 0 and mark_price > 0:
            payment = -signed_perp_qty * mark_price * rate
            self._accumulated_funding += payment
            self._funding_settlements_count += 1
            self.log.info(
                f"Funding payment: rate={rate} qty={signed_perp_qty} mark={mark_price} -> delta={payment:+f} USDT"
            )

        # 2. Form snapshot for strategy signal evaluation
        ts = datetime.fromtimestamp(funding_rate.ts_event / 1_000_000_000, tz=UTC)
        index_price = self._last_spot.close if self._last_spot is not None else None
        snapshot = FundingSnapshot(
            instrument=str(self.config.leg_perp_id),
            funding_rate=rate,
            mark_price=mark_price,
            index_price=index_price,
            ts_utc=ts,
        )

        signal = self._robot.on_funding(snapshot)
        if signal is None:
            return

        equity = self._equity()
        plan = plan_for_signal(self._holding_spot(), signal.leg_a.side)
        if plan.is_noop:
            return
        entry_allowed = plan.wants_entry and self._entry_allowed(
            equity, reversing=plan.exit_position
        )
        if plan.exit_position:
            self._flatten_both(equity)
        if not entry_allowed or equity is None:
            return

        risk_fraction = resolve_risk_fraction(
            self._limits,
            self._overlay,
            stats=self._trade_stats,
        )
        assert self._last_spot is not None
        assert self._last_perp is not None
        self._submit_leg(
            self.config.leg_spot_id,
            signal.leg_a.side,
            self._last_spot.close,
            self.config.qty_step_spot,
            equity,
            risk_fraction,
            self._atr_spot.value,
        )
        self._submit_leg(
            self.config.leg_perp_id,
            signal.leg_b.side,
            self._last_perp.close,
            self.config.qty_step_perp,
            equity,
            risk_fraction * signal.leg_b.qty_weight,
            self._atr_perp.value,
        )
        self._entry_equity = equity

    def on_stop(self) -> None:
        self._flatten_both(self._equity())

    @property
    def accumulated_funding(self) -> Decimal:
        return self._accumulated_funding

    @property
    def funding_settlements_count(self) -> int:
        return self._funding_settlements_count

    @property
    def equity_curve(self) -> tuple[Decimal, ...]:
        return tuple(self._equity_curve)

    @property
    def turnover(self) -> Decimal:
        return self._turnover

    @property
    def risk_breaches(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._refusal_reasons.items()))

    def _entry_allowed(self, equity: Decimal | None, *, reversing: bool) -> bool:
        if equity is None:
            self.log.error("No account equity; skip funding spread entry")
            return False
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
            self.log.warning(f"Risk blocked funding entry: {decision.reason}")
            return False
        return True

    def _holding_spot(self) -> Holding:
        signed = sum(
            (
                lot.signed_qty
                for lot in self._open_lots()
                if lot.instrument_id == str(self.config.leg_spot_id)
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
            for leg in (self.config.leg_spot_id, self.config.leg_perp_id)
            for position in self.cache.positions_open(instrument_id=leg)
        ]

    def _submit_leg(
        self,
        instrument_id: InstrumentId,
        side: SignalSide,
        price: Decimal,
        qty_step: Decimal,
        equity: Decimal,
        risk_fraction: Decimal,
        atr: Decimal | None,
    ) -> None:
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            return
        distance = stop_distance(price, self._limits, atr=atr)
        qty = size_position(
            equity=equity,
            price=price,
            stop_distance=distance,
            risk_fraction=risk_fraction,
            qty_step=qty_step,
        )
        if qty <= 0:
            return
        order_side = OrderSide.BUY if side is SignalSide.BUY else OrderSide.SELL
        order = self.order_factory.market(instrument_id, order_side, instrument.make_qty(qty))
        self.submit_order(order)
        self._turnover += price * qty

    def _flatten_both(self, equity: Decimal | None) -> None:
        if equity is not None and self._entry_equity is not None and self._open_legs() > 0:
            self._trade_stats.record(equity - self._entry_equity)
            self._entry_equity = None
        self.close_all_positions(self.config.leg_spot_id)
        self.close_all_positions(self.config.leg_perp_id)

    def _open_legs(self) -> int:
        count = 0
        if not self.portfolio.is_flat(self.config.leg_spot_id):
            count += 1
        if not self.portfolio.is_flat(self.config.leg_perp_id):
            count += 1
        return count

    def _equity(self) -> Decimal | None:
        quote = Currency.from_str(self.config.quote_currency)
        account = self.cache.account_for_venue(self.config.leg_spot_id.venue)
        if account is None:
            return None
        total = account.balance_total(quote)
        if total is None:
            return None
        marks: dict[str, Decimal] = {}
        if self._last_spot is not None:
            marks[str(self.config.leg_spot_id)] = self._last_spot.close
        if self._last_perp is not None:
            marks[str(self.config.leg_perp_id)] = self._last_perp.close
        base_eq = marked_equity(_as_decimal(total), self._open_lots(), marks)
        return base_eq + self._accumulated_funding

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
        self._refusal_reasons[reason] = self._refusal_reasons.get(reason, 0) + 1
        if self._peak_state is not None and self._last_equity_ts is not None:
            self._peak_state = on_refusal(self._peak_state, reason=reason, now=self._last_equity_ts)


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
