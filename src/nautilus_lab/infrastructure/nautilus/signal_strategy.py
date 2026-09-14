from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol

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
    size_position,
    stop_distance,
)
from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.ema_crossover import EmaCrossover
from nautilus_lab.domain.formulaic_lgbm_strategy import FormulaicLgbmStrategy
from nautilus_lab.domain.regime import RegimeParams, RobotName, require_backtest_support
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.risk import AccountSnapshot, RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.volatility import HarRealizedVolatility
from nautilus_lab.domain.vpin import BarVpin
from nautilus_lab.domain.vpin_momentum import VpinMomentum
from nautilus_lab.infrastructure.lightgbm_classifier import (
    HeuristicDirectionClassifier,
    LightGBMDirectionClassifier,
)


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
    vpin_bucket_volume: Decimal = Decimal("1000")
    vpin_toxic_threshold: Decimal = Decimal("0.7")
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
    formulaic_model_path: str | None = None
    formulaic_threshold: Decimal = Decimal("0.55")
    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")


class SignalRobot(Strategy):  # type: ignore[misc]
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
        self._previous_ts: datetime | None = None
        self._day_start_equity: Decimal | None = None
        self._peak_equity: Decimal | None = None
        self._day: date | None = None
        self._equity_curve: list[Decimal] = []
        self._turnover: Decimal = Decimal("0")
        self._returns: list[Decimal] = []
        self._previous_equity: Decimal | None = None
        self._entry_equity: Decimal | None = None
        self._trade_stats = TradeStats()
        self._atr = AverageTrueRange(14)
        self._har = HarRealizedVolatility()
        self._previous_close: Decimal | None = None

    def on_start(self) -> None:
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        domain_bar = _to_domain_bar(bar, str(self.config.instrument_id))
        validate_bar(domain_bar, previous_ts=self._previous_ts, now=domain_bar.ts_utc)
        self._previous_ts = domain_bar.ts_utc
        self._atr.update(domain_bar)
        vol_forecast = self._har.update(domain_bar, self._previous_close)
        self._previous_close = domain_bar.close

        signal = self._robot.on_bar(domain_bar)
        equity = self._equity()
        if equity is not None:
            self._update_equity_path(domain_bar.ts_utc, equity)
            self._equity_curve.append(equity)
            if self._previous_equity is not None and self._previous_equity > 0:
                self._returns.append((equity - self._previous_equity) / self._previous_equity)
            self._previous_equity = equity

        if signal is None:
            return
        if signal.side is SignalSide.FLAT:
            self._flatten(equity)
            return

        if equity is None:
            self.log.error("No account equity; skip order (fail closed)")
            return

        snapshot = AccountSnapshot(
            equity=equity,
            peak_equity=self._peak_equity or equity,
            day_start_equity=self._day_start_equity or equity,
            open_positions=0 if self._is_flat() else 1,
            recent_returns=tuple(self._returns[-30:]),
        )
        decision = evaluate_entry(snapshot, self._limits, self._overlay)
        if not decision.allowed:
            self.log.warning(f"Risk blocked entry: {decision.reason}")
            return

        desired_buy = signal.side is SignalSide.BUY
        if desired_buy and self.portfolio.is_net_long(self.config.instrument_id):
            return
        if not desired_buy and self.portfolio.is_net_short(self.config.instrument_id):
            return

        distance = stop_distance(domain_bar.close, self._limits, atr=self._atr.value)
        risk_fraction = resolve_risk_fraction(
            self._limits,
            self._overlay,
            stats=self._trade_stats,
            forecast_vol=vol_forecast,
        )
        qty = size_position(
            equity=equity,
            price=domain_bar.close,
            stop_distance=distance,
            risk_fraction=risk_fraction,
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
            self._flatten(equity)

        side = OrderSide.BUY if desired_buy else OrderSide.SELL
        order = self.order_factory.market(
            self.config.instrument_id,
            side,
            instrument.make_qty(qty),
        )
        self.submit_order(order)
        self._turnover += domain_bar.close * qty
        self._entry_equity = equity

    def on_stop(self) -> None:
        self._flatten(self._equity())

    @property
    def equity_curve(self) -> tuple[Decimal, ...]:
        return tuple(self._equity_curve)

    @property
    def turnover(self) -> Decimal:
        return self._turnover

    def _flatten(self, equity: Decimal | None) -> None:
        if not self._is_flat():
            if equity is not None and self._entry_equity is not None:
                self._trade_stats.record(equity - self._entry_equity)
                self._entry_equity = None
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
        return VpinMomentum(
            instrument_id=instrument_id,
            bucket_volume=config.vpin_bucket_volume,
            toxic_threshold=config.vpin_toxic_threshold,
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
    vpin = None
    if config.use_bar_vpin:
        vpin = BarVpin(
            bucket_volume=config.vpin_bucket_volume,
            toxic_threshold=config.vpin_toxic_threshold,
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
