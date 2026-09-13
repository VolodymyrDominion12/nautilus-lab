from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PurgedFold:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


def purged_k_fold(
    length: int,
    *,
    n_splits: int = 5,
    embargo: int = 10,
) -> list[PurgedFold]:
    """Purged K-fold with embargo gaps between train and test."""
    if length < n_splits * 2:
        raise ValueError("series too short for purged k-fold")
    fold_size = length // n_splits
    folds: list[PurgedFold] = []
    for index in range(n_splits):
        test_start = index * fold_size
        test_end = min(length, test_start + fold_size)
        test_indices = tuple(range(test_start, test_end))
        train_indices = tuple(
            pos for pos in range(length) if pos < test_start - embargo or pos >= test_end + embargo
        )
        if train_indices and test_indices:
            folds.append(PurgedFold(train_indices=train_indices, test_indices=test_indices))
    return folds


def label_direction(
    future_return: Decimal,
    *,
    threshold_bps: Decimal = Decimal("5"),
) -> str:
    threshold = threshold_bps / Decimal("10000")
    if future_return > threshold:
        return "up"
    if future_return < -threshold:
        return "down"
    return "flat"
