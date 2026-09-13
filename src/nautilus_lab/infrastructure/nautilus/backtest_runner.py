from __future__ import annotations

from decimal import Decimal

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, LatencyModel, MakerTakerFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import TraderId, Venue
from nautilus_trader.model.objects import Money

from nautilus_lab.application.dtos import BacktestReport, BacktestRequest
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.infrastructure.nautilus.bar_convert import to_engine_bars
from nautilus_lab.infrastructure.nautilus.instrument import eth_usdt_sim
from nautilus_lab.infrastructure.nautilus.signal_strategy import SignalRobot, SignalRobotConfig


class NautilusResearchBacktest:
    """Low-level BacktestEngine with fees, latency, and slippage."""

    def run(self, request: BacktestRequest, bars: list[OhlcvBar]) -> BacktestReport:
        instrument = eth_usdt_sim()
        if request.instrument_id != str(instrument.id):
            raise ValueError(f"unsupported instrument_id: {request.instrument_id}")

        bar_type = BarType.from_str(request.bar_type)
        engine_bars = to_engine_bars(bars, bar_type=bar_type, instrument=instrument)

        usdt = instrument.quote_currency
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
            engine.add_instrument(instrument)
            engine.add_data(engine_bars)
            engine.add_strategy(
                SignalRobot(
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
                    ),
                ),
            )
            engine.run()
            fills = engine.trader.generate_order_fills_report()
            positions = engine.trader.generate_positions_report()
            account = engine.trader.generate_account_report(venue=Venue("SIM"))
            ending = _ending_balance(account)
            return BacktestReport(
                fills=len(fills),
                positions=len(positions),
                ending_balance=ending,
                notes=(
                    f"{request.robot.value} {request.source.value} backtest with fees, "
                    "50ms latency, 25% one-tick slippage"
                ),
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
