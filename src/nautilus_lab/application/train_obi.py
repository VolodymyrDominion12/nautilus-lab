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
from nautilus_lab.domain.hawkes import ExponentialHawkes
from nautilus_lab.domain.microstructure import (
    liquidity_fade_velocity,
    order_book_imbalance,
    weighted_order_flow_imbalance,
)
from nautilus_lab.domain.ml_classifier import DIRECTION_CLASS_INDEX, DIRECTION_CLASSES
from nautilus_lab.domain.order_book import OrderBookSnapshot


@dataclass(frozen=True, slots=True)
class ObiDataset:
    features: list[tuple[Decimal, ...]]
    labels: list[str]
    sample_times: tuple[int, ...]
    label_ends: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ObiTrainReport:
    model_path: str
    rows: int
    folds: int
    accuracy: Decimal | None
    majority_rate: Decimal | None
    beats_majority: bool | None
    train_window: str


def build_obi_dataset(
    snapshots: list[OrderBookSnapshot],
    *,
    horizon: int = 50,
    threshold_bps: Decimal = Decimal("0.5"),
) -> ObiDataset:
    if horizon < 1:
        raise ValueError("horizon must be >= 1")

    features: list[tuple[Decimal, ...]] = []
    labels: list[str] = []
    sample_times: list[int] = []
    label_ends: list[int] = []

    hawkes = ExponentialHawkes()
    previous: OrderBookSnapshot | None = None

    for index, snapshot in enumerate(snapshots):
        snapshot.validate()
        if previous is None:
            previous = snapshot
            continue

        dt_seconds = Decimal(str((snapshot.ts_utc - previous.ts_utc).total_seconds()))
        # Two snapshots sharing a timestamp carry no elapsed time; dividing by it in the
        # liquidity-fade velocity would raise, so the later one cannot be used as an update.
        if dt_seconds == 0:
            previous = snapshot
            continue

        obi = order_book_imbalance(snapshot)
        ofi = weighted_order_flow_imbalance(snapshot, previous)
        fade = liquidity_fade_velocity(snapshot, previous)

        buy_volume = ofi if ofi > 0 else Decimal("0")
        sell_volume = -ofi if ofi < 0 else Decimal("0")

        hawkes_intensity = hawkes.update(
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            dt_seconds=dt_seconds,
        )

        row = (
            obi,
            ofi,
            fade,
            hawkes_intensity.buy_intensity,
            hawkes_intensity.sell_intensity,
        )

        future_index = index + horizon
        if future_index >= len(snapshots):
            break

        current_mid = (snapshot.bids[0].price + snapshot.asks[0].price) / 2
        future_snapshot = snapshots[future_index]
        future_mid = (future_snapshot.bids[0].price + future_snapshot.asks[0].price) / 2

        if current_mid <= 0:
            previous = snapshot
            continue

        ret = (future_mid - current_mid) / current_mid
        features.append(row)
        labels.append(label_direction(ret, threshold_bps=threshold_bps))
        sample_times.append(index)
        label_ends.append(index + horizon + 1)

        previous = snapshot

    return ObiDataset(
        features=features,
        labels=labels,
        sample_times=tuple(sample_times),
        label_ends=tuple(label_ends),
    )


def train_obi_lightgbm(
    dataset: ObiDataset,
    output_path: Path,
    *,
    n_splits: int = 5,
    embargo: int = 10,
    train_window: str | None = None,
) -> ObiTrainReport:
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
    return ObiTrainReport(
        model_path=str(output_path),
        rows=len(dataset.features),
        folds=len(folds),
        accuracy=accuracy,
        majority_rate=baseline,
        beats_majority=beats,
        train_window=train_window or describe_train_window(start=None, end=None),
    )
