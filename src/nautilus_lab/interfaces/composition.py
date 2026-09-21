from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.dtos import (
    BacktestRequest,
    FundingIngestRequest,
    IngestAggTradesRequest,
    IngestRequest,
    OverfitAuditRequest,
    WalkForwardRequest,
)
from nautilus_lab.application.ingest_agg_trades import IngestAggTrades
from nautilus_lab.application.ingest_funding_history import IngestFundingHistory
from nautilus_lab.application.ingest_historical_bars import IngestHistoricalBars
from nautilus_lab.application.ingest_orderbook import IngestOrderBook
from nautilus_lab.application.propose_alphas import AlphaProposalRequest, resolve_prompt_path
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_overfitting_audit import RunOverfitAudit
from nautilus_lab.application.run_research_backtest import RunResearchBacktest
from nautilus_lab.application.run_walk_forward import RunWalkForward
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.ports import ChatCompleter
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.ticks import AggTrade
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.agg_trades_catalog import ParquetAggTradesCatalog
from nautilus_lab.infrastructure.alerts import AlertNotifier, build_notifier
from nautilus_lab.infrastructure.binance_agg_trades import BinancePublicAggTrades
from nautilus_lab.infrastructure.binance_funding import BinancePublicFunding
from nautilus_lab.infrastructure.binance_klines import BinancePublicKlines
from nautilus_lab.infrastructure.funding_catalog import ParquetFundingCatalog
from nautilus_lab.infrastructure.http_resilience import ResilientJsonClient
from nautilus_lab.infrastructure.llm_client import OpenAICompatibleChatClient
from nautilus_lab.infrastructure.nautilus.backtest_runner import NautilusResearchBacktest
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.instrument import (
    binance_symbol_for_instrument,
    binance_symbol_to_instrument_id,
)
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.orderbook_catalog import ParquetOrderBookCatalog
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.infrastructure.taker_flow_catalog import ParquetTakerFlowCatalog
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type


def settings() -> Settings:
    return Settings()


def catalog(cfg: Settings, *, path: str | None = None) -> NautilusParquetCatalog:
    return NautilusParquetCatalog(Path(path or cfg.catalog_path), fees=cfg.fee_schedule())


def taker_flow_catalog(cfg: Settings, *, path: str | None = None) -> ParquetTakerFlowCatalog:
    """Per-bar taker split, a sibling series of the bar catalog under the same root."""
    return ParquetTakerFlowCatalog(Path(path or cfg.catalog_path))


def orderbook_catalog(cfg: Settings, *, path: str | None = None) -> ParquetOrderBookCatalog:
    """L2 Orderbook snapshots."""
    return ParquetOrderBookCatalog(Path(path or cfg.catalog_path))


def research_feed(cfg: Settings, *, path: str | None = None) -> ResearchBarFeed:
    """Bars plus the taker-flow join. One place, so no run silently loses the join."""
    return ResearchBarFeed(catalog(cfg, path=path), taker_flow=taker_flow_catalog(cfg, path=path))


def notifier(cfg: Settings | None = None) -> AlertNotifier:
    resolved = cfg or settings()
    return build_notifier(
        telegram_token=resolved.telegram_bot_token,
        telegram_chat_id=resolved.telegram_chat_id,
        webhook_url=resolved.alert_webhook_url,
    )


class _TickFeedAdapter:
    def __init__(self, catalog: ParquetAggTradesCatalog) -> None:
        self._catalog = catalog

    def load(self, request: BacktestRequest) -> list[AggTrade]:
        symbol = binance_symbol_for_instrument(request.instrument_id)
        if not symbol:
            return []
        return self._catalog.load(symbol=symbol, start=request.start, end=request.end)

class _BookFeedAdapter:
    def __init__(self, catalog: ParquetOrderBookCatalog) -> None:
        self._catalog = catalog

    def load(self, request: BacktestRequest) -> list[OrderBookSnapshot]:
        symbol = binance_symbol_for_instrument(request.instrument_id)
        if not symbol:
            return []
        return self._catalog.load(symbol=symbol, start=request.start, end=request.end)


def research_use_case(cfg: Settings | None = None) -> RunResearchBacktest:
    resolved = cfg or settings()
    tick_catalog = ParquetAggTradesCatalog(Path(resolved.catalog_path))
    book_catalog = orderbook_catalog(resolved)
    tick_feed = _TickFeedAdapter(tick_catalog)
    book_feed = _BookFeedAdapter(book_catalog)
    return RunResearchBacktest(NautilusResearchBacktest(), research_feed(resolved), tick_feed, book_feed)


def walk_forward_use_case(cfg: Settings | None = None) -> RunWalkForward:
    resolved = cfg or settings()
    tick_catalog = ParquetAggTradesCatalog(Path(resolved.catalog_path))
    book_catalog = orderbook_catalog(resolved)
    tick_feed = _TickFeedAdapter(tick_catalog)
    book_feed = _BookFeedAdapter(book_catalog)
    return RunWalkForward(NautilusResearchBacktest(), research_feed(resolved), tick_feed, book_feed)


def overfit_audit_use_case(cfg: Settings | None = None) -> RunOverfitAudit:
    resolved = cfg or settings()
    tick_catalog = ParquetAggTradesCatalog(Path(resolved.catalog_path))
    book_catalog = orderbook_catalog(resolved)
    tick_feed = _TickFeedAdapter(tick_catalog)
    book_feed = _BookFeedAdapter(book_catalog)
    return RunOverfitAudit(NautilusResearchBacktest(), research_feed(resolved), tick_feed, book_feed)


