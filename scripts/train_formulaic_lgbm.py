#!/usr/bin/env python3
"""Offline training for formulaic LightGBM direction model (no live trading)."""

from __future__ import annotations

import argparse
from pathlib import Path

from nautilus_lab.application.train_classifier import (
    describe_train_window,
    parse_optional_utc,
    require_exclusive_window,
)
from nautilus_lab.application.train_formulaic import (
    build_formulaic_dataset,
    train_formulaic_lightgbm,
)
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type


def main() -> None:
    parser = argparse.ArgumentParser(description="Train formulaic LightGBM on catalog bars")
    parser.add_argument("--catalog", default="catalog", help="Parquet catalog path")
    parser.add_argument("--instrument", default="ETH/USDT.SIM", help="Instrument id")
    parser.add_argument("--interval", default="1h", help="Bar interval")
    parser.add_argument("--output", default="models/formulaic_lgbm.txt", help="Model output path")
    parser.add_argument("--horizon", type=int, default=5, help="Label horizon in bars")
    parser.add_argument("--folds", type=int, default=5, help="Purged k-fold splits")
    parser.add_argument(
        "--embargo",
        type=int,
        default=10,
        help="Embargo in bars (label time), not in row count",
    )
    parser.add_argument("--start", default=None, help="Inclusive UTC start (YYYY-MM-DD)")
    parser.add_argument(
        "--end",
        default=None,
        help="Exclusive UTC end (YYYY-MM-DD). Omit only for an in-sample-only artifact",
    )
    args = parser.parse_args()

    start = parse_optional_utc(args.start)
    end = parse_optional_utc(args.end)
    require_exclusive_window(start, end)
    window = describe_train_window(start=start, end=end)

    store = NautilusParquetCatalog(Path(args.catalog), fees=FeeSchedule.binance_spot_vip0())
    bar_type = nautilus_bar_type(args.instrument, args.interval)
    bars = store.load(bar_type=bar_type, start=start, end=end)
    dataset = build_formulaic_dataset(bars, horizon=args.horizon)
    report = train_formulaic_lightgbm(
        dataset,
        Path(args.output),
        n_splits=args.folds,
        embargo=args.embargo,
        train_window=window,
    )
    accuracy = "n/a" if report.accuracy is None else f"{report.accuracy * 100:.2f}%"
    majority = "n/a" if report.majority_rate is None else f"{report.majority_rate * 100:.2f}%"
    beats = "n/a" if report.beats_majority is None else str(report.beats_majority).lower()
    print(
        f"saved={report.model_path} rows={report.rows} folds={report.folds} "
        f"purged_cv_accuracy={accuracy} majority_rate={majority} beats_majority={beats} "
        f"train_window={report.train_window}"
    )


if __name__ == "__main__":
    main()
