from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.dtos import BacktestRequest, IngestRequest, WalkForwardRequest
from nautilus_lab.application.ingest_historical_bars import IngestHistoricalBars
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.alerts import AlertNotifier, build_notifier
from nautilus_lab.infrastructure.binance_klines import BinancePublicKlines
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_to_instrument_id
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type


def settings() -> Settings:
    return Settings()


def catalog(cfg: Settings, *, path: str | None = None) -> NautilusParquetCatalog:
    return NautilusParquetCatalog(Path(path or cfg.catalog_path), fees=cfg.fee_schedule())


def notifier(cfg: Settings | None = None) -> AlertNotifier:
    resolved = cfg or settings()
    return build_notifier(
        telegram_token=resolved.telegram_bot_token,
        telegram_chat_id=resolved.telegram_chat_id,
        webhook_url=resolved.alert_webhook_url,
    )


def research_use_case(cfg: Settings | None = None) -> RunResearchBacktest:
    resolved = cfg or settings()
    return RunResearchBacktest(NautilusResearchBacktest(), ResearchBarFeed(catalog(resolved)))


def walk_forward_use_case(cfg: Settings | None = None) -> RunWalkForward:
    resolved = cfg or settings()
    return RunWalkForward(NautilusResearchBacktest(), ResearchBarFeed(catalog(resolved)))


def ingest_use_case(cfg: Settings | None = None) -> IngestHistoricalBars:
    resolved = cfg or settings()
    store = catalog(resolved)
    return IngestHistoricalBars(
        BinancePublicKlines(),
        store,
        catalog_path=str(store.path),
    )


def research_request(
    cfg: Settings,
    *,
    bar_count: int,
    robot: RobotName | None = None,
    source: BarOrigin = BarOrigin.CATALOG,
    start: datetime | None = None,
    end: datetime | None = None,
    stress_slice: str | None = None,
    tearsheet_path: str | None = None,
) -> BacktestRequest:
    require_simulated_mode(cfg.trading_mode)
    resolved_robot = robot or cfg.robot
    bar_type = (
        "ETH/USDT.SIM-1-MINUTE-LAST-EXTERNAL"
        if source is BarOrigin.SYNTHETIC
        else nautilus_bar_type(cfg.instrument_id, cfg.bar_interval)
    )
    pairs = cfg.pairs_params()
    instrument_ids: tuple[str, ...] = ()
    if resolved_robot is RobotName.PAIRS:
        instrument_ids = (pairs.leg_a, pairs.leg_b)
    return BacktestRequest(
        mode=cfg.trading_mode,
        instrument_id=cfg.instrument_id,
        bar_count=bar_count,
        starting_equity=cfg.starting_equity,
        risk=cfg.risk_limits(),
        risk_overlay=cfg.risk_overlay(),
        robot=resolved_robot,
        fast_ema=cfg.fast_ema,
        slow_ema=cfg.slow_ema,
        regime=cfg.regime_params(),
        pairs=pairs,
        source=source,
        bar_type=bar_type,
        bar_types=tuple(
            nautilus_bar_type(instrument_id, cfg.bar_interval) for instrument_id in instrument_ids
        ),
        instrument_ids=instrument_ids,
        start=start,
        end=end,
        fee_schedule=cfg.fee_schedule(),
        embargo_bars=cfg.embargo_bars,
        stress_slice=stress_slice,
        use_bar_vpin=cfg.use_bar_vpin,
        vpin_bucket_volume=cfg.vpin_bucket_volume,
        vpin_toxic_threshold=cfg.vpin_toxic_threshold,
        vpin_momentum_ema_period=cfg.vpin_momentum_ema_period,
        vpin_momentum_atr_multiple=cfg.vpin_momentum_atr_multiple,
        formulaic_model_path=cfg.formulaic_model_path,
        formulaic_threshold=cfg.formulaic_threshold,
        tearsheet_path=tearsheet_path,
    )


def ingest_request(
    cfg: Settings,
    *,
    start: datetime,
    end: datetime,
    symbol: str | None = None,
) -> IngestRequest:
    require_simulated_mode(cfg.trading_mode)
    resolved_symbol = symbol or cfg.binance_symbol
    instrument_id = binance_symbol_to_instrument_id(resolved_symbol)
    return IngestRequest(
        mode=cfg.trading_mode,
        symbol=resolved_symbol,
        interval=cfg.bar_interval,
        instrument_id=instrument_id,
        bar_type=nautilus_bar_type(instrument_id, cfg.bar_interval),
        start=start,
        end=end,
    )


def walk_forward_request(
    cfg: Settings,
    *,
    robot: RobotName | None = None,
    source: BarOrigin = BarOrigin.CATALOG,
    bar_count: int = 0,
    window: WalkForwardWindow | None = None,
    in_sample_fraction: Decimal | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    stress_slice: str | None = None,
    tearsheet_path: str | None = None,
    use_optuna: bool = False,
    optuna_trials: int = 20,
    folds: int = 1,
) -> WalkForwardRequest:
    backtest = research_request(
        cfg,
        bar_count=bar_count,
        robot=robot,
        source=source,
        start=start,
        end=end,
        stress_slice=stress_slice,
        tearsheet_path=tearsheet_path,
    )
    return WalkForwardRequest(
        backtest=backtest,
        window=window,
        in_sample_fraction=in_sample_fraction or Decimal("0.7"),
        embargo_bars=cfg.embargo_bars,
        use_optuna=use_optuna,
        optuna_trials=optuna_trials,
        tearsheet_path=tearsheet_path,
        folds=folds,
    )
