#!/usr/bin/env python3
"""Offline training for meta-label LightGBM (primary = regime, labels = Triple Barrier)."""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.train_meta_label import (
    build_meta_label_dataset,
    train_meta_label_lightgbm,
)
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.triple_barrier import TripleBarrierConfig
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a meta-label LightGBM on catalog bars (regime primary, TBM labels)"
    )
    parser.add_argument("--catalog", default="catalog", help="Parquet catalog path")
    parser.add_argument("--instrument", default="ETH/USDT.SIM", help="Instrument id")
    parser.add_argument("--interval", default="1h", help="Bar interval")
    parser.add_argument("--output", default="models/meta_label.txt", help="Model output path")
    parser.add_argument("--folds", type=int, default=5, help="Purged k-fold splits")
    parser.add_argument(
        "--embargo",
        type=int,
        default=10,
        help="Embargo bars between folds (keep >= horizon)",
    )
    parser.add_argument("--profit-multiple", default="2", help="Take-profit in units of vol")
    parser.add_argument("--stop-multiple", default="1", help="Stop-loss in units of vol")
    parser.add_argument("--horizon", type=int, default=10, help="Vertical barrier in bars")
    parser.add_argument("--vol-window", type=int, default=20, help="Volatility window")
    args = parser.parse_args()

    store = NautilusParquetCatalog(Path(args.catalog), fees=FeeSchedule.binance_spot_vip0())
    bar_type = nautilus_bar_type(args.instrument, args.interval)
    bars = store.load(bar_type=bar_type)
    barrier = TripleBarrierConfig(
        profit_multiple=Decimal(args.profit_multiple),
        stop_multiple=Decimal(args.stop_multiple),
        horizon=args.horizon,
    )
    dataset = build_meta_label_dataset(
        bars,
        instrument_id=args.instrument,
        barrier=barrier,
        volatility_window=args.vol_window,
    )
    report = train_meta_label_lightgbm(
        dataset,
        Path(args.output),
        n_splits=args.folds,
        embargo=args.embargo,
    )
    accuracy = "n/a" if report.accuracy is None else f"{report.accuracy * 100:.2f}%"
    tp_rate = "n/a" if report.take_profit_rate is None else f"{report.take_profit_rate * 100:.2f}%"
    print(
        f"saved={report.model_path} rows={report.rows} folds={report.folds} "
        f"purged_cv_accuracy={accuracy} take_profit_rate={tp_rate}"
    )


if __name__ == "__main__":
    main()
