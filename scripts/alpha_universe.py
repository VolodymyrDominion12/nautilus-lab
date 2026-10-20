"""Build the point-in-time perp universe (monthly top-N by 30-day dollar volume).

Needs daily perp bars for *every* USDT perp, delisted ones included:

  .venv/bin/lab ingest-archive --market um --dataset klines --interval 1d --symbols all \
      --start 2020-01-01

then:

  .venv/bin/python scripts/alpha_universe.py --top 30
  # -> research/alpha/universe_perp_top30.json, and the 1h ingest commands for its coins

The file is the universe the screen and validation use (`--universe`). Commit it: a
validation run checks the file's sha256 against the one its preregistration recorded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nautilus_lab.application.alpha.universe import pit_universe, save_universe
from nautilus_lab.domain.data_zone import DEFAULT_ZONE_POLICY
from nautilus_lab.domain.universe import candidate_symbols
from nautilus_lab.infrastructure.alpha_panel_store import build_panel

_SUFFIX = "-PERP.SIM-1-DAY-LAST-EXTERNAL"


def catalog_perp_symbols(catalog: Path) -> list[str]:
    """Symbols from the bar directory names, no Parquet read."""
    bar_dir = catalog / "data" / "bar"
    names = [p.name[: -len(_SUFFIX)] for p in bar_dir.glob(f"*{_SUFFIX}") if p.is_dir()]
    return candidate_symbols(names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--daily-catalog", default="catalog_perp_1d")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--min-days", type=int, default=20)
    parser.add_argument("--start", default="2020-01-01", help="for the printed ingest commands")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    catalog = Path(args.daily_catalog)
    symbols = catalog_perp_symbols(catalog)
    if len(symbols) <= args.top:
        print(
            f"only {len(symbols)} perp series in {catalog}: a top-{args.top} universe drawn from "
            "them is the survivor list again. Ingest every perp first:\n"
            "  .venv/bin/lab ingest-archive --market um --dataset klines --interval 1d "
            "--symbols all --start 2020-01-01",
            file=sys.stderr,
        )
        return 2
    print(f"{len(symbols)} perp series in {catalog}; loading daily bars...", flush=True)
    daily = build_panel(
        bar_catalog=catalog, symbols=symbols, interval="1d", perp=True, skip_missing=True
    )
    universe = pit_universe(
        daily, top_n=args.top, lookback_days=args.lookback_days, min_days=args.min_days
    )
    out = Path(args.out or f"research/alpha/universe_perp_top{args.top}.json")
    save_universe(universe, out)

    ever = universe.ever()
    held = DEFAULT_ZONE_POLICY.holdout_symbols(ever)
    sizes = [len(m) for _, m in universe.months]
    print(
        f"wrote {out}: {len(universe.months)} months "
        f"({universe.months[0][0]}..{universe.months[-1][0]}), members/month "
        f"{min(sizes)}..{max(sizes)}, {len(ever)} coins ever a member"
    )
    print(f"holdout coins (never screened): {len(held)}: {', '.join(held)}")
    joined = ",".join(ever)
    print("\nnext: 1h history for these coins (bars + taker flow, premium, funding):")
    for dataset in ("klines", "premium"):
        print(
            f"  .venv/bin/lab ingest-archive --market um --dataset {dataset} --interval 1h "
            f"--symbols {joined} --start {args.start}"
        )
    print(
        f"  .venv/bin/lab ingest-archive --dataset funding --symbols {joined} --start {args.start}"
    )
    print(
        "then:\n  .venv/bin/python scripts/alpha_screen.py --universe "
        f"{out} --funding-catalog catalog_perp_1h --rebuild"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
