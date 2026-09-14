from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.train_classifier import label_direction, purged_k_fold
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.formulaic_alphas import MIN_HISTORY, FormulaicAlphaEngine


@dataclass(frozen=True, slots=True)
class FormulaicDataset:
    features: list[tuple[Decimal, ...]]
    labels: list[str]
    future_returns: list[Decimal]


@dataclass(frozen=True, slots=True)
class FormulaicTrainReport:
    model_path: str
    rows: int
    folds: int
    accuracy: Decimal | None


def build_formulaic_dataset(
    bars: list[OhlcvBar],
    *,
    horizon: int = 5,
    threshold_bps: Decimal = Decimal("5"),
) -> FormulaicDataset:
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    engine = FormulaicAlphaEngine(history=max(MIN_HISTORY, 30))
    features: list[tuple[Decimal, ...]] = []
    labels: list[str] = []
    future_returns: list[Decimal] = []
    for index, bar in enumerate(bars):
        row = engine.update(bar)
        if row is None:
            continue
        future_index = index + horizon
        if future_index >= len(bars):
            break
        current = bar.close
        future = bars[future_index].close
        if current <= 0:
            continue
        ret = (future - current) / current
        features.append(row)
        labels.append(label_direction(ret, threshold_bps=threshold_bps))
        future_returns.append(ret)
    return FormulaicDataset(features=features, labels=labels, future_returns=future_returns)


def train_formulaic_lightgbm(
    dataset: FormulaicDataset,
    output_path: Path,
    *,
    n_splits: int = 5,
    embargo: int = 10,
) -> FormulaicTrainReport:
    try:
        import lightgbm as lgb
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("lightgbm extra not installed; run: uv sync --extra ml") from exc

    if len(dataset.features) < n_splits * 4:
        raise ValueError("dataset too short for purged k-fold training")

    label_map = {"down": 0, "flat": 1, "up": 2}
    x_all = np.array(
        [[float(item) for item in row] for row in dataset.features],
        dtype=np.float64,
    )
    y_all = np.array([label_map[item] for item in dataset.labels], dtype=np.int32)
    folds = purged_k_fold(len(dataset.features), n_splits=n_splits, embargo=embargo)
    correct = 0
    total = 0
    for fold in folds:
        train_x = x_all[list(fold.train_indices)]
        train_y = y_all[list(fold.train_indices)]
        test_x = x_all[list(fold.test_indices)]
        test_y = y_all[list(fold.test_indices)]
        if len(train_x) == 0 or len(test_x) == 0:
            continue
        train_set = lgb.Dataset(train_x, label=train_y)
        booster = lgb.train(
            {
                "objective": "multiclass",
                "num_class": 3,
                "metric": "multi_logloss",
                "verbosity": -1,
                "num_leaves": 15,
                "learning_rate": 0.05,
            },
            train_set,
            num_boost_round=80,
        )
        raw_preds = booster.predict(test_x)
        preds = np.asarray(raw_preds).argmax(axis=1)
        correct += int((preds == test_y).sum())
        total += len(test_y)

    final_set = lgb.Dataset(x_all, label=y_all)
    final_model = lgb.train(
        {
            "objective": "multiclass",
            "num_class": 3,
            "metric": "multi_logloss",
            "verbosity": -1,
            "num_leaves": 15,
            "learning_rate": 0.05,
        },
        final_set,
        num_boost_round=120,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(output_path))
    accuracy = Decimal(correct) / Decimal(total) if total else None
    return FormulaicTrainReport(
        model_path=str(output_path),
        rows=len(dataset.features),
        folds=len(folds),
        accuracy=accuracy,
    )
