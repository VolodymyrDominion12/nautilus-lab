from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from nautilus_lab.application.catalog_queries import incremental_ingest_start
from nautilus_lab.application.dtos import (
    BacktestReport,
    MultiWindowReport,
    PaperSessionReport,
    WalkForwardReport,
    apply_selected,
)
from nautilus_lab.application.journal import JournalEntry, record_run
from nautilus_lab.application.preregistration import register, research_terms, verdict_for
from nautilus_lab.application.promotion_gate import evaluate_gate
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_alpha_proposal import ProposeJobConfig, execute_propose
from nautilus_lab.application.run_paper import (
    PAPER_SUPPORTED_ROBOTS,
    require_paper_support,
)
from nautilus_lab.application.run_walk_forward import window_return
from nautilus_lab.application.scan_triangular import scan_triangular_opportunities
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.errors import (
    CatalogEmptyError,
    InvalidHypothesisError,
    InvalidWindowError,
    LiveTradingDisabledError,
    PaperTradingNotReadyError,
)
from nautilus_lab.domain.preregistration import PreregistrationVerdict
from nautilus_lab.domain.provenance import RunManifest
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.llm_client import LlmRequestError
from nautilus_lab.infrastructure.paper_sessions import append_session
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import (
    collect_live_agg_trades_use_case,
    funding_ingest_request,
    ingest_agg_trades_request,
    ingest_agg_trades_use_case,
    ingest_funding_use_case,
    ingest_orderbook_use_case,
    ingest_request,
    ingest_use_case,
    journal_paths,
    live_paper_use_case,
    notifier,
    overfit_audit_request,
    overfit_audit_use_case,
    paper_request,
    paper_use_case,
    param_selection_use_case,
    preregistration_store,
    research_request,
    research_use_case,
    run_manifest,
    settings,
    taker_flow_catalog,
    walk_forward_request,
    walk_forward_use_case,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lab",
        description="Research-first trading robots on NautilusTrader.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser(
        "ingest",
        help="Download public Binance klines into a Nautilus Parquet catalog",
    )
    ingest.add_argument("--start", help="UTC start (YYYY-MM-DD). Default: 365 days ago")
    ingest.add_argument("--end", help="UTC end exclusive (YYYY-MM-DD). Default: now")
    ingest.add_argument("--catalog", help="Catalog directory (default: settings/catalog)")
    ingest.add_argument(
        "--symbols",
        help="Comma-separated Binance symbols (default: settings binance_symbols)",
    )
    ingest.add_argument(
        "--incremental",
        action="store_true",
        help="Append only bars after the last stored bar per symbol (skip if up to date)",
    )
    ingest.add_argument(
        "--funding",
        action="store_true",
        help=(
            "Ingest USD-M funding settlements instead of klines "
            "(event series, stored under catalog/data/funding/)"
        ),
    )
    ingest.add_argument(
        "--trades",
        action="store_true",
        help=(
            "Ingest aggregated trades (ticks) instead of klines "
            "(stored under catalog/data/agg_trade/). "
            "Enables real VPIN and Hawkes computation without a bar-volume proxy."
        ),
    )
    ingest.add_argument(
        "--live-ticks",
        type=float,
        default=None,
        metavar="MINUTES",
        help=(
            "Collect live aggTrades from the public WebSocket for this many minutes "
            "instead of walking REST history. Use it when the REST path cannot deliver "
            "the window in reasonable time (see docs/24 section 5.2)"
        ),
    )
    ingest.add_argument(
        "--depth",
        action="store_true",
        help=(
            "Live ingestion of L2 Orderbook depth snapshots via WebSocket "
            "(stored under catalog/data/orderbook/). Runs indefinitely until interrupted."
        ),
    )

    research = sub.add_parser("research", help="Run a simulated backtest (default path)")
    research.add_argument("--bars", type=int, default=3000, help="Synthetic bar count")
    research.add_argument(
        "--robot",
        choices=tuple(item.value for item in RobotName),
        default=None,
        help="Strategy robot",
    )
    research.add_argument(
        "--synthetic",
        action="store_true",
        help="Use deterministic synthetic bars instead of the Parquet catalog",
    )
    research.add_argument(
        "--full-sample",
        action="store_true",
        help="One catalog run on the whole series (in-sample only, not a report)",
    )
    research.add_argument(
        "--walk-forward",
        action="store_true",
        default=None,
        help="Fit on in-sample, report out-of-sample (default for catalog data)",
    )
    research.add_argument("--is-start", help="In-sample start UTC (YYYY-MM-DD)")
    research.add_argument("--is-end", help="In-sample end exclusive UTC")
    research.add_argument("--oos-start", help="Out-of-sample start UTC")
    research.add_argument("--oos-end", help="Out-of-sample end exclusive UTC")
    research.add_argument(
        "--is-fraction",
        type=Decimal,
        default=Decimal("0.7"),
        help="Anchored split when dates are omitted (default 0.7)",
    )
    research.add_argument("--catalog", help="Catalog directory (default: settings/catalog)")
    research.add_argument(
        "--slice",
        help="Named stress slice: covid2020, ftx2022, etf2024",
    )
    research.add_argument(
        "--embargo-bars",
        type=int,
        default=None,
        help="Purged embargo bars between IS and OOS",
    )
    research.add_argument(
        "--bar-vpin",
        action="store_true",
        help="Enable bar-level VPIN regime filter (regime robot)",
    )
    research.add_argument(
        "--tick-vpin",
        action="store_true",
        help="Enable tick-level VPIN regime filter (regime robot)",
    )
    research.add_argument(
        "--hawkes",
        action="store_true",
        help="Enable tick-level Hawkes process regime filter (regime robot)",
    )
    research.add_argument(
        "--tearsheet",
        help="Path to save interactive HTML tearsheet (e.g. reports/tearsheet.html)",
    )
    research.add_argument(
        "--optuna",
        action="store_true",
        help="Use Bayesian hyperparameter optimization (Optuna) on in-sample",
    )
    research.add_argument(
        "--trials",
        type=int,
        default=20,
        help="Number of Optuna trials (default: 20)",
    )
    research.add_argument(
        "--folds",
        type=int,
        default=1,
        help=(
            "Rolling walk-forward folds. >= 2 runs one walk-forward per fold and "
            "reports the out-of-sample aggregate instead of a single split"
        ),
    )
    research.add_argument(
        "--notify",
        action="store_true",
        help="Send notification on completion via Telegram/Webhook",
    )
    research.add_argument(
        "--pbo",
        action="store_true",
        help=(
            "Overfitting audit (PBO/CSCV): score every grid configuration on every "
            "history block and report how often the in-sample winner fails out of sample"
        ),
    )
    research.add_argument(
        "--pbo-blocks",
        type=int,
        default=8,
        help="Contiguous history blocks for --pbo, even (default: 8)",
    )
    research.add_argument(
        "--journal",
        action="store_true",
        help="Append a row for this run to the research journal (table + journal.jsonl)",
    )
    research.add_argument(
        "--register",
        metavar="HYPOTHESIS",
        help=(
            "Pre-register this catalog walk-forward (needs --folds >= 2): write its terms "
            "and fold windows to research/preregistrations/ without running anything. "
            "Only a later run with matching terms can be promoted"
        ),
    )

    paper = sub.add_parser(
        "paper",
        help="Paper session: run a frozen robot forward, full ledger, no orders sent",
    )
    paper.add_argument("--bars", type=int, default=2000, help="Bars in the session window")
    paper.add_argument(
        "--robot",
        choices=sorted(item.value for item in PAPER_SUPPORTED_ROBOTS),
        default="regime",
    )
    paper.add_argument(
        "--source",
        choices=("catalog", "synthetic", "live"),
        default="catalog",
        help=(
            "Where the closed bars come from: catalog (real history), synthetic "
            "(tests only), or live (public Binance WebSocket tail after a catalog warm-up)"
        ),
    )
    paper.add_argument(
        "--live-bars",
        type=int,
        default=5,
        help=(
            "With --source live: how many closed bars to wait for from the socket. "
            "--bars still sets the total window, so the rest is catalog warm-up"
        ),
    )
    paper.add_argument(
        "--live-timeout",
        type=float,
        default=900.0,
        help="With --source live: give up after this many seconds without enough bars",
    )
    paper.add_argument(
        "--select-on-is",
        action="store_true",
        help=(
            "Grid-search the robot's parameters on the history BEFORE the session window "
            "(with an embargo gap) and run the session with that configuration. Without "
            "this, a robot whose defaults never trade reports fills=0 and looks broken"
        ),
    )
    paper.add_argument(
        "--embargo-bars",
        type=int,
        default=None,
        help="Embargo gap between the selection window and the session window",
    )
    paper.add_argument(
        "--tick-vpin",
        action="store_true",
        help=(
            "Enable the tick-level VPIN filter (needs an aggTrades series in the "
            "catalog: 'lab ingest --trades')"
        ),
    )
    paper.add_argument(
        "--hawkes",
        action="store_true",
        help="Enable the tick-level Hawkes filter (needs an aggTrades series)",
    )
    paper.add_argument(
        "--journal",
        action="store_true",
        help="Append this session to reports/paper/sessions.jsonl",
    )

    scan = sub.add_parser("scan", help="Research scanners (no orders)")
    scan.add_argument(
        "--triangular",
        action="store_true",
        help="Scan for triangular arbitrage cycles in sample rates",
    )

    propose = sub.add_parser(
        "propose",
        help="Ask a model for alpha hypotheses offline (research only, never trades)",
    )
    propose.add_argument(
        "--prompt",
        default="01-generate-alphas.md",
        help="Prompt file, or a bare name inside the configured prompts directory",
    )
    propose.add_argument("--count", type=int, default=5, help="How many hypotheses to ask for")
    propose.add_argument(
        "--as-of",
        type=parse_date,
        default=None,
        help="Knowledge cutoff date stated to the model (YYYY-MM-DD)",
    )
    propose.add_argument("--model", default=None, help="Model id (default: settings)")
    propose.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible base URL (default: settings; local servers are fine)",
    )
    propose.add_argument("--output-dir", default=None, help="Artifact directory")
    propose.add_argument("--slug", default=None, help="Override the artifact base name")
    propose.add_argument(
        "--dry-run",
        action="store_true",
        help="Render the prompt, call nothing, write nothing (needs no API key)",
    )
    propose.add_argument(
        "--journal",
        action="store_true",
        help="Append a pending row for this proposal to the research journal",
    )

    ml = sub.add_parser("ml", help="Machine learning pipelines")
    ml_sub = ml.add_subparsers(dest="ml_command", required=True)
    train = ml_sub.add_parser("train", help="Train a model")
    train.add_argument("--model-type", choices=["formulaic", "meta_label", "obi"], required=True)
    train.add_argument("--catalog", help="Catalog directory (default: settings/catalog)")
    train.add_argument("--instrument", help="Instrument ID")
    train.add_argument("--interval", help="Bar interval")
    train.add_argument("--output", help="Model output path")
    train.add_argument("--folds", type=int, default=5, help="Purged K-Fold folds (default: 5)")
    train.add_argument("--embargo", type=int, default=10, help="Embargo bars (default: 10)")
    train.add_argument("--horizon", type=int, default=5, help="Prediction horizon")
    train.add_argument("--profit", default="2", help="Triple barrier profit multiple")
    train.add_argument("--stop", default="1", help="Triple barrier stop multiple")
    train.add_argument("--vol-window", type=int, default=20, help="Volatility window")
    train.add_argument("--start", help="UTC start (YYYY-MM-DD)")
    train.add_argument("--end", help="UTC end (YYYY-MM-DD)")
    train.add_argument("--threshold", default="0.55", help="Classifier probability threshold")

    xsmom = sub.add_parser(
        "xsmom",
        help="Cross-sectional momentum over a basket of spot coins: walk-forward (+ audit)",
    )
    xsmom.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,DOGEUSDT",
        help="Comma-separated Binance spot symbols already in the catalog",
    )
    xsmom.add_argument("--interval", default=None, help="Bar interval (default: settings)")
    xsmom.add_argument("--catalog", help="Catalog directory (default: settings/catalog)")
    xsmom.add_argument("--start", help="UTC start (YYYY-MM-DD)")
    xsmom.add_argument("--end", help="UTC end exclusive (YYYY-MM-DD)")
    xsmom.add_argument("--folds", type=int, default=6, help="Rolling walk-forward folds")
    xsmom.add_argument(
        "--is-fraction", default="0.5", help="Share of history for the first selection block"
    )
    xsmom.add_argument("--lookbacks", default="14,30,60", help="Momentum lookbacks, in bars")
    xsmom.add_argument("--top-n", default="2,3", help="Coins held, grid")
    xsmom.add_argument("--rebalance", default="7", help="Rebalance period in bars, grid")
    xsmom.add_argument(
        "--no-positive-filter",
        action="store_true",
        help="Hold the top coins even when their own momentum is negative",
    )
    xsmom.add_argument(
        "--inverse-vol", action="store_true", help="Weight holdings by inverse volatility"
    )
    xsmom.add_argument(
        "--slippage-bps", default="5", help="Adverse slippage per fill, in basis points"
    )
    xsmom.add_argument(
        "--metric",
        choices=["pnl", "sharpe", "calmar"],
        default="calmar",
        help="In-sample selection metric (default: calmar)",
    )
    xsmom.add_argument(
        "--pbo", action="store_true", help="Also run the PBO/DSR audit and the full gate"
    )
    xsmom.add_argument("--pbo-blocks", type=int, default=8, help="Blocks for the audit")

    sub.add_parser("live", help="Live trading (always fail closed)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = settings()
    catalog_path = getattr(args, "catalog", None)
    if catalog_path:
        cfg = cfg.model_copy(update={"catalog_path": catalog_path})
    if getattr(args, "bar_vpin", False):
        cfg = cfg.model_copy(update={"use_bar_vpin": True})
    if getattr(args, "tick_vpin", False):
        cfg = cfg.model_copy(update={"use_tick_vpin": True})
    if getattr(args, "hawkes", False):
        cfg = cfg.model_copy(update={"use_hawkes": True})
    if getattr(args, "embargo_bars", None) is not None:
        cfg = cfg.model_copy(update={"embargo_bars": args.embargo_bars})
    try:
        if args.command == "ingest":
            return _run_ingest(cfg, args)
        if args.command == "research":
            return _run_research(cfg, args)
        if args.command == "paper":
            return _run_paper(cfg, args)
        if args.command == "scan":
            return _run_scan(args)
        if args.command == "propose":
            return _run_propose(cfg, args)
        if args.command == "ml":
            return _run_ml_train(cfg, args)
        if args.command == "xsmom":
            return _run_xsmom(cfg, args)
        if args.command == "live":
            require_simulated_mode(TradingMode.LIVE)
    except (
        LiveTradingDisabledError,
        PaperTradingNotReadyError,
        CatalogEmptyError,
        InvalidWindowError,
        LlmRequestError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


def _run_ingest(cfg: Settings, args: argparse.Namespace) -> int:
    default_start = parse_utc(args.start) if args.start else datetime.now(UTC) - timedelta(days=365)
    end = parse_utc(args.end) if args.end else datetime.now(UTC)
    symbols = (
        [item.strip() for item in args.symbols.split(",") if item.strip()]
        if args.symbols
        else cfg.binance_symbols
    )
    if getattr(args, "funding", False):
        return _run_ingest_funding(cfg, symbols=symbols, start=default_start, end=end)
    if getattr(args, "trades", False):
        minutes = getattr(args, "live_ticks", None)
        if minutes is not None:
            return _run_collect_live_ticks(cfg, symbols=symbols, minutes=minutes)
        return _run_ingest_agg_trades(cfg, symbols=symbols, start=default_start, end=end)
    if getattr(args, "depth", False):
        return _run_ingest_depth(cfg, symbols=symbols)
    use_case = ingest_use_case(cfg)
    incremental = bool(getattr(args, "incremental", False))
    for symbol in symbols:
        start = default_start
        if incremental:
            inc_start = incremental_ingest_start(
                cfg,
                catalog_path=cfg.catalog_path,
                symbol=symbol,
                default_start=default_start,
                end=end,
            )
            # `--incremental` walks forward from the last stored bar, so a catalog that
            # predates the taker-flow series would stay without it forever: the bars are
            # "up to date", the order-flow field is not. Backfill the full window once,
            # out loud, instead of leaving a silently degraded feature behind.
            if inc_start is None and not taker_flow_catalog(cfg).series_exists(
                symbol, cfg.bar_interval
            ):
                print(f"symbol={symbol} taker-flow backfill: re-reading the full window")
                inc_start = default_start
            if inc_start is None:
                print(f"symbol={symbol} up-to-date (incremental skip)")
                continue
            start = inc_start
        report = use_case.execute(ingest_request(cfg, start=start, end=end, symbol=symbol))
        print(
            f"symbol={symbol} wrote={report.bars_written} "
            f"taker_flow={report.taker_flow_rows} "
            f"first={report.first_ts.isoformat()} last={report.last_ts.isoformat()} "
            f"catalog={report.catalog_path}"
        )
    return 0


def _run_collect_live_ticks(
    cfg: Settings,
    *,
    symbols: list[str],
    minutes: float,
) -> int:
    """Collect live aggTrades from the public WebSocket for a bounded time.

    Bounded on purpose: an unbounded collector is a process nobody dares stop. The
    deadline is checked against the wall clock, so a dead market ends the run instead
    of idling forever, and whatever arrived before it is already on disk.
    """
    if minutes <= 0:
        raise ValueError("--live-ticks must be a positive number of minutes")
    duration = timedelta(minutes=minutes)
    for symbol in symbols:

        def _progress(written: int, last_ts: datetime | None, _symbol: str = symbol) -> None:
            stamp = "n/a" if last_ts is None else last_ts.isoformat()
            print(f"  {_symbol} trades={written} last={stamp}", flush=True)

        use_case = collect_live_agg_trades_use_case(cfg, symbol=symbol, progress=_progress)
        report = use_case.execute(duration=duration)
        print(report.summary_line())
    return 0


def _run_ingest_agg_trades(
    cfg: Settings,
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> int:
    """Ingest aggregated trades (ticks) for research-grade VPIN and Hawkes.

    Data is stored under ``catalog/data/agg_trade/<SYMBOL>/``, one Parquet file per
    UTC day.  No API keys required — this is a public Binance endpoint.

    Progress is printed per day. A tick window is measured in hours of downloading,
    and the earlier silent version could not be told apart from a hung one.
    """

    def _progress(day: datetime, trades: int) -> None:
        print(
            f"  {day.date().isoformat()} trades={trades}",
            flush=True,
        )

    use_case = ingest_agg_trades_use_case(cfg, progress=_progress)
    for symbol in symbols:
        report = use_case.execute(
            ingest_agg_trades_request(cfg, start=start, end=end, symbol=symbol)
        )
        print(
            f"symbol={report.symbol} trades={report.trades_written} "
            f"first={report.first_ts.isoformat()} last={report.last_ts.isoformat()} "
            f"catalog={report.catalog_path}"
        )
    return 0


def _run_ingest_funding(
    cfg: Settings,
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> int:
    """Ingest the funding series. Symbol universe is shared with the kline ingest.

    Binance serves funding history on USD-M futures, so the same `*USDT` symbols the
    lab already ingests work unchanged; there is no separate perp symbol mapping.
    """
    use_case = ingest_funding_use_case(cfg)
    for symbol in symbols:
        report = use_case.execute(funding_ingest_request(cfg, start=start, end=end, symbol=symbol))
        print(
            f"symbol={symbol} funding={report.snapshots_written} "
            f"missing_index_price={report.missing_index_price} "
            f"first={report.first_ts.isoformat()} last={report.last_ts.isoformat()} "
            f"catalog={report.catalog_path}"
        )
    return 0


def _run_ingest_depth(cfg: Settings, *, symbols: list[str]) -> int:
    """Ingest live L2 orderbook snapshots via WebSocket. Blocks until interrupted."""
    if not symbols:
        print("At least one symbol required.", file=sys.stderr)
        return 1

    use_case = ingest_orderbook_use_case(cfg)
    symbol = symbols[0]
    if len(symbols) > 1:
        print(f"Warning: Only one symbol supported for --depth currently. Using {symbol}.")

    print(f"Starting live L2 orderbook ingest for {symbol} to {cfg.catalog_path} ...")
    try:
        use_case(symbol)
    except KeyboardInterrupt:
        print("\nIngestion interrupted by user.")
    return 0


def _run_research(cfg: Settings, args: argparse.Namespace) -> int:
    robot = RobotName(args.robot) if args.robot is not None else None
    tearsheet = getattr(args, "tearsheet", None)
    optuna_enabled = getattr(args, "optuna", False)
    trials = getattr(args, "trials", 20)
    should_notify = getattr(args, "notify", False)
    folds = getattr(args, "folds", 1)
    if folds < 1:
        # Without this, --folds 0 silently fell through to the single-split path and
        # reported one window as if the request had been honoured.
        raise ValueError(f"--folds must be >= 1, got {folds}")
    subject = f"{(robot or cfg.robot).value} {cfg.instrument_id}"
    journal_enabled = _journal_enabled(cfg, args)
    started_at = datetime.now(UTC)
    if getattr(args, "register", None) is not None:
        return _run_register(cfg, args, robot, folds)
    manifest = _announce_manifest(cfg, synthetic=bool(args.synthetic))

    if getattr(args, "pbo", False):
        return _run_pbo(cfg, args, robot, manifest)

    if args.synthetic:
        if getattr(args, "walk_forward", False) or optuna_enabled or folds > 1:
            window = _optional_window(args)
            request = walk_forward_request(
                cfg,
                robot=robot,
                source=BarOrigin.SYNTHETIC,
                bar_count=args.bars,
                window=window,
                in_sample_fraction=args.is_fraction,
                stress_slice=args.slice,
                tearsheet_path=tearsheet,
                use_optuna=optuna_enabled,
                optuna_trials=trials,
                folds=folds,
            )
            use_case = walk_forward_use_case(cfg)
            if folds > 1:
                multi = use_case.execute_multi(request)
                _print_multi_window(multi)
                if should_notify:
                    notifier(cfg).notify(
                        f"Synthetic multi-window walk-forward complete: {multi.summary_line()}"
                    )
                if journal_enabled:
                    _record_journal(
                        cfg,
                        manifest,
                        _journal_entry(
                            subject=subject,
                            gates=f"walk-forward synthetic folds={folds}",
                            oos_return=multi.mean_oos_return,
                            buy_and_hold=multi.mean_buy_and_hold_return,
                            fills=multi.total_oos_fills,
                            reason=(
                                f"auto: profitable {multi.profitable_folds}"
                                f"/{len(multi.folds)} folds"
                            ),
                            artifact=tearsheet,
                        ),
                    )
                return 0
            wf = use_case.execute(request)
            _print_walk_forward(wf)
            if should_notify:
                notifier(cfg).notify(
                    f"Synthetic walk-forward complete: IS={wf.in_sample.ending_balance} "
                    f"OOS={wf.out_of_sample.ending_balance}"
                )
            if journal_enabled:
                _record_journal(
                    cfg,
                    manifest,
                    _journal_entry(
                        subject=subject,
                        gates="walk-forward synthetic single split",
                        oos_return=window_return(wf.out_of_sample, cfg.starting_equity),
                        fills=wf.out_of_sample.fills,
                        reason="auto: single split; buy&hold not measured",
                        artifact=tearsheet,
                    ),
                )
            return 0

        report = research_use_case(cfg).execute(
            research_request(
                cfg,
                bar_count=args.bars,
                robot=robot,
                source=BarOrigin.SYNTHETIC,
                stress_slice=args.slice,
                tearsheet_path=tearsheet,
            )
        )
        _print_backtest(report)
        if should_notify:
            notifier(cfg).notify(
                f"Synthetic backtest complete: fills={report.fills} ending={report.ending_balance}"
            )
        if journal_enabled:
            _record_journal(
                cfg,
                manifest,
                _journal_entry(
                    subject=subject,
                    gates="synthetic backtest (no OOS split)",
                    fills=report.fills,
                    reason=(
                        "auto: in-sample only; "
                        f"IS return {_pct(window_return(report, cfg.starting_equity))} "
                        "(not an OOS number)"
                    ),
                    artifact=tearsheet,
                ),
            )
        return 0

    walk_forward = True if args.walk_forward else not args.full_sample
    if args.full_sample:
        walk_forward = False
    if walk_forward:
        window = _optional_window(args)
        request = walk_forward_request(
            cfg,
            robot=robot,
            window=window,
            in_sample_fraction=args.is_fraction,
            stress_slice=args.slice,
            tearsheet_path=tearsheet,
            use_optuna=optuna_enabled,
            optuna_trials=trials,
            folds=folds,
        )
        use_case = walk_forward_use_case(cfg)
        if folds > 1:
            multi = use_case.execute_multi(request)
            registration = verdict_for(
                request,
                [fold.window for fold in multi.folds],
                preregistration_store(cfg),
                run_started_at=started_at,
            )
            manifest = replace(manifest, preregistration_sha256=registration.run_sha256)
            _print_multi_window(multi, registration)
            if should_notify:
                notifier(cfg).notify(
                    "Catalog multi-window walk-forward complete: "
                    f"{multi.summary_line()}{_breach_suffix(_multi_window_breach_line(multi))}"
                )
            if journal_enabled:
                _record_journal(
                    cfg,
                    manifest,
                    _journal_entry(
                        subject=subject,
                        gates=(
                            f"walk-forward catalog folds={folds} "
                            f"preregistration={registration.status.value}"
                        ),
                        oos_return=multi.mean_oos_return,
                        buy_and_hold=multi.mean_buy_and_hold_return,
                        fills=multi.total_oos_fills,
                        reason=(
                            f"auto: profitable {multi.profitable_folds}/{len(multi.folds)} folds"
                        ),
                        artifact=tearsheet,
                    ),
                )
            return 0
        wf = use_case.execute(request)
        _print_walk_forward(wf)
        if should_notify:
            notifier(cfg).notify(
                f"Catalog walk-forward complete: IS={wf.in_sample.ending_balance} "
                f"OOS={wf.out_of_sample.ending_balance}"
                f"{_breach_suffix(_breach_line('oos', wf.out_of_sample))}"
            )
        if journal_enabled:
            _record_journal(
                cfg,
                manifest,
                _journal_entry(
                    subject=subject,
                    gates="walk-forward catalog single split",
                    oos_return=window_return(wf.out_of_sample, cfg.starting_equity),
                    fills=wf.out_of_sample.fills,
                    reason="auto: single split; buy&hold not measured",
                    artifact=tearsheet,
                ),
            )
        return 0

    report = research_use_case(cfg).execute(
        research_request(
            cfg,
            bar_count=args.bars,
            robot=robot,
            source=BarOrigin.CATALOG,
            stress_slice=args.slice,
            tearsheet_path=tearsheet,
        )
    )
    print("full-sample catalog run (in-sample only; not an out-of-sample report)")
    _print_backtest(report)
    if should_notify:
        notifier(cfg).notify(
            f"Full-sample backtest complete: fills={report.fills} ending={report.ending_balance}"
        )
    if journal_enabled:
        _record_journal(
            cfg,
            manifest,
            _journal_entry(
                subject=subject,
                gates="full-sample catalog (no OOS split)",
                fills=report.fills,
                reason=(
                    "auto: in-sample only; "
                    f"IS return {_pct(window_return(report, cfg.starting_equity))} "
                    "(not an OOS number)"
                ),
                artifact=tearsheet,
            ),
        )
    return 0


def _run_register(
    cfg: Settings, args: argparse.Namespace, robot: RobotName | None, folds: int
) -> int:
    """Write down a walk-forward's terms before it runs (docs/27 R-2).

    The fold windows come from the same data and the same rolling split the run will use,
    computed here without a single backtest, so nothing has been seen yet.
    """
    if args.synthetic:
        raise ValueError("--register is for catalog data; synthetic bars are not a test")
    if folds < 2:
        raise ValueError("--register needs --folds >= 2 (the promotion gate reads folds)")
    if getattr(args, "pbo", False):
        raise ValueError("--register describes the walk-forward; run it without --pbo")
    request = walk_forward_request(
        cfg,
        robot=robot,
        window=None,
        in_sample_fraction=args.is_fraction,
        stress_slice=args.slice,
        use_optuna=getattr(args, "optuna", False),
        optuna_trials=getattr(args, "trials", 20),
        folds=folds,
    )
    windows = walk_forward_use_case(cfg).plan_multi(request)
    terms = research_terms(request, windows)
    registration, where = register(
        terms,
        hypothesis=args.register,
        registered_at=datetime.now(UTC),
        store=preregistration_store(cfg),
    )
    print(f"registered {registration.terms_sha256} -> {where}")
    print(f"robot={terms.robot} dataset={terms.dataset} grid={len(terms.grid)} folds={terms.folds}")
    for index, (start, end) in enumerate(terms.oos_windows):
        print(f"  fold {index} OOS=[{start}, {end})")
    print("run the same command without --register; only matching terms can be promoted")
    return 0


def _run_pbo(
    cfg: Settings, args: argparse.Namespace, robot: RobotName | None, manifest: RunManifest
) -> int:
    blocks = getattr(args, "pbo_blocks", 8)
    if blocks < 2 or blocks % 2:
        raise ValueError(f"--pbo-blocks must be an even number >= 2 (CSCV), got {blocks}")
    if getattr(args, "optuna", False):
        # PBO/CSCV already iterates over all grid configurations on every block;
        # adding Optuna on top would fit a separate HPO search inside each block,
        # which is neither the documented protocol nor what the user likely expects.
        # Warn explicitly rather than silently ignoring the flag.
        print(
            "warning: --optuna is ignored when --pbo is active. "
            "PBO evaluates every grid configuration on every block; "
            "Optuna HPO cannot be composed with that protocol.",
            file=sys.stderr,
        )
    if getattr(args, "tearsheet", None):
        # There is no single "the" run to draw: the audit simulates blocks x
        # configurations. Failing loudly beats writing a tearsheet of whichever run
        # happened to finish last and calling it the audit's result.
        raise ValueError(
            "--pbo simulates many runs (blocks x configurations), so --tearsheet has "
            "nothing single to draw; use one or the other"
        )
    request = overfit_audit_request(
        cfg,
        bar_count=args.bars,
        robot=robot,
        source=BarOrigin.SYNTHETIC if args.synthetic else BarOrigin.CATALOG,
        blocks=blocks,
        stress_slice=args.slice,
    )
    report = overfit_audit_use_case(cfg).execute(request)
    print(report.notes)
    print(f"blocks={report.blocks} configurations={report.configuration_count}")
    for index, label in enumerate(report.labels):
        cells = " ".join(_pct(row[index]) for row in report.block_returns)
        print(f"  [{index}] {label} :: {cells}")
    print(report.summary_line())
    print(report.deflated_sharpe.summary_line())
    print(evaluate_gate(None, report).summary_line())
    if getattr(args, "notify", False):
        notifier(cfg).notify(f"Overfitting audit complete: {report.summary_line()}")
    if _journal_enabled(cfg, args):
        _record_journal(
            cfg,
            manifest,
            _journal_entry(
                subject=f"{(robot or cfg.robot).value} {cfg.instrument_id}",
                gates=(
                    f"PBO/CSCV blocks={report.blocks} configurations={report.configuration_count}"
                ),
                reason=report.summary_line(),
            ),
        )
    return 0


def _run_paper(cfg: Settings, args: argparse.Namespace) -> int:
    """Run a paper session: real ledger, real fees, and no exchange submission.

    This is not a backtest report and not an out-of-sample result. With
    `--select-on-is` the configuration is chosen on history that ends *before* the
    session window (plus an embargo gap), which is the only honest way to give a robot
    parameters it would actually have had at the start of the session. Without it the
    request runs exactly as configured, and a robot whose defaults never trade will
    honestly report `fills=0`.
    """
    require_simulated_mode(TradingMode.PAPER)
    robot = RobotName(args.robot)
    require_paper_support(robot)
    live = args.source == "live"
    if live:
        if robot is RobotName.PAIRS:
            raise ValueError(
                "live paper does not support the two-leg pairs robot yet; "
                "run it with --source catalog"
            )
        if robot is RobotName.ML_OBI:
            raise ValueError(
                "live paper does not support ml_obi: it needs a live L2 depth stream, "
                "and the session would otherwise run without the books it trades on"
            )
    source = BarOrigin.SYNTHETIC if args.source == "synthetic" else BarOrigin.CATALOG
    request = paper_request(cfg, bar_count=args.bars, robot=robot, source=source)

    if args.select_on_is:
        embargo = cfg.embargo_bars if args.embargo_bars is None else args.embargo_bars
        selection = param_selection_use_case(cfg).execute(
            request,
            holdout_bars=args.bars,
            embargo_bars=embargo,
        )
        print(selection.notes)
        print(selection.summary_line())
        request = apply_selected(request, selection.params)

    if live:
        print(
            f"live paper: waiting for {args.live_bars} closed "
            f"{cfg.bar_interval} bars from the public Binance stream (no keys, no orders)"
        )
        use_case = live_paper_use_case(
            cfg,
            live_bars=args.live_bars,
            timeout_seconds=args.live_timeout,
        )
    else:
        use_case = paper_use_case(cfg)

    report = use_case.execute(request)
    _print_paper_session(report)
    if args.journal:
        path = append_session(report, created_at=datetime.now(UTC).isoformat())
        print(f"paper_session_appended={path}")
    return 0


def _print_paper_session(report: PaperSessionReport) -> None:
    def percent(value: Decimal | None) -> str:
        return "n/a" if value is None else f"{value * 100:.2f}%"

    window = (
        "n/a"
        if report.window_start is None or report.window_end is None
        else f"[{report.window_start.isoformat()}, {report.window_end.isoformat()}]"
    )
    print(
        f"paper session (no exchange submission) robot={report.robot.value} "
        f"instrument={report.instrument_id} mode={report.mode.value} source={report.source}"
    )
    print(
        f"bars={report.bar_count} window={window} starting={report.starting_equity} "
        f"ending_balance={report.ending_equity} "
        # `ending_balance` is the account after realized fills only; a session that ends
        # holding a position is not flat, so the marked number is printed beside it.
        f"net_pnl_marked={report.net_pnl} return_marked={percent(report.return_fraction)}"
    )
    print(
        f"fills={len(report.fills)} positions={len(report.positions)} "
        f"fees={report.fees_paid} traded_notional={report.traded_notional} "
        f"max_dd={'n/a' if report.metrics is None else report.metrics.max_drawdown}"
    )
    if report.open_position is not None:
        print(
            f"open_position side={report.open_position.side} qty={report.open_position.qty} "
            f"entry={report.open_position.entry_price} mark={report.mark_price} "
            f"unrealized={report.unrealized_pnl}"
        )
    else:
        print("open_position=none (flat at the last bar)")
    for reason, count in report.risk_breaches:
        print(f"risk_breach blocked={count} {reason}")
    for fill in report.fills[:10]:
        print(
            f"  {fill.ts_utc.isoformat()} {fill.instrument_id} {fill.side} "
            f"qty={fill.qty} px={fill.price} fee={fill.commission} {fill.liquidity}"
        )
    if len(report.fills) > 10:
        print(f"  ... {len(report.fills) - 10} more fills")


def _run_scan(args: argparse.Namespace) -> int:
    if args.triangular:
        rates = {
            ("USDT", "BTC"): Decimal("0.000015"),
            ("BTC", "ETH"): Decimal("15"),
            ("ETH", "USDT"): Decimal("3500"),
        }
        opportunities = scan_triangular_opportunities(rates)
        print(f"triangular_opportunities={len(opportunities)}")
        for item in opportunities:
            print(f"cycle={item.cycle} profit_log={item.profit_log}")
        return 0
    print("Specify --triangular", file=sys.stderr)
    return 1


def _run_propose(cfg: Settings, args: argparse.Namespace) -> int:
    """Ask a model for hypotheses. Offline research: no orders, no market data."""
    job = ProposeJobConfig(
        count=args.count,
        dry_run=bool(args.dry_run),
        prompt=args.prompt,
        as_of=args.as_of,
        model=args.model,
        base_url=args.base_url,
        output_dir=args.output_dir,
        slug=args.slug,
        journal=bool(getattr(args, "journal", False)),
    )
    try:
        result = execute_propose(job, cfg)
    except (ValueError, InvalidHypothesisError, LlmRequestError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if result["status"] == "dry_run":
        print(result["prompt"])
        print(f"[dry-run] rendered {args.prompt}; no network call, {result['model']} unused.")
        return 0

    print(result["summary"])
    print(f"artifact={result['artifact_path']}")
    return 0


def _announce_manifest(cfg: Settings, *, synthetic: bool) -> RunManifest:
    """Print where this run comes from before it starts (docs/27 E-1.4).

    Printed first so a log that ends in a crash still says which code and data it ran.
    Warnings go to stderr: a dirty tree does not stop research, it only means the
    revision in the journal will not rebuild this run on its own.
    """
    manifest = run_manifest(cfg, with_catalog=not synthetic)
    print(manifest.summary_line())
    for warning in manifest.warnings():
        print(f"manifest_warning={warning}", file=sys.stderr)
    return manifest


def _journal_enabled(cfg: Settings, args: argparse.Namespace) -> bool:
    """`--journal` forces the write; JOURNAL_ENABLED makes it the default for every run."""
    return bool(getattr(args, "journal", False)) or cfg.journal_enabled


def _journal_entry(
    *,
    subject: str,
    gates: str,
    source: str = "lab research",
    oos_return: Decimal | None = None,
    buy_and_hold: Decimal | None = None,
    fills: int | None = None,
    reason: str = "",
    artifact: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        created_at=datetime.now(UTC),
        source=source,
        subject=subject,
        gates=gates,
        oos_return=oos_return,
        buy_and_hold_return=buy_and_hold,
        fills=fills,
        reason=reason,
        artifact=artifact,
    )


def _record_journal(cfg: Settings, manifest: RunManifest, entry: JournalEntry) -> None:
    markdown_path, jsonl_path = journal_paths(cfg)
    stamped = replace(entry, provenance=manifest)
    record_run(markdown_path=markdown_path, jsonl_path=jsonl_path, entry=stamped)
    print(f"journal_row_appended={markdown_path}")


def _int_list(raw: str) -> tuple[int, ...]:
    values = tuple(int(item) for item in raw.split(",") if item.strip())
    if not values:
        raise ValueError(f"expected a comma-separated list of integers, got {raw!r}")
    return values


def _run_xsmom(cfg: Settings, args: argparse.Namespace) -> int:
    """Walk-forward (and optionally PBO/DSR) for the basket rotation; prints the gate."""
    from nautilus_lab.application.run_xsmom import (
        XsMomGrid,
        XsMomRequest,
        run_xsmom_audit,
        run_xsmom_walk_forward,
    )
    from nautilus_lab.domain.metrics import PERIODS_PER_YEAR, SelectionMetric
    from nautilus_lab.domain.xsmom import Weighting
    from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_to_instrument_id
    from nautilus_lab.infrastructure.timeframe import nautilus_bar_type
    from nautilus_lab.interfaces.composition import research_feed, trial_ledger

    require_simulated_mode(cfg.trading_mode)
    interval = args.interval or cfg.bar_interval
    if interval != cfg.bar_interval:
        cfg = cfg.model_copy(update={"bar_interval": interval})
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if len(symbols) < 2:
        raise ValueError("cross-sectional momentum needs at least two symbols")
    _announce_manifest(cfg, synthetic=False)
    instrument_ids = tuple(binance_symbol_to_instrument_id(symbol) for symbol in symbols)
    base = research_request(
        cfg,
        bar_count=0,
        source=BarOrigin.CATALOG,
        start=parse_utc(args.start) if args.start else None,
        end=parse_utc(args.end) if args.end else None,
    )
    feed_request = replace(
        base,
        instrument_id=instrument_ids[0],
        instrument_ids=instrument_ids,
        bar_type=nautilus_bar_type(instrument_ids[0], interval),
    )
    bars = research_feed(cfg).load_multi(feed_request)
    empty = [key for key, series in bars.items() if not series]
    if empty:
        raise CatalogEmptyError(
            f"no {interval} bars for {', '.join(empty)} in the catalog; ingest them first: "
            f"uv run lab ingest --symbols {','.join(symbols)}"
        )
    request = XsMomRequest(
        starting_equity=cfg.starting_equity,
        fees=cfg.fee_schedule(),
        slippage=Decimal(args.slippage_bps) / Decimal("10000"),
        grid=XsMomGrid(
            lookback_bars=_int_list(args.lookbacks),
            top_n=_int_list(args.top_n),
            rebalance_every=_int_list(args.rebalance),
            require_positive=not args.no_positive_filter,
            weighting=Weighting.INVERSE_VOL if args.inverse_vol else Weighting.EQUAL,
        ),
        folds=args.folds,
        in_sample_fraction=Decimal(args.is_fraction),
        embargo_bars=cfg.embargo_bars,
        selection_metric=SelectionMetric(args.metric),
        periods_per_year=PERIODS_PER_YEAR.get(interval),
        pbo_blocks=args.pbo_blocks,
    )
    first = next(iter(bars.values()))
    print(
        f"xsmom basket={','.join(symbols)} interval={interval} bars={len(first)} "
        f"window=[{first[0].ts_utc.isoformat()}, {first[-1].ts_utc.isoformat()}] "
        f"grid={len(request.grid.candidates())} metric={request.selection_metric.value} "
        "(portfolio simulator: decide on close, fill next open, taker fee + slippage)"
    )
    report = run_xsmom_walk_forward(bars, request)
    for fold in report.folds:
        window = fold.window
        oos = fold.out_of_sample
        print(
            f"fold {fold.index} OOS=[{window.out_of_sample_start.isoformat()}, "
            f"{window.out_of_sample_end.isoformat()}) trades={oos.trades} "
            f"return={_pct(fold.oos_return)} basket={_pct(fold.buy_and_hold_return)} "
            f"max_dd={_pct(oos.metrics.max_drawdown)} fees={oos.fees_paid:.2f} "
            f"selected={fold.selected.label()}"
        )
    print(report.summary_line())
    audit = (
        run_xsmom_audit(
            bars,
            request,
            trial_ledger=trial_ledger(cfg),
            dataset=",".join(sorted(nautilus_bar_type(item, interval) for item in instrument_ids)),
        )
        if args.pbo
        else None
    )
    if audit is not None:
        print(audit.summary_line())
        print(audit.deflated_sharpe.summary_line())
    print(evaluate_gate(report, audit).summary_line())
    return 0


def parse_date(value: str) -> date:
    """YYYY-MM-DD for argparse; a bad value becomes a usage error, not a traceback."""
    return date.fromisoformat(value)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_window(args: argparse.Namespace) -> WalkForwardWindow | None:
    dates = (args.is_start, args.is_end, args.oos_start, args.oos_end)
    if not any(dates):
        return None
    if not all(dates):
        raise ValueError("walk-forward dates require --is-start --is-end --oos-start --oos-end")
    return WalkForwardWindow(
        in_sample_start=parse_utc(args.is_start),
        in_sample_end=parse_utc(args.is_end),
        out_of_sample_start=parse_utc(args.oos_start),
        out_of_sample_end=parse_utc(args.oos_end),
    )


def _print_multi_window(
    report: MultiWindowReport, registration: PreregistrationVerdict | None = None
) -> None:
    print(report.notes)
    # Full ISO timestamps, not dates: on intraday bars an out-of-sample block can be
    # hours long, and a date-only label would print the same day for every fold.
    for fold in report.folds:
        window = fold.window
        print(
            f"fold {fold.index} "
            f"OOS=[{window.out_of_sample_start.isoformat()}, "
            f"{window.out_of_sample_end.isoformat()}) "
            f"fills={fold.out_of_sample.fills} "
            f"return={_pct(fold.oos_return)} buy_hold={_pct(fold.buy_and_hold_return)} "
            f"selected={fold.selected.label()}"
        )
    print(
        f"out-of-sample aggregate profitable={report.profitable_folds}/{len(report.folds)} "
        f"mean={_pct(report.mean_oos_return)} median={_pct(report.median_oos_return)} "
        f"worst={_pct(report.worst_oos_return)} best={_pct(report.best_oos_return)}"
    )
    print(
        f"baseline buy&hold mean={_pct(report.mean_buy_and_hold_return)} "
        f"oos_fills={report.total_oos_fills}"
    )
    print(
        f"breakeven_cost mean_bps={_bps(report.mean_breakeven_cost)} "
        f"folds_measured={len(report.breakeven_costs)}/{len(report.folds)}"
    )
    breaches = _multi_window_breach_line(report)
    if breaches is not None:
        print(breaches)
    print(report.summary_line())
    if registration is not None:
        print(registration.summary_line())
    # Half the evidence: PBO/DSR come from `--pbo`, so this is INCOMPLETE at best.
    print(evaluate_gate(report, None, preregistration=registration).summary_line())


def _breach_suffix(line: str | None) -> str:
    """Append breach detail to a notification, or nothing when no breaker fired."""
    return "" if line is None else f" | {line}"


def _multi_window_breach_line(report: MultiWindowReport) -> str | None:
    """Circuit-breaker refusals summed across folds, per reason.

    Aggregated rather than per-fold: the question this answers is "is this robot
    being held back by a breaker across the whole walk-forward", which a per-fold
    breakdown would bury. Per-fold detail is still in each fold's report.
    """
    totals: dict[str, int] = {}
    for fold in report.folds:
        for reason, count in fold.out_of_sample.risk_breaches:
            totals[reason] = totals.get(reason, 0) + count
    if not totals:
        return None
    detail = ", ".join(f"{reason}={count}" for reason, count in totals.items())
    return f"risk_breaches blocked={sum(totals.values())} {detail}"


def _pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _bps(value: Decimal | None) -> str:
    """Cost rate as basis points (1 bps = 0.01%), same units as maker/taker fees."""
    return "n/a" if value is None else f"{value * 10000:.2f}"


def _breakeven_line(label: str, report: BacktestReport) -> str | None:
    """One line: what was traded, what it cost, and how much cost the run could take."""
    metrics = report.metrics
    if metrics is None or (metrics.traded_notional <= 0 and metrics.breakeven_cost is None):
        return None
    return (
        f"{label} traded_notional={metrics.traded_notional} "
        f"paid_cost_bps={_bps(metrics.paid_cost_rate)} "
        f"breakeven_cost_bps={_bps(metrics.breakeven_cost)}"
    )


def _breach_line(label: str, report: BacktestReport) -> str | None:
    """Which circuit breakers refused entries, and how often.

    Printed only when something actually tripped: an all-clear line on every run
    would be noise, and the absence of the line means "no entry was blocked",
    which the report's empty tuple already states.
    """
    if not report.risk_breaches:
        return None
    detail = ", ".join(f"{reason}={count}" for reason, count in report.risk_breaches)
    return f"{label} risk_breaches blocked={sum(c for _, c in report.risk_breaches)} {detail}"


def _print_backtest(report: BacktestReport) -> None:
    print(f"fills={report.fills} positions={report.positions} ending={report.ending_balance}")
    if report.metrics is not None:
        print(
            f"fees_paid={report.metrics.fees_paid} max_dd={report.metrics.max_drawdown} "
            f"turnover={report.metrics.turnover} sharpe_like={report.metrics.sharpe_like}"
        )
        breakeven = _breakeven_line("cost", report)
        if breakeven is not None:
            print(breakeven)
    breaches = _breach_line("cost", report)
    if breaches is not None:
        print(breaches)
    if report.tearsheet_path:
        print(f"tearsheet_saved={report.tearsheet_path}")
    print(report.notes)


def _print_walk_forward(report: WalkForwardReport) -> None:
    print(report.notes)
    print(
        "in-sample (selection only) "
        f"fills={report.in_sample.fills} ending={report.in_sample.ending_balance}"
    )
    print(
        "out-of-sample (report this) "
        f"fills={report.out_of_sample.fills} ending={report.out_of_sample.ending_balance}"
    )
    breakeven = _breakeven_line("out-of-sample", report.out_of_sample)
    if breakeven is not None:
        print(breakeven)
    breaches = _breach_line("out-of-sample", report.out_of_sample)
    if breaches is not None:
        print(breaches)
    if report.out_of_sample.tearsheet_path:
        print(f"tearsheet_saved={report.out_of_sample.tearsheet_path}")


if __name__ == "__main__":
    raise SystemExit(main())


def _run_ml_train(cfg: Settings, args: argparse.Namespace) -> int:
    from nautilus_lab.api.ml_runner import MLTrainConfig, execute_ml_train

    if args.ml_command != "train":
        print(f"Unknown ml command: {args.ml_command}", file=sys.stderr)
        return 1

    job = MLTrainConfig(
        model_type=args.model_type,
        catalog_path=args.catalog,
        instrument_id=args.instrument,
        bar_interval=args.interval,
        output_path=args.output,
        folds=args.folds,
        embargo=args.embargo,
        horizon=args.horizon,
        profit_multiple=args.profit,
        stop_multiple=args.stop,
        vol_window=args.vol_window,
        start=args.start,
        end=args.end,
        threshold=args.threshold,
    )
    result, _ = execute_ml_train(job)
    if result.get("is_error", False):
        print(f"ML train error: {result.get('error_message')}", file=sys.stderr)
        return 1
    return 0
