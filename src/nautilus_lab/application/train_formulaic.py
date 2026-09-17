from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.train_classifier import (
    describe_train_window,
    label_direction,
    majority_rate,
    purged_k_fold,
)
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.formulaic_alphas import MIN_HISTORY, FormulaicAlphaEngine
from nautilus_lab.domain.ml_classifier import DIRECTION_CLASS_INDEX, DIRECTION_CLASSES


@dataclass(frozen=True, slots=True)
class FormulaicDataset:
    features: list[tuple[Decimal, ...]]
    labels: list[str]
    future_returns: list[Decimal]
    sample_times: tuple[int, ...]
    label_ends: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FormulaicTrainReport:
    model_path: str
    rows: int
    folds: int
    accuracy: Decimal | None
    majority_rate: Decimal | None
    beats_majority: bool | None
    train_window: str


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
    sample_times: list[int] = []
    label_ends: list[int] = []
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
        sample_times.append(index)
        label_ends.append(index + horizon + 1)
    return FormulaicDataset(
        features=features,
        labels=labels,
        future_returns=future_returns,
        sample_times=tuple(sample_times),
        label_ends=tuple(label_ends),
    )


def train_formulaic_lightgbm(
    dataset: FormulaicDataset,
    output_path: Path,
    *,
    n_splits: int = 5,
    embargo: int = 10,
    train_window: str | None = None,
) -> FormulaicTrainReport:
    try:
        import lightgbm as lgb
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("lightgbm extra not installed; run: uv sync --extra ml") from exc

    if len(dataset.features) < n_splits * 4:
        raise ValueError("dataset too short for purged k-fold training")

    label_map = DIRECTION_CLASS_INDEX
    x_all = np.array(
        [[float(item) for item in row] for row in dataset.features],
        dtype=np.float64,
    )
    y_all = np.array([label_map[item] for item in dataset.labels], dtype=np.int32)
    folds = purged_k_fold(
        len(dataset.features),
        n_splits=n_splits,
        embargo=embargo,
        sample_times=dataset.sample_times,
        label_ends=dataset.label_ends,
    )
    booster_params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "verbosity": -1,
        "num_leaves": 15,
        "learning_rate": 0.05,
    }
    oof_true: list[str] = []
    oof_pred: list[str] = []
    for fold in folds:
        train_x = x_all[list(fold.train_indices)]
        train_y = y_all[list(fold.train_indices)]
        test_x = x_all[list(fold.test_indices)]
        test_y = y_all[list(fold.test_indices)]
        if len(train_x) == 0 or len(test_x) == 0:
            continue
        booster = lgb.train(
            booster_params,
            lgb.Dataset(train_x, label=train_y),
            num_boost_round=80,
        )
        raw_preds = booster.predict(test_x)
        preds = np.asarray(raw_preds).argmax(axis=1)
        for true_code, pred_code in zip(test_y.tolist(), preds.tolist(), strict=True):
            oof_true.append(DIRECTION_CLASSES[int(true_code)])
            oof_pred.append(DIRECTION_CLASSES[int(pred_code)])

    final_model = lgb.train(
        booster_params,
        lgb.Dataset(x_all, label=y_all),
        num_boost_round=120,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(output_path))
    correct = sum(true == pred for true, pred in zip(oof_true, oof_pred, strict=True))
    accuracy = Decimal(correct) / Decimal(len(oof_true)) if oof_true else None
    baseline = majority_rate(oof_true)
    beats = accuracy > baseline if accuracy is not None and baseline is not None else None
    return FormulaicTrainReport(
        model_path=str(output_path),
        rows=len(dataset.features),
        folds=len(folds),
        accuracy=accuracy,
        majority_rate=baseline,
        beats_majority=beats,
        train_window=train_window or describe_train_window(start=None, end=None),
    )
