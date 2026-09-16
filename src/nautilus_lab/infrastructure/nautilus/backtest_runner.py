from __future__ import annotations

from decimal import Decimal, InvalidOperation

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, LatencyModel, MakerTakerFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Currency, Money

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.metrics import compute_metrics
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.infrastructure.nautilus.bar_convert import to_engine_bars
from nautilus_lab.infrastructure.nautilus.instrument import resolve_instrument
from nautilus_lab.infrastructure.nautilus.signal_strategy import SignalRobot, SignalRobotConfig
from nautilus_lab.infrastructure.nautilus.spread_strategy import SpreadRobot, SpreadRobotConfig
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type


class NautilusResearchBacktest:
    """Low-level BacktestEngine with fees, latency, and slippage."""

    def run(self, request: BacktestRequest, bars: list[OhlcvBar]) -> BacktestReport:
        if request.robot is RobotName.PAIRS:
            raise ValueError("pairs robot requires run_spread with two instruments")
        instrument = resolve_instrument(request.instrument_id, fees=request.fee_schedule)
        bar_type = BarType.from_str(request.bar_type)
        engine_bars = to_engine_bars(bars, bar_type=bar_type, instrument=instrument)
        strategy = SignalRobot(
            SignalRobotConfig(
                instrument_id=instrument.id,
                bar_type=bar_type,
                robot=request.robot.value,
                fast_period=request.fast_ema,
                slow_period=request.slow_ema,
                er_period=request.regime.er_period,
                trend_ema_period=request.regime.trend_ema_period,
                slope_lookback=request.regime.slope_lookback,
                enter_trend_er=request.regime.enter_trend_er,
                exit_trend_er=request.regime.exit_trend_er,
                donchian_period=request.regime.donchian_period,
                bb_period=request.regime.bb_period,
                bb_k=request.regime.bb_k,
                risk_per_trade=request.risk.risk_per_trade,
                stop_pct=request.risk.stop_pct,
                max_daily_loss=request.risk.max_daily_loss,
                max_drawdown=request.risk.max_drawdown,
                max_open_positions=request.risk.max_open_positions,
                kelly_fraction=request.risk.kelly_fraction,
                max_var_99=request.risk.max_var_99,
                use_bar_vpin=request.use_bar_vpin,
                vpin_bucket_volume=request.vpin_bucket_volume,
                vpin_toxic_threshold=request.vpin_toxic_threshold,
                vpin_momentum_ema_period=request.vpin_momentum_ema_period,
                vpin_momentum_atr_multiple=request.vpin_momentum_atr_multiple,
                formulaic_model_path=request.formulaic_model_path,
                formulaic_threshold=request.formulaic_threshold,
                meta_label_model_path=request.meta_label_model_path,
                meta_label_threshold=request.meta_label_threshold,
                use_vol_scaling=request.risk_overlay.use_vol_scaling,
                vol_scaling_target=request.risk_overlay.vol_scaling_target,
                use_fractional_kelly=request.risk_overlay.use_fractional_kelly,
                kelly_min_trades=request.risk_overlay.kelly_min_trades,
                use_cvar_breaker=request.risk_overlay.use_cvar_breaker,
                max_cvar_99=request.risk_overlay.max_cvar_99,
                use_ratchet=request.risk_overlay.use_ratchet,
                ratchet_arm_pct=request.risk_overlay.ratchet_arm_pct,
            ),
        )
        return self._execute(
            request=request,
            instruments=[instrument],
            data=engine_bars,
            strategy=strategy,
        )

    def run_spread(
        self,
        request: BacktestRequest,
        bars_by_instrument: dict[str, list[OhlcvBar]],
    ) -> BacktestReport:
        leg_a = request.pairs.leg_a
        leg_b = request.pairs.leg_b
        bars_a = bars_by_instrument.get(leg_a)
        bars_b = bars_by_instrument.get(leg_b)
        if bars_a is None or bars_b is None:
            raise ValueError(f"missing bars for pair {leg_a}/{leg_b}")
        instrument_a = resolve_instrument(leg_a, fees=request.fee_schedule)
        instrument_b = resolve_instrument(leg_b, fees=request.fee_schedule)
        interval = interval_from_bar_type(request.bar_type)
        bar_type_a = BarType.from_str(nautilus_bar_type(leg_a, interval))
        bar_type_b = BarType.from_str(nautilus_bar_type(leg_b, interval))
        data_a = to_engine_bars(bars_a, bar_type=bar_type_a, instrument=instrument_a)
        data_b = to_engine_bars(bars_b, bar_type=bar_type_b, instrument=instrument_b)
        strategy = SpreadRobot(
            SpreadRobotConfig(
                leg_a_id=instrument_a.id,
                leg_b_id=instrument_b.id,
                bar_type_a=bar_type_a,
                bar_type_b=bar_type_b,
                pairs=request.pairs,
                risk_per_trade=request.risk.risk_per_trade,
                stop_pct=request.risk.stop_pct,
                max_daily_loss=request.risk.max_daily_loss,
                max_drawdown=request.risk.max_drawdown,
                max_open_positions=request.risk.max_open_positions,
                kelly_fraction=request.risk.kelly_fraction,
                max_var_99=request.risk.max_var_99,
                use_vol_scaling=request.risk_overlay.use_vol_scaling,
                vol_scaling_target=request.risk_overlay.vol_scaling_target,
                use_fractional_kelly=request.risk_overlay.use_fractional_kelly,
                kelly_min_trades=request.risk_overlay.kelly_min_trades,
                use_cvar_breaker=request.risk_overlay.use_cvar_breaker,
                max_cvar_99=request.risk_overlay.max_cvar_99,
            ),
        )
        return self._execute(
            request=request,
            instruments=[instrument_a, instrument_b],
            data=[*data_a, *data_b],
            strategy=strategy,
        )

    def _execute(
        self,
        *,
        request: BacktestRequest,
        instruments: list[Instrument],
        data: list[Bar],
        strategy: SignalRobot | SpreadRobot,
    ) -> BacktestReport:
        usdt = Currency.from_str("USDT")
        engine = BacktestEngine(
            config=BacktestEngineConfig(
                trader_id=TraderId("BACKTESTER-001"),
                logging=LoggingConfig(log_level="ERROR"),
                risk_engine=RiskEngineConfig(bypass=False),
            ),
        )
        try:
            engine.add_venue(
                venue=Venue("SIM"),
                oms_type=OmsType.NETTING,
                account_type=AccountType.MARGIN,
                starting_balances=[Money(request.starting_equity, usdt)],
                base_currency=usdt,
                default_leverage=Decimal(1),
                fill_model=FillModel(
                    prob_fill_on_limit=1.0,
                    prob_slippage=0.25,
                    random_seed=request.seed,
                ),
                fee_model=MakerTakerFeeModel(),
                latency_model=LatencyModel(base_latency_nanos=50_000_000),
                bar_execution=True,
            )
            for instrument in instruments:
                engine.add_instrument(instrument)
            engine.add_data(data)
            engine.add_strategy(strategy)
            engine.run()
            fills_report = engine.trader.generate_order_fills_report()
            positions = engine.trader.generate_positions_report()
            account = engine.trader.generate_account_report(venue=Venue("SIM"))
            ending = _ending_balance(account)
            fees_paid = _fees_paid(fills_report)
            equity_curve = getattr(strategy, "equity_curve", ())
            turnover = getattr(strategy, "turnover", Decimal("0"))
            traded_notional = _traded_notional(fills_report)
            metrics = compute_metrics(
                starting_equity=request.starting_equity,
                equity_curve=equity_curve,
                fees_paid=fees_paid,
                turnover=turnover,
                traded_notional=traded_notional,
                ending_equity=ending,
            )
            saved_tearsheet: str | None = None
            if request.tearsheet_path:
                try:
                    from pathlib import Path

                    from nautilus_trader.analysis.tearsheet import (
                        PLOTLY_AVAILABLE,
                        create_tearsheet,
                    )

                    if PLOTLY_AVAILABLE:
                        Path(request.tearsheet_path).parent.mkdir(parents=True, exist_ok=True)
                        create_tearsheet(
                            engine,
                            output_path=request.tearsheet_path,
                            title=f"nautilus-lab {request.robot.value} Backtest Results",
                        )
                        saved_tearsheet = request.tearsheet_path
                    else:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Cannot generate tearsheet: plotly is missing."
                        )
                except Exception as exc:
                    import logging

                    logging.getLogger(__name__).warning("Failed to generate tearsheet: %s", exc)

            return BacktestReport(
                fills=len(fills_report),
                positions=len(positions),
                ending_balance=ending,
                notes=(
                    f"{request.robot.value} {request.source.value} backtest with fees "
                    f"(maker={request.fee_schedule.maker} taker={request.fee_schedule.taker}), "
                    "50ms latency, 25% one-tick slippage"
                ),
                metrics=metrics,
                tearsheet_path=saved_tearsheet,
            )
        finally:
            engine.dispose()


