#!/usr/bin/env python3
"""Offline training for formulaic LightGBM direction model (no live trading)."""

from __future__ import annotations

import argparse
from pathlib import Path

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
    parser.add_argument("--embargo", type=int, default=10, help="Embargo bars between folds")
    args = parser.parse_args()

    store = NautilusParquetCatalog(Path(args.catalog), fees=FeeSchedule.binance_spot_vip0())
    bar_type = nautilus_bar_type(args.instrument, args.interval)
    bars = store.load(bar_type=bar_type)
    dataset = build_formulaic_dataset(bars, horizon=args.horizon)
    report = train_formulaic_lightgbm(
        dataset,
        Path(args.output),
        n_splits=args.folds,
        embargo=args.embargo,
    )
    accuracy = "n/a" if report.accuracy is None else f"{report.accuracy * 100:.2f}%"
    print(
        f"saved={report.model_path} rows={report.rows} folds={report.folds} "
        f"purged_cv_accuracy={accuracy}"
    )


if __name__ == "__main__":
    main()
