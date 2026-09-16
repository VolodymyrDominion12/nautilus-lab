#!/usr/bin/env python3
"""Offline A/B: does Kronos-style candle geometry add signal to the formulaic features?

Question behind the experiment (source review and its §7.1: see
`docs/18-transformery-ssm-vidpovidnist.md`):
the Kronos tokenizer splits a candle into a coarse part (direction, magnitude) and a fine
part (wick structure), arguing that flattening OHLCV into independent channels destroys
market axiomatics. This lab keeps the axiomatics in `domain/bars.py::validate_bar`, but its
`FormulaicAlphaEngine` reads close/high/low/volume and never reads `open` — so the cheapest
testable form of that claim is: add candle geometry (body, wicks, gap) to the same 12
features and see whether purged-CV accuracy moves.

Method: identical to `application/train_formulaic.py` — 3-class direction label with a 5 bps
threshold at a 5-bar horizon, purged K-fold (5 splits, embargo 10), same LightGBM
hyperparameters. Reference points: (a) the 12-feature model, (b) the majority class.

This is a *feature-set* measurement, not a trading verdict: accuracy here says nothing about
OOS return vs buy&hold, which stays the only reportable number (see AGENTS.md).

Run: .venv/bin/python scripts/experiment_candle_geometry.py
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

import lightgbm as lgb
import numpy as np

from nautilus_lab.application.train_classifier import label_direction, purged_k_fold
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.formulaic_alphas import MIN_HISTORY, FormulaicAlphaEngine
from nautilus_lab.domain.ml_classifier import DIRECTION_CLASS_INDEX
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type

HORIZON = 5
THRESHOLD_BPS = Decimal("5")
N_SPLITS = 5
EMBARGO = 10
SEED = 7


def candle_geometry(bar: OhlcvBar, previous_close: Decimal | None) -> tuple[Decimal, ...]:
    """Body, wicks and opening gap of the just-closed bar. No look-ahead."""
    span = bar.high - bar.low
    body = bar.close - bar.open
    upper_wick = bar.high - max(bar.open, bar.close)
    lower_wick = min(bar.open, bar.close) - bar.low
    if span > 0:
        body_pct = body / span
        upper_pct = upper_wick / span
        lower_pct = lower_wick / span
    else:
        body_pct = upper_pct = lower_pct = Decimal("0")
    body_return = body / bar.open if bar.open > 0 else Decimal("0")
    gap = (
        (bar.open - previous_close) / previous_close
        if previous_close is not None and previous_close > 0
        else Decimal("0")
    )
    return (body_pct, upper_pct, lower_pct, body_return, gap)


def build_rows(
    bars: list[OhlcvBar],
) -> tuple[list[tuple[Decimal, ...]], list[tuple[Decimal, ...]], list[str]]:
    engine = FormulaicAlphaEngine(history=max(MIN_HISTORY, 30))
    base: list[tuple[Decimal, ...]] = []
    extended: list[tuple[Decimal, ...]] = []
    labels: list[str] = []
    previous_close: Decimal | None = None
    for index, bar in enumerate(bars):
        row = engine.update(bar)
        geometry = candle_geometry(bar, previous_close)
        previous_close = bar.close
        future_index = index + HORIZON
        if row is None or future_index >= len(bars) or bar.close <= 0:
            continue
        future_return = (bars[future_index].close - bar.close) / bar.close
        base.append(row)
        extended.append(row + geometry)
        labels.append(label_direction(future_return, threshold_bps=THRESHOLD_BPS))
    return base, extended, labels


def purged_cv_accuracy(
    features: list[tuple[Decimal, ...]], labels: list[str]
) -> tuple[float, list[float]]:
    label_map = DIRECTION_CLASS_INDEX
    x_all = np.array([[float(value) for value in row] for row in features], dtype=np.float64)
    y_all = np.array([label_map[label] for label in labels], dtype=np.int32)
    per_fold: list[float] = []
    for fold in purged_k_fold(len(features), n_splits=N_SPLITS, embargo=EMBARGO):
        train_x = x_all[list(fold.train_indices)]
        test_x = x_all[list(fold.test_indices)]
        booster = _fit_booster(train_x, y_all[list(fold.train_indices)])
        predictions = np.asarray(booster.predict(test_x)).argmax(axis=1)
        per_fold.append(float((predictions == y_all[list(fold.test_indices)]).mean()))
    return float(np.mean(per_fold)), per_fold


def _fit_booster(train_x: np.ndarray, train_y: np.ndarray) -> lgb.Booster:
    return lgb.train(
        {
            "objective": "multiclass",
            "num_class": 3,
            "metric": "multi_logloss",
            "verbosity": -1,
            "num_leaves": 15,
            "learning_rate": 0.05,
            "seed": SEED,
        },
        lgb.Dataset(train_x, label=train_y),
        num_boost_round=80,
    )


def _matrix(
    features: list[tuple[Decimal, ...]], labels: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    x_all = np.array([[float(value) for value in row] for row in features], dtype=np.float64)
    y_all = np.array([DIRECTION_CLASS_INDEX[label] for label in labels], dtype=np.int32)
    return x_all, y_all


def cv_accuracy_with_selection(
    features: list[tuple[Decimal, ...]],
    labels: list[str],
    *,
    top_k: int,
) -> tuple[float, list[float], list[tuple[str, ...]], np.ndarray]:
    """Top-k features by LightGBM gain, selected INSIDE each train fold.

    Selection on the whole dataset before cross-validation is the classic way to
    leak: the test fold influences which features are used. Here every fold picks
    its own subset from its own training rows only, so the reported accuracy is
    the accuracy of "select, then fit" — the procedure, not one lucky subset.
    """
    x_all, y_all = _matrix(features, labels)
    per_fold: list[float] = []
    subsets: list[tuple[str, ...]] = []
    gain_totals = np.zeros(x_all.shape[1], dtype=np.float64)
    for fold in purged_cv_kfold(len(features)):
        train_x = x_all[list(fold.train_indices)]
        train_y = y_all[list(fold.train_indices)]
        test_x = x_all[list(fold.test_indices)]
        scout = _fit_booster(train_x, train_y)
        gains = np.asarray(scout.feature_importance(importance_type="gain"), dtype=np.float64)
        if gains.sum() > 0:
            gain_totals += gains / gains.sum()
        chosen = np.sort(np.argsort(gains)[::-1][:top_k])
        subsets.append(tuple(FEATURE_NAMES[index] for index in chosen))
        booster = _fit_booster(train_x[:, chosen], train_y)
        predictions = np.asarray(booster.predict(test_x[:, chosen])).argmax(axis=1)
        per_fold.append(float((predictions == y_all[list(fold.test_indices)]).mean()))
    gain_share = gain_totals / len(subsets) if subsets else gain_totals
    return float(np.mean(per_fold)), per_fold, subsets, gain_share


def cv_accuracy_linear(
    features: list[tuple[Decimal, ...]],
    labels: list[str],
    *,
    penalty: float = 1.0,
) -> tuple[float, list[float]]:
    """Linear reference: ridge regression on one-hot labels, closed form.

    The Oxford benchmark's own message is that a linear model (AR1x, Sharpe 0.77)
    can tie a state-space model (Mamba2, 0.78), so "does the booster beat a line?"
    is the question to ask BEFORE reaching for any sequence architecture. Features
    are standardised on the train fold only — a global standardisation would leak
    test-fold scale into training.
    """
    x_all, y_all = _matrix(features, labels)
    per_fold: list[float] = []
    for fold in purged_cv_kfold(len(features)):
        train_x = x_all[list(fold.train_indices)]
        train_y = y_all[list(fold.train_indices)]
        test_x = x_all[list(fold.test_indices)]
        mean = train_x.mean(axis=0)
        std = train_x.std(axis=0)
        std[std == 0] = 1.0
        train_z = (train_x - mean) / std
        test_z = (test_x - mean) / std
        one_hot = np.eye(3)[train_y]
        prior = one_hot.mean(axis=0)
        gram = train_z.T @ train_z + penalty * np.eye(train_z.shape[1])
        weights = np.linalg.solve(gram, train_z.T @ (one_hot - prior))
        predictions = (test_z @ weights + prior).argmax(axis=1)
        per_fold.append(float((predictions == y_all[list(fold.test_indices)]).mean()))
    return float(np.mean(per_fold)), per_fold


def purged_cv_kfold(length: int) -> list[object]:
    return list(purged_k_fold(length, n_splits=N_SPLITS, embargo=EMBARGO))


def majority_class_rate(labels: list[str]) -> tuple[float, dict[str, int]]:
    counts = {name: labels.count(name) for name in sorted(set(labels))}
    return max(counts.values()) / len(labels), counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="catalog", help="Parquet catalog path")
    parser.add_argument("--interval", default="1h", help="Bar interval")
    parser.add_argument(
        "--instruments",
        default="ETH/USDT.SIM,BTC/USDT.SIM",
        help="Comma-separated instrument ids",
    )
    args = parser.parse_args()

    store = NautilusParquetCatalog(Path(args.catalog), fees=FeeSchedule.binance_spot_vip0())
    for instrument in args.instruments.split(","):
        bars = store.load(bar_type=nautilus_bar_type(instrument, args.interval))
        base, extended, labels = build_rows(bars)
        base_accuracy, base_folds = purged_cv_accuracy(base, labels)
        extended_accuracy, extended_folds = purged_cv_accuracy(extended, labels)
        majority, counts = majority_class_rate(labels)
        print(
            f"{instrument} bars={len(bars)} rows={len(labels)} labels={counts}\n"
            f"  majority_class_accuracy={majority:.4f}\n"
            f"  12 features             purged_cv_accuracy={base_accuracy:.4f} "
            f"folds={[round(value, 4) for value in base_folds]}\n"
            f"  12 + candle geometry    purged_cv_accuracy={extended_accuracy:.4f} "
            f"folds={[round(value, 4) for value in extended_folds]}\n"
            f"  delta={extended_accuracy - base_accuracy:+.4f}"
        )


if __name__ == "__main__":
    main()
