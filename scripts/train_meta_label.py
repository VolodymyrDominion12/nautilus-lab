#!/usr/bin/env python3
"""Offline training for meta-label LightGBM (primary = regime, labels = Triple Barrier)."""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.train_classifier import (
    describe_train_window,
    parse_optional_utc,
    require_exclusive_window,
)
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
        help="Embargo in bars (label time), not in event count",
    )
    parser.add_argument("--profit-multiple", default="2", help="Take-profit in units of vol")
    parser.add_argument("--stop-multiple", default="1", help="Stop-loss in units of vol")
    parser.add_argument("--horizon", type=int, default=10, help="Vertical barrier in bars")
    parser.add_argument("--vol-window", type=int, default=20, help="Volatility window")
    parser.add_argument(
        "--threshold",
        default="0.55",
        help="Operating threshold for OOF precision (same as META_LABEL_THRESHOLD)",
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
        threshold=Decimal(args.threshold),
        train_window=window,
    )
    accuracy = "n/a" if report.accuracy is None else f"{report.accuracy * 100:.2f}%"
    tp_rate = "n/a" if report.take_profit_rate is None else f"{report.take_profit_rate * 100:.2f}%"
    precision = "n/a" if report.oof_precision is None else f"{report.oof_precision * 100:.2f}%"
    recall = "n/a" if report.oof_recall is None else f"{report.oof_recall * 100:.2f}%"
    beats = "n/a" if report.beats_always_take is None else str(report.beats_always_take).lower()
    print(
        f"saved={report.model_path} rows={report.rows} folds={report.folds} "
        f"purged_cv_accuracy={accuracy} take_profit_rate={tp_rate} "
        f"oof_precision={precision} oof_recall={recall} beats_always_take={beats} "
        f"train_window={report.train_window}"
    )


if __name__ == "__main__":
    main()
