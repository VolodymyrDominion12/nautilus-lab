#!/usr/bin/env python
"""Run the whole archive ingest of docs/34 P1 in one go.

Steps (each is one `lab ingest-archive` call; re-running is cheap because every
verified archive file is cached under data/raw/binance_vision):

1. spot klines 1d for every *USDT crypto symbol in the archive, from 2019;
2. USD-M perp klines 1d for every *USDT perp, from 2020;
3. funding for every perp, from 2020, into every catalog_perp_* directory;
4. premium index 1d for every perp, from 2020;
5. (with --with-4h) the same 4h series for spot and perps.

Usage:
    .venv/bin/python scripts/fetch_binance_vision.py
    .venv/bin/python scripts/fetch_binance_vision.py --symbols BTCUSDT,ETHUSDT --with-4h

Each step prints one line per symbol with rows, first/last bar and the QC verdict
(`quality=ok|warn|fail`); the per-series details land in <catalog>/quality.json.
The exit code is non-zero when any symbol failed, so a scheduled run can alert.
"""

from __future__ import annotations

import argparse
import sys

from nautilus_lab.interfaces.cli import main as lab


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="all", help="'all' or a comma-separated list")
    parser.add_argument("--spot-start", default="2019-01-01")
    parser.add_argument("--perp-start", default="2020-01-01")
    parser.add_argument("--with-4h", action="store_true", help="Also ingest 4h bars")
    parser.add_argument("--workers", default="8")
    parser.add_argument("--skip-spot", action="store_true")
    parser.add_argument("--skip-perp", action="store_true")
    args = parser.parse_args(argv)

    common = ["--symbols", args.symbols, "--workers", args.workers]
    intervals = ["1d", "4h"] if args.with_4h else ["1d"]

    def klines(market: str, interval: str, start: str) -> list[str]:
        return ["--market", market, "--dataset", "klines", "--interval", interval, "--start", start]

    steps: list[list[str]] = []
    if not args.skip_spot:
        steps.extend(klines("spot", interval, args.spot_start) for interval in intervals)
    if not args.skip_perp:
        steps.extend(klines("um", interval, args.perp_start) for interval in intervals)
        # Perp bar catalogs must exist before funding, which goes into each of them.
        steps.append(["--dataset", "funding", "--start", args.perp_start])
        steps.extend(
            ["--dataset", "premium", "--interval", interval, "--start", args.perp_start]
            for interval in intervals
        )

    worst = 0
    for number, step in enumerate(steps, start=1):
        print(f"\n=== [{number}/{len(steps)}] lab ingest-archive {' '.join(step)} ===", flush=True)
        code = lab(["ingest-archive", *step, *common])
        worst = max(worst, code)
    print(f"\n=== done, exit code {worst} ===")
    return worst


if __name__ == "__main__":
    sys.exit(main())