def _ending_balance(account_report: object) -> Decimal | None:
    import pandas as pd

    if not isinstance(account_report, pd.DataFrame) or account_report.empty:
        return None
    last = account_report.iloc[-1]
    for column in ("total", "balance", "free"):
        if column in account_report.columns:
            return Decimal(str(last[column]))
    return None


def _fees_paid(fills_report: object) -> Decimal:
    import pandas as pd

    if not isinstance(fills_report, pd.DataFrame) or fills_report.empty:
        return Decimal("0")
    for column in ("commissions", "commission", "fees"):
        if column not in fills_report.columns:
            continue
        total = Decimal("0")
        for value in fills_report[column]:
            text = str(value[0]) if isinstance(value, list) and value else str(value)
            amount = text.split()[0]
            total += Decimal(amount)
        return total
    return Decimal("0")


def _traded_notional(fills_report: object) -> Decimal:
    """Two-sided traded notional (entry AND exit fills) from the engine's fills report.

    This is the base for breakeven cost. The strategy's own `turnover` counter is
    NOT usable here: it accumulates entry notional only (signal_strategy.py adds it
    in the entry branch, and `_flatten()` closes positions without adding anything),
    so a breakeven computed from it would be roughly twice too optimistic.

    One row per filled order (`generate_order_fills_report`), so `avg_px * filled_qty`
    is the executed notional. Returns 0 when the report has no recognisable columns —
    breakeven then prints as undefined instead of inventing a number.
    """
    import pandas as pd

    if not isinstance(fills_report, pd.DataFrame) or fills_report.empty:
        return Decimal("0")
    price_column = next(
        (name for name in ("avg_px", "price", "last_px") if name in fills_report.columns),
        None,
    )
    quantity_column = next(
        (name for name in ("filled_qty", "quantity", "last_qty") if name in fills_report.columns),
        None,
    )
    if price_column is None or quantity_column is None:
        import logging

        logging.getLogger(__name__).warning(
            "Fills report has no usable price/quantity columns (%s); breakeven undefined.",
            ", ".join(str(name) for name in fills_report.columns),
        )
        return Decimal("0")
    total = Decimal("0")
    for price, quantity in zip(
        fills_report[price_column], fills_report[quantity_column], strict=True
    ):
        total += _to_decimal(price) * _to_decimal(quantity)
    return total


def _to_decimal(value: object) -> Decimal:
    """Nautilus reports mix Decimal, float and '0.5 USDT'-style strings."""
    text = str(value[0]) if isinstance(value, list) and value else str(value)
    token = text.split()[0] if text.split() else "0"
    try:
        return Decimal(token)
    except InvalidOperation:
        return Decimal("0")
