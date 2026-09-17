from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

IN_SAMPLE_ONLY = "full-catalog (in-sample only; not an out-of-sample model)"


@dataclass(frozen=True, slots=True)
class PurgedFold:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BinaryOofReport:
    """OOF metrics for a binary gate. Precision is undefined when nothing is taken."""

    accuracy: Decimal | None
    precision: Decimal | None
    recall: Decimal | None
    predicted_positives: int
    positives: int
    total: int
    baseline_precision: Decimal | None
    beats_always_take: bool | None


def parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_optional_utc(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    return parse_utc_timestamp(value.strip())


def require_exclusive_window(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and start >= end:
        raise ValueError("train window start must be before exclusive end")


def describe_train_window(*, start: datetime | None, end: datetime | None) -> str:
    """Human-readable window. Missing exclusive end is never presented as OOS-safe."""
    require_exclusive_window(start, end)
    if end is None:
        if start is None:
            return IN_SAMPLE_ONLY
        return f"[{start.isoformat()}, catalog-end) (in-sample only; not an out-of-sample model)"
    start_s = start.isoformat() if start is not None else "-inf"
    return f"[{start_s}, {end.isoformat()})"


def purged_k_fold(
    length: int,
    *,
    n_splits: int = 5,
    embargo: int = 10,
    sample_times: Sequence[int] | None = None,
    label_ends: Sequence[int] | None = None,
) -> list[PurgedFold]:
    """Purged K-fold: drop train rows whose label interval overlaps the test span.

    ``sample_times[i]`` is the event time (bar index). ``label_ends[i]`` is the
    exclusive end of information used to form the label. Embargo is applied in
    those same units, not as a count of rows. When both sequences are omitted,
    times default to row indices and each label spans one index — the legacy
    ±embargo split.
    """
    if length < n_splits * 2:
        raise ValueError("series too short for purged k-fold")
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if embargo < 0:
        raise ValueError("embargo must be >= 0")
    times = _as_times(length, sample_times)
    ends = _as_label_ends(length, times, label_ends)
    _validate_label_span(times, ends)

    fold_size = length // n_splits
    folds: list[PurgedFold] = []
    for index in range(n_splits):
        test_start = index * fold_size
        test_end = min(length, test_start + fold_size)
        test_indices = tuple(range(test_start, test_end))
        if not test_indices:
            continue
        span_start = min(times[pos] for pos in test_indices)
        span_end = max(ends[pos] for pos in test_indices)
        train_indices = tuple(
            pos
            for pos in range(length)
            if pos < test_start or pos >= test_end
            if not _overlaps(times[pos], ends[pos], span_start, span_end)
            if not _in_embargo(times[pos], span_start, span_end, embargo)
        )
        if train_indices and test_indices:
            folds.append(PurgedFold(train_indices=train_indices, test_indices=test_indices))
    return folds


def binary_oof_metrics(
    y_true: Sequence[int],
    scores: Sequence[Decimal],
    *,
    threshold: Decimal,
) -> BinaryOofReport:
    if len(y_true) != len(scores):
        raise ValueError("y_true and scores must have the same length")
    if threshold <= 0 or threshold >= 1:
        raise ValueError("threshold must be in (0, 1)")
    total = len(y_true)
    if total == 0:
        return BinaryOofReport(
            accuracy=None,
            precision=None,
            recall=None,
            predicted_positives=0,
            positives=0,
            total=0,
            baseline_precision=None,
            beats_always_take=None,
        )

    positives = 0
    predicted = 0
    true_positives = 0
    correct = 0
    for label, score in zip(y_true, scores, strict=True):
        if label not in (0, 1):
            raise ValueError("binary labels must be 0 or 1")
        take = score >= threshold
        if label == 1:
            positives += 1
        if take:
            predicted += 1
            if label == 1:
                true_positives += 1
        if take == (label == 1):
            correct += 1

    accuracy = Decimal(correct) / Decimal(total)
    baseline = Decimal(positives) / Decimal(total) if total else None
    precision = Decimal(true_positives) / Decimal(predicted) if predicted else None
    recall = Decimal(true_positives) / Decimal(positives) if positives else None
    beats: bool | None
    if precision is None or baseline is None:
        beats = False if total else None
    else:
        beats = precision > baseline
    return BinaryOofReport(
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        predicted_positives=predicted,
        positives=positives,
        total=total,
        baseline_precision=baseline,
        beats_always_take=beats,
    )


def majority_rate(labels: Sequence[str]) -> Decimal | None:
    if not labels:
        return None
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return Decimal(max(counts.values())) / Decimal(len(labels))


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


def _as_times(length: int, sample_times: Sequence[int] | None) -> tuple[int, ...]:
    if sample_times is None:
        return tuple(range(length))
    if len(sample_times) != length:
        raise ValueError("sample_times must match series length")
    return tuple(sample_times)


def _as_label_ends(
    length: int,
    times: Sequence[int],
    label_ends: Sequence[int] | None,
) -> tuple[int, ...]:
    if label_ends is None:
        return tuple(time + 1 for time in times)
    if len(label_ends) != length:
        raise ValueError("label_ends must match series length")
    return tuple(label_ends)


def _validate_label_span(times: Sequence[int], ends: Sequence[int]) -> None:
    for start, end in zip(times, ends, strict=True):
        if end <= start:
            raise ValueError("label_ends must be greater than sample_times")


def _overlaps(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def _in_embargo(time: int, span_start: int, span_end: int, embargo: int) -> bool:
    if embargo == 0:
        return False
    if span_start - embargo <= time < span_start:
        return True
    return span_end <= time < span_end + embargo
