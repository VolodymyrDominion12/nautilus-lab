from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Currency
from nautilus_trader.trading.strategy import Strategy

from nautilus_lab.application.risk import evaluate_entry, size_position
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.regime import RegimeParams, RobotName
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.signals import SignalSide


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
    quote_currency: str = "USDT"
    qty_step: Decimal = Decimal("0.001")


class SignalRobot(Strategy):  # type: ignore[misc]  # nautilus Strategy is untyped
    """Thin Nautilus adapter: domain signal -> risk -> sized order."""

    def __init__(self, config: SignalRobotConfig) -> None:
        super().__init__(config)
        self._robot = _build_robot(config)
        self._limits = RiskLimits(
            risk_per_trade=config.risk_per_trade,
            stop_pct=config.stop_pct,
            max_daily_loss=config.max_daily_loss,
            max_drawdown=config.max_drawdown,
            max_open_positions=config.max_open_positions,
        )
        self._previous_ts: datetime | None = None
        self._day_start_equity: Decimal | None = None
        self._peak_equity: Decimal | None = None
        self._day: date | None = None

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        domain_bar = _to_domain_bar(bar, str(self.config.instrument_id))
        validate_bar(domain_bar, previous_ts=self._previous_ts, now=domain_bar.ts_utc)
        self._previous_ts = domain_bar.ts_utc

        signal = self._robot.on_bar(domain_bar)
        if signal is None:
            return
        if signal.side is SignalSide.FLAT:
            self._flatten()
            return

        equity = self._equity()
        if equity is None:
            self.log.error("No account equity; skip order (fail closed)")
            return
        self._update_equity_path(domain_bar.ts_utc, equity)

        snapshot = AccountSnapshot(
            equity=equity,
            peak_equity=self._peak_equity or equity,
            day_start_equity=self._day_start_equity or equity,
            open_positions=0 if self._is_flat() else 1,
        )
        decision = evaluate_entry(snapshot, self._limits)
        if not decision.allowed:
            self.log.warning(f"Risk blocked entry: {decision.reason}")
            return

        desired_buy = signal.side is SignalSide.BUY
        if desired_buy and self.portfolio.is_net_long(self.config.instrument_id):
            return
        if not desired_buy and self.portfolio.is_net_short(self.config.instrument_id):
            return

        stop_distance = domain_bar.close * self._limits.stop_pct
        qty = size_position(
            equity=equity,
            price=domain_bar.close,
            stop_distance=stop_distance,
            risk_fraction=self._limits.risk_per_trade,
            qty_step=self.config.qty_step,
        )
        if qty <= 0:
            self.log.warning("Sized quantity is 0; skip order")
            return

        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.log.error("Instrument missing from cache; skip order")
            return

        if not self._is_flat():
            self.close_all_positions(self.config.instrument_id)

        side = OrderSide.BUY if desired_buy else OrderSide.SELL
        order = self.order_factory.market(
            self.config.instrument_id,
            side,
            instrument.make_qty(qty),
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        self.close_all_positions(self.config.instrument_id)

    def _flatten(self) -> None:
        if not self._is_flat():
            self.close_all_positions(self.config.instrument_id)

    def _is_flat(self) -> bool:
        return bool(self.portfolio.is_flat(self.config.instrument_id))

    def _equity(self) -> Decimal | None:
        quote = Currency.from_str(self.config.quote_currency)
        account = self.cache.account_for_venue(self.config.instrument_id.venue)
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


def _build_robot(config: SignalRobotConfig) -> EmaCrossover | RegimeRouter:
    robot = RobotName(config.robot)
    if robot is RobotName.EMA:
        return EmaCrossover(
            instrument_id=str(config.instrument_id),
            fast_period=config.fast_period,
            slow_period=config.slow_period,
        )
    return RegimeRouter(
        instrument_id=str(config.instrument_id),
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
    )


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
