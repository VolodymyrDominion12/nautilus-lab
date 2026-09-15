#!/usr/bin/env python3
"""Offline IC score for a DSL recipe on catalog bars. Never trades."""

from __future__ import annotations

import argparse
from pathlib import Path

from nautilus_lab.application.evaluate_recipe import score_recipe
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a factor DSL recipe (research only)")
    parser.add_argument("formula", help="DSL formula, e.g. 'trend_er * momentum_10'")
    parser.add_argument("--catalog", default="catalog", help="Parquet catalog path")
    parser.add_argument("--instrument", default="ETH/USDT.SIM", help="Instrument id")
    parser.add_argument("--interval", default="1h", help="Bar interval")
    parser.add_argument("--horizon", type=int, default=5, help="Forward return horizon in bars")
    parser.add_argument(
        "--sign",
        type=int,
        choices=(-1, 1),
        default=1,
        help="Expected sign of the recipe vs future return",
    )
    args = parser.parse_args()

    store = NautilusParquetCatalog(Path(args.catalog), fees=FeeSchedule.binance_spot_vip0())
    bar_type = nautilus_bar_type(args.instrument, args.interval)
    bars = store.load(bar_type=bar_type)
    score = score_recipe(
        bars,
        args.formula,
        horizon_bars=args.horizon,
        expected_sign=args.sign,
    )
    ic = "n/a" if score.information_coefficient is None else f"{score.information_coefficient:.4f}"
    cf = "n/a" if score.counterfactual_ic is None else f"{score.counterfactual_ic:.4f}"
    hit = "n/a" if score.hit_rate is None else f"{score.hit_rate:.2%}"
    print(
        f"formula={score.formula!r} complexity={score.complexity} depth={score.depth} "
        f"n={score.observations} ic={ic} hit_rate={hit} counterfactual_ic={cf}"
    )
    if score.crowding_index:
        print(f"crowding_hits={score.crowding_index}")


if __name__ == "__main__":
    main()
