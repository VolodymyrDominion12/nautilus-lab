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
from nautilus_lab.infrastructure.binance_klines import BinancePublicKlines
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type


def settings() -> Settings:
    return Settings()


def catalog(cfg: Settings, *, path: str | None = None) -> NautilusParquetCatalog:
    return NautilusParquetCatalog(Path(path or cfg.catalog_path))


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
) -> BacktestRequest:
    require_simulated_mode(cfg.trading_mode)
    bar_type = (
        "ETH/USDT.SIM-1-MINUTE-LAST-EXTERNAL"
        if source is BarOrigin.SYNTHETIC
        else nautilus_bar_type(cfg.instrument_id, cfg.bar_interval)
    )
    return BacktestRequest(
        mode=cfg.trading_mode,
        instrument_id=cfg.instrument_id,
        bar_count=bar_count,
        starting_equity=cfg.starting_equity,
        risk=cfg.risk_limits(),
        robot=robot or cfg.robot,
        fast_ema=cfg.fast_ema,
        slow_ema=cfg.slow_ema,
        regime=cfg.regime_params(),
        source=source,
        bar_type=bar_type,
        start=start,
        end=end,
    )


def ingest_request(
    cfg: Settings,
    *,
    start: datetime,
    end: datetime,
) -> IngestRequest:
    require_simulated_mode(cfg.trading_mode)
    return IngestRequest(
        mode=cfg.trading_mode,
        symbol=cfg.binance_symbol,
        interval=cfg.bar_interval,
        instrument_id=cfg.instrument_id,
        bar_type=nautilus_bar_type(cfg.instrument_id, cfg.bar_interval),
        start=start,
        end=end,
    )


def walk_forward_request(
    cfg: Settings,
    *,
    robot: RobotName | None = None,
    window: WalkForwardWindow | None = None,
    in_sample_fraction: Decimal | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> WalkForwardRequest:
    backtest = research_request(
        cfg,
        bar_count=0,
        robot=robot,
        source=BarOrigin.CATALOG,
        start=start,
        end=end,
    )
    return WalkForwardRequest(
        backtest=backtest,
        window=window,
        in_sample_fraction=in_sample_fraction or Decimal("0.7"),
    )