def llm_completer(
    cfg: Settings,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> ChatCompleter:
    """Offline research only. Raises LlmRequestError when no key is configured.

    Kept out of every trading path on purpose: nothing in the backtest or execution
    layer may call a language model (docs/14-llm-model-u-torhivli.md, section 1).
    """
    return OpenAICompatibleChatClient(
        api_key=cfg.llm_api_key or "",
        base_url=base_url or cfg.llm_base_url,
        model=model or cfg.llm_model,
        temperature=cfg.llm_temperature,
        timeout_seconds=cfg.llm_timeout_seconds,
    )


def alpha_proposal_request(
    cfg: Settings,
    *,
    prompt: str,
    count: int = 5,
    as_of: date | None = None,
    output_dir: str | None = None,
    slug: str | None = None,
) -> AlphaProposalRequest:
    return AlphaProposalRequest(
        prompt_file=str(resolve_prompt_path(prompt, cfg.llm_prompts_dir)),
        output_dir=output_dir or cfg.llm_hypotheses_dir,
        count=count,
        as_of=as_of,
        slug=slug,
    )


def journal_paths(cfg: Settings) -> tuple[Path, Path]:
    """Human markdown log and machine JSONL log, in that order."""
    return Path(cfg.journal_path), Path(cfg.journal_jsonl_path)


def overfit_audit_request(
    cfg: Settings,
    *,
    bar_count: int,
    robot: RobotName | None = None,
    source: BarOrigin = BarOrigin.CATALOG,
    blocks: int = 8,
    stress_slice: str | None = None,
) -> OverfitAuditRequest:
    return OverfitAuditRequest(
        backtest=research_request(
            cfg,
            bar_count=bar_count,
            robot=robot,
            source=source,
            stress_slice=stress_slice,
        ),
        blocks=blocks,
    )


def ingest_use_case(cfg: Settings | None = None) -> IngestHistoricalBars:
    resolved = cfg or settings()
    store = catalog(resolved)
    return IngestHistoricalBars(
        # The resilient client is the only HTTP path used for ingest: a long
        # multi-symbol run is exactly where a bare 429/418 would otherwise kill
        # the process mid-series and leave a truncated catalog behind.
        BinancePublicKlines(ResilientJsonClient()),
        store,
        catalog_path=str(store.path),
        taker_flow=taker_flow_catalog(resolved),
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
        use_tick_vpin=cfg.use_tick_vpin,
        use_hawkes=cfg.use_hawkes,
        hawkes_baseline=cfg.hawkes_baseline,
        hawkes_alpha=cfg.hawkes_alpha,
        hawkes_beta=cfg.hawkes_beta,
        hawkes_toxic_threshold=cfg.hawkes_toxic_threshold,
        vpin_bucket_volume=cfg.vpin_bucket_volume,
        vpin_toxic_threshold=cfg.vpin_toxic_threshold,
        vpin_momentum_ema_period=cfg.vpin_momentum_ema_period,
        vpin_momentum_atr_multiple=cfg.vpin_momentum_atr_multiple,
        formulaic_model_path=cfg.formulaic_model_path,
        formulaic_threshold=cfg.formulaic_threshold,
        meta_label_model_path=cfg.meta_label_model_path,
        meta_label_threshold=cfg.meta_label_threshold,
        adaptive_params=cfg.adaptive_ema_params(),
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


def funding_ingest_request(
    cfg: Settings,
    *,
    start: datetime,
    end: datetime,
    symbol: str | None = None,
) -> FundingIngestRequest:
    require_simulated_mode(cfg.trading_mode)
    return FundingIngestRequest(
        mode=cfg.trading_mode,
        symbol=symbol or cfg.binance_symbol,
        start=start,
        end=end,
    )


def ingest_funding_use_case(cfg: Settings | None = None) -> IngestFundingHistory:
    resolved = cfg or settings()
    store = ParquetFundingCatalog(Path(resolved.catalog_path))
    return IngestFundingHistory(
        BinancePublicFunding(ResilientJsonClient()),
        store,
        catalog_path=str(store.path),
    )


def ingest_agg_trades_use_case(cfg: Settings | None = None) -> IngestAggTrades:
    resolved = cfg or settings()
    store = ParquetAggTradesCatalog(Path(resolved.catalog_path))
    return IngestAggTrades(
        BinancePublicAggTrades(ResilientJsonClient()),
        store,
        catalog_path=str(store.path),
    )


def ingest_orderbook_use_case(cfg: Settings | None = None) -> IngestOrderBook:
    resolved = cfg or settings()
    return IngestOrderBook(orderbook_catalog(resolved))


def ingest_agg_trades_request(
    cfg: Settings,
    *,
    start: datetime,
    end: datetime,
    symbol: str | None = None,
) -> IngestAggTradesRequest:
    require_simulated_mode(cfg.trading_mode)
    resolved_symbol = symbol or cfg.binance_symbol
    instrument_id = binance_symbol_to_instrument_id(resolved_symbol)
    return IngestAggTradesRequest(
        mode=cfg.trading_mode,
        symbol=resolved_symbol,
        instrument_id=instrument_id,
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
