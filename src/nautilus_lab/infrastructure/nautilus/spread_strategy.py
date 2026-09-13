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
    effective_risk_fraction,
    evaluate_entry,
    size_position,
    stop_distance,
)
from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.pairs.pairs_trading import PairsTrading
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.signals import SignalSide


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
    quote_currency: str = "USDT"
    qty_step_a: Decimal = Decimal("0.001")
    qty_step_b: Decimal = Decimal("0.00001")


class SpreadRobot(Strategy):  # type: ignore[misc]
    """Thin adapter: spread signal -> risk -> dual-leg market orders."""

    def __init__(self, config: SpreadRobotConfig) -> None:
        super().__init__(config)
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
        )
        self._last_a: OhlcvBar | None = None
        self._last_b: OhlcvBar | None = None
        self._prev_ts_a: datetime | None = None
        self._prev_ts_b: datetime | None = None
        self._day_start_equity: Decimal | None = None
        self._peak_equity: Decimal | None = None
        self._day: date | None = None
        self._equity_curve: list[Decimal] = []
        self._turnover: Decimal = Decimal("0")
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
        equity = self._equity()
        if equity is not None:
            self._update_equity_path(self._last_a.ts_utc, equity)
            self._equity_curve.append(equity)

        if signal is None:
            return
        if signal.leg_a.side is SignalSide.FLAT:
            self._flatten_both()
            return

        if equity is None:
            self.log.error("No account equity; skip spread order")
            return
        snapshot = AccountSnapshot(
            equity=equity,
            peak_equity=self._peak_equity or equity,
            day_start_equity=self._day_start_equity or equity,
            open_positions=self._open_legs(),
        )
        decision = evaluate_entry(snapshot, self._limits)
        if not decision.allowed:
            self.log.warning(f"Risk blocked spread entry: {decision.reason}")
            return

        risk_fraction = effective_risk_fraction(self._limits)
        self._flatten_both()
        self._submit_leg(
            self.config.leg_a_id,
            signal.leg_a.side,
            self._last_a.close,
            self.config.qty_step_a,
            equity,
            risk_fraction,
            self._atr_a.value,
        )
        self._submit_leg(
            self.config.leg_b_id,
            signal.leg_b.side,
            self._last_b.close,
            self.config.qty_step_b,
            equity,
            risk_fraction * signal.leg_b.qty_weight,
            self._atr_b.value,
        )

    def on_stop(self) -> None:
        self._flatten_both()

    @property
    def equity_curve(self) -> tuple[Decimal, ...]:
        return tuple(self._equity_curve)

    @property
    def turnover(self) -> Decimal:
        return self._turnover

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

    def _flatten_both(self) -> None:
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
        return _as_decimal(total)

    def _update_equity_path(self, ts_utc: datetime, equity: Decimal) -> None:
        day = ts_utc.date()
        if self._day != day:
            self._day = day
            self._day_start_equity = equity
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity


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
