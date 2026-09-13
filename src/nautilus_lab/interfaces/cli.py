from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_lab.application.dtos import BacktestReport, WalkForwardReport
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_paper import RunPaperResearch
from nautilus_lab.application.scan_triangular import scan_triangular_opportunities
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.errors import (
    CatalogEmptyError,
    InvalidWindowError,
    LiveTradingDisabledError,
    PaperTradingNotReadyError,
)
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import (
    ingest_request,
    ingest_use_case,
    research_request,
    research_use_case,
    settings,
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

    paper = sub.add_parser("paper", help="Paper trading: log hypothetical orders only")
    paper.add_argument("--bars", type=int, default=500, help="Synthetic bar count")
    paper.add_argument(
        "--robot",
        choices=("regime", "ema"),
        default="regime",
    )

    scan = sub.add_parser("scan", help="Research scanners (no orders)")
    scan.add_argument(
        "--triangular",
        action="store_true",
        help="Scan for triangular arbitrage cycles in sample rates",
    )

    sub.add_parser("live", help="Live trading (always fail closed)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = settings()
    catalog_path = getattr(args, "catalog", None)
    if catalog_path:
        cfg = cfg.model_copy(update={"catalog_path": catalog_path})
    if getattr(args, "bar_vpin", False):
        cfg = cfg.model_copy(update={"use_bar_vpin": True})
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
        if args.command == "live":
            require_simulated_mode(TradingMode.LIVE)
    except (
        LiveTradingDisabledError,
        PaperTradingNotReadyError,
        CatalogEmptyError,
        InvalidWindowError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


def _run_ingest(cfg: Settings, args: argparse.Namespace) -> int:
    start = parse_utc(args.start) if args.start else datetime.now(UTC) - timedelta(days=365)
    end = parse_utc(args.end) if args.end else datetime.now(UTC)
    symbols = (
        [item.strip() for item in args.symbols.split(",") if item.strip()]
        if args.symbols
        else cfg.binance_symbols
    )
    use_case = ingest_use_case(cfg)
    for symbol in symbols:
        report = use_case.execute(ingest_request(cfg, start=start, end=end, symbol=symbol))
        print(
            f"symbol={symbol} wrote={report.bars_written} "
            f"first={report.first_ts.isoformat()} last={report.last_ts.isoformat()} "
            f"catalog={report.catalog_path}"
        )
    return 0


def _run_research(cfg: Settings, args: argparse.Namespace) -> int:
    robot = RobotName(args.robot) if args.robot is not None else None
    if args.synthetic:
        report = research_use_case(cfg).execute(
            research_request(
                cfg,
                bar_count=args.bars,
                robot=robot,
                source=BarOrigin.SYNTHETIC,
                stress_slice=args.slice,
            )
        )
        _print_backtest(report)
        return 0
    walk_forward = True if args.walk_forward else not args.full_sample
    if args.full_sample:
        walk_forward = False
    if walk_forward:
        window = _optional_window(args)
        wf = walk_forward_use_case(cfg).execute(
            walk_forward_request(
                cfg,
                robot=robot,
                window=window,
                in_sample_fraction=args.is_fraction,
                stress_slice=args.slice,
            )
        )
        _print_walk_forward(wf)
        return 0
    report = research_use_case(cfg).execute(
        research_request(
            cfg,
            bar_count=args.bars,
            robot=robot,
            source=BarOrigin.CATALOG,
            stress_slice=args.slice,
        )
    )
    print("full-sample catalog run (in-sample only; not an out-of-sample report)")
    _print_backtest(report)
    return 0


def _run_paper(cfg: Settings, args: argparse.Namespace) -> int:
    require_simulated_mode(TradingMode.PAPER)
    request = research_request(
        cfg,
        bar_count=args.bars,
        robot=RobotName(args.robot),
        source=BarOrigin.SYNTHETIC,
    )
    bars = research_use_case(cfg)._feed.load(request)
    logger = RunPaperResearch().execute(request, bars)
    print(f"paper_orders={len(logger.orders)} (no exchange submission)")
    for order in logger.orders[:10]:
        print(
            f"{order.ts_utc.isoformat()} {order.instrument_id} "
            f"{order.side} qty={order.qty} reason={order.description}"
        )
    return 0


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


def _print_backtest(report: BacktestReport) -> None:
    print(f"fills={report.fills} positions={report.positions} ending={report.ending_balance}")
    if report.metrics is not None:
        print(
            f"fees_paid={report.metrics.fees_paid} max_dd={report.metrics.max_drawdown} "
            f"turnover={report.metrics.turnover} sharpe_like={report.metrics.sharpe_like}"
        )
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


if __name__ == "__main__":
    raise SystemExit(main())
