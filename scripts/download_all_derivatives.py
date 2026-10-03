#!/usr/bin/env python
"""Batch downloader for Binance USD-M derivatives data.

Downloads:
1. Perpetual futures klines (1d and 4h) into catalog_perp_1d and catalog_perp_4h
2. Funding rates and joined index prices into catalog/data/funding/
3. Premium index klines (1d and 4h) into catalog/data/premium_index/

Usage:
    .venv/bin/python scripts/download_all_derivatives.py
    .venv/bin/python scripts/download_all_derivatives.py --start 2020-01-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.cli import (
    _run_ingest,
    _run_ingest_funding,
    _run_ingest_premium_index,
    parse_utc,
)

DEFAULT_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "DOTUSDT",
    "MATICUSDT",
    "LINKUSDT",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start", default="2020-01-01", help="UTC start date (default: 2020-01-01)"
    )
    parser.add_argument("--end", default=None, help="UTC end date exclusive (default: now)")
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="Comma-separated symbols (default: all 11 supported symbols)",
    )
    parser.add_argument("--skip-klines", action="store_true", help="Skip 1d/4h perp klines")
    parser.add_argument("--skip-funding", action="store_true", help="Skip funding rates")
    parser.add_argument("--skip-premium", action="store_true", help="Skip premium index klines")
    args = parser.parse_args(argv)

    start = parse_utc(args.start)
    end = parse_utc(args.end) if args.end else datetime.now(UTC)
    raw_symbols = [
        s.strip().removesuffix("-PERP").upper() for s in args.symbols.split(",") if s.strip()
    ]
    perp_symbols = [f"{s}-PERP" for s in raw_symbols]

    print(f"=== Starting derivatives ingestion for {len(raw_symbols)} symbols ===")
    print(f"Window: [{start.isoformat()} -> {end.isoformat()})")
    print(f"Symbols: {', '.join(raw_symbols)}\n")

    cfg = Settings()

    # 1. Funding rates
    if not args.skip_funding:
        print(">>> [1/5] Ingesting funding rates...")
        _run_ingest_funding(cfg, symbols=raw_symbols, start=start, end=end)
        print(">>> Funding rates completed.\n")

    # 2. Perp Klines 1d
    if not args.skip_klines:
        print(">>> [2/5] Ingesting 1d perpetual klines (catalog_perp_1d)...")
        cfg_1d = cfg.model_copy(update={"catalog_path": "catalog_perp_1d", "bar_interval": "1d"})
        args_1d = argparse.Namespace(
            start=args.start,
            end=args.end,
            symbols=",".join(perp_symbols),
            incremental=False,
            funding=False,
            trades=False,
            depth=False,
            interval="1d",
            premium_index=False,
        )
        _run_ingest(cfg_1d, args_1d)
        print(">>> 1d perpetual klines completed.\n")

    # 3. Perp Klines 4h
    if not args.skip_klines:
        print(">>> [3/5] Ingesting 4h perpetual klines (catalog_perp_4h)...")
        cfg_4h = cfg.model_copy(update={"catalog_path": "catalog_perp_4h", "bar_interval": "4h"})
        args_4h = argparse.Namespace(
            start=args.start,
            end=args.end,
            symbols=",".join(perp_symbols),
            incremental=False,
            funding=False,
            trades=False,
            depth=False,
            interval="4h",
            premium_index=False,
        )
        _run_ingest(cfg_4h, args_4h)
        print(">>> 4h perpetual klines completed.\n")

    # 4. Premium Index 1d
    if not args.skip_premium:
        print(">>> [4/5] Ingesting 1d premium index klines (catalog_perp_1d)...")
        cfg_prem_1d = cfg.model_copy(update={"catalog_path": "catalog_perp_1d"})
        _run_ingest_premium_index(
            cfg_prem_1d, symbols=raw_symbols, interval="1d", start=start, end=end
        )
        print(">>> 1d premium index klines completed.\n")

    # 5. Premium Index 4h
    if not args.skip_premium:
        print(">>> [5/5] Ingesting 4h premium index klines (catalog_perp_4h)...")
        cfg_prem_4h = cfg.model_copy(update={"catalog_path": "catalog_perp_4h"})
        _run_ingest_premium_index(
            cfg_prem_4h, symbols=raw_symbols, interval="4h", start=start, end=end
        )
        print(">>> 4h premium index klines completed.\n")

    print("=== All derivatives data successfully ingested! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
