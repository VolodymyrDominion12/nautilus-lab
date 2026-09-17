from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.application.train_classifier import (
    IN_SAMPLE_ONLY,
    binary_oof_metrics,
    describe_train_window,
    parse_optional_utc,
    purged_k_fold,
    require_exclusive_window,
)


def _legacy_index_split(
    length: int, *, n_splits: int, embargo: int
) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    fold_size = length // n_splits
    folds: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for index in range(n_splits):
        test_start = index * fold_size
        test_end = min(length, test_start + fold_size)
        test_indices = tuple(range(test_start, test_end))
        train_indices = tuple(
            pos for pos in range(length) if pos < test_start - embargo or pos >= test_end + embargo
        )
        if train_indices and test_indices:
            folds.append((train_indices, test_indices))
    return folds


def test_index_embargo_matches_the_legacy_split() -> None:
    folds = purged_k_fold(100, n_splits=5, embargo=5)
    expected = _legacy_index_split(100, n_splits=5, embargo=5)
    assert [(fold.train_indices, fold.test_indices) for fold in folds] == expected


def test_overlapping_label_is_purged_from_train() -> None:
    times = tuple(range(0, 20, 2))
    ends = tuple(time + 10 for time in times)
    folds = purged_k_fold(
        len(times),
        n_splits=2,
        embargo=0,
        sample_times=times,
        label_ends=ends,
    )
    first = folds[0]
    assert first.test_indices == tuple(range(5))
    assert 5 not in first.train_indices
    assert all(pos not in first.train_indices for pos in range(5))


def test_embargo_uses_sample_time_not_event_count() -> None:
    times = (0, 50, 100, 150, 200, 250, 300, 350)
    ends = tuple(time + 1 for time in times)
    folds = purged_k_fold(
        len(times),
        n_splits=2,
        embargo=10,
        sample_times=times,
        label_ends=ends,
    )
    first = folds[0]
    assert first.test_indices == (0, 1, 2, 3)
    assert 4 in first.train_indices
    index_embargo = purged_k_fold(len(times), n_splits=2, embargo=1)
    assert 4 not in index_embargo[0].train_indices


def test_never_taking_does_not_beat_always_take() -> None:
    report = binary_oof_metrics(
        (1, 1, 0, 0, 0),
        (Decimal("0.1"), Decimal("0.2"), Decimal("0.1"), Decimal("0.1"), Decimal("0.1")),
        threshold=Decimal("0.55"),
    )
    assert report.predicted_positives == 0
    assert report.precision is None
    assert report.accuracy == Decimal("3") / Decimal("5")
    assert report.baseline_precision == Decimal("2") / Decimal("5")
    assert report.beats_always_take is False


def test_precision_above_always_take_is_a_win() -> None:
    report = binary_oof_metrics(
        (1, 1, 0, 0, 0),
        (Decimal("0.9"), Decimal("0.2"), Decimal("0.1"), Decimal("0.1"), Decimal("0.1")),
        threshold=Decimal("0.55"),
    )
    assert report.precision == Decimal("1")
    assert report.recall == Decimal("1") / Decimal("2")
    assert report.beats_always_take is True


def test_missing_end_is_labelled_in_sample_only() -> None:
    assert describe_train_window(start=None, end=None) == IN_SAMPLE_ONLY
    start = datetime(2024, 1, 1, tzinfo=UTC)
    assert "in-sample only" in describe_train_window(start=start, end=None)
    bounded = describe_train_window(start=start, end=datetime(2025, 1, 1, tzinfo=UTC))
    assert bounded.startswith("[2024-01-01")
    assert "in-sample only" not in bounded


def test_reversed_window_is_rejected() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="before exclusive end"):
        require_exclusive_window(start, end)


def test_parse_optional_utc_treats_blank_as_missing() -> None:
    assert parse_optional_utc(None) is None
    assert parse_optional_utc("  ") is None
    parsed = parse_optional_utc("2024-06-01")
    assert parsed == datetime(2024, 6, 1, tzinfo=UTC)
