from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.train_classifier import purged_k_fold
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.formulaic_alphas import MIN_HISTORY, FormulaicAlphaEngine
from nautilus_lab.domain.meta_label_strategy import PrimaryRobot, encode_meta_features
from nautilus_lab.domain.regime import RegimeParams
from nautilus_lab.domain.regime_router import RegimeRouter
from nautilus_lab.domain.signals import SignalSide
from nautilus_lab.domain.triple_barrier import (
    BarrierTouch,
    TripleBarrierConfig,
    TripleBarrierOutcome,
    label_triple_barrier,
    rolling_volatility,
)


@dataclass(frozen=True, slots=True)
class MetaLabelDataset:
    features: list[tuple[Decimal, ...]]
    labels: list[int]
    outcomes: list[TripleBarrierOutcome]


@dataclass(frozen=True, slots=True)
class MetaLabelTrainReport:
    model_path: str
    rows: int
    folds: int
    accuracy: Decimal | None
    take_profit_rate: Decimal | None


def build_meta_label_dataset(
    bars: list[OhlcvBar],
    *,
    instrument_id: str,
    primary: PrimaryRobot | None = None,
    regime: RegimeParams | None = None,
    barrier: TripleBarrierConfig | None = None,
    volatility_window: int = 20,
) -> MetaLabelDataset:
    robot = (
        primary
        if primary is not None
        else RegimeRouter(
            instrument_id=instrument_id,
            params=regime or RegimeParams(),
        )
    )
    params = barrier or TripleBarrierConfig()
    engine = FormulaicAlphaEngine(history=max(MIN_HISTORY, 30))
    features: list[tuple[Decimal, ...]] = []
    labels: list[int] = []
    outcomes: list[TripleBarrierOutcome] = []
    awaiting_entry = True
    for index, bar in enumerate(bars):
        row = engine.update(bar)
        signal = robot.on_bar(bar)
        if signal is not None and signal.side is SignalSide.FLAT:
            awaiting_entry = True
            continue
        if not awaiting_entry or signal is None:
            continue
        if signal.side not in (SignalSide.BUY, SignalSide.SELL):
            continue
        if row is None:
            continue
        volatility = rolling_volatility(bars, index, window=volatility_window)
        if volatility is None:
            continue
        outcome = label_triple_barrier(
            bars,
            index,
            volatility=volatility,
            config=params,
            side=signal.side,
        )
        if outcome is None:
            continue
        features.append(encode_meta_features(row, signal.side))
        labels.append(1 if outcome.touch is BarrierTouch.PROFIT else 0)
        outcomes.append(outcome)
        awaiting_entry = False
    return MetaLabelDataset(features=features, labels=labels, outcomes=outcomes)


def train_meta_label_lightgbm(
    dataset: MetaLabelDataset,
    output_path: Path,
    *,
    n_splits: int = 5,
    embargo: int = 10,
) -> MetaLabelTrainReport:
    try:
        import lightgbm as lgb
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("lightgbm extra not installed; run: uv sync --extra ml") from exc

    if len(dataset.features) < n_splits * 4:
        raise ValueError("dataset too short for purged k-fold training")

    x_all = np.array(
        [[float(item) for item in row] for row in dataset.features],
        dtype=np.float64,
    )
    y_all = np.array(dataset.labels, dtype=np.int32)
    folds = purged_k_fold(len(dataset.features), n_splits=n_splits, embargo=embargo)
    booster_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "verbosity": -1,
        "num_leaves": 15,
        "learning_rate": 0.05,
    }
    correct = 0
    total = 0
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
        probs = np.asarray(booster.predict(test_x))
        preds = (probs >= 0.5).astype(np.int32)
        correct += int((preds == test_y).sum())
        total += len(test_y)

    final_model = lgb.train(
        booster_params,
        lgb.Dataset(x_all, label=y_all),
        num_boost_round=120,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_model.save_model(str(output_path))
    accuracy = Decimal(correct) / Decimal(total) if total else None
    wins = sum(dataset.labels)
    take_profit_rate = Decimal(wins) / Decimal(len(dataset.labels)) if dataset.labels else None
    return MetaLabelTrainReport(
        model_path=str(output_path),
        rows=len(dataset.features),
        folds=len(folds),
        accuracy=accuracy,
        take_profit_rate=take_profit_rate,
    )
