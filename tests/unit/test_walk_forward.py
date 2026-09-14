from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import InvalidWindowError
from nautilus_lab.domain.walk_forward import (
    WalkForwardWindow,
    anchored_window,
    bars_in_range,
    rolling_windows,
    split_by_window,
)


def _bar(ts: datetime) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("1"),
    )


def test_window_rejects_overlap() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(InvalidWindowError, match="overlap"):
        WalkForwardWindow(
            in_sample_start=start,
            in_sample_end=datetime(2024, 3, 1, tzinfo=UTC),
            out_of_sample_start=datetime(2024, 2, 1, tzinfo=UTC),
            out_of_sample_end=datetime(2024, 4, 1, tzinfo=UTC),
        )


def test_window_allows_purge_gap() -> None:
    window = WalkForwardWindow(
        in_sample_start=datetime(2024, 1, 1, tzinfo=UTC),
        in_sample_end=datetime(2024, 2, 1, tzinfo=UTC),
        out_of_sample_start=datetime(2024, 3, 1, tzinfo=UTC),
        out_of_sample_end=datetime(2024, 4, 1, tzinfo=UTC),
    )
    assert window.in_sample_end < window.out_of_sample_start


def test_window_rejects_non_utc() -> None:
    kyiv = datetime(2024, 1, 1, tzinfo=ZoneInfo("Europe/Kyiv"))
    with pytest.raises(InvalidWindowError, match="UTC"):
        WalkForwardWindow(
            in_sample_start=kyiv,
            in_sample_end=datetime(2024, 2, 1, tzinfo=UTC),
            out_of_sample_start=datetime(2024, 2, 1, tzinfo=UTC),
            out_of_sample_end=datetime(2024, 3, 1, tzinfo=UTC),
        )


def test_split_is_half_open_and_contiguous() -> None:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [_bar(origin + timedelta(days=index)) for index in range(10)]
    window = WalkForwardWindow(
        in_sample_start=origin,
        in_sample_end=origin + timedelta(days=7),
        out_of_sample_start=origin + timedelta(days=7),
        out_of_sample_end=origin + timedelta(days=10),
    )

    split = split_by_window(bars, window)

    assert len(split.in_sample) == 7
    assert len(split.out_of_sample) == 3
    assert split.in_sample[-1].ts_utc < split.out_of_sample[0].ts_utc


def test_bars_in_range_excludes_end() -> None:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [_bar(origin), _bar(origin + timedelta(days=1)), _bar(origin + timedelta(days=2))]
    sliced = bars_in_range(bars, start=origin, end=origin + timedelta(days=2))
    assert len(sliced) == 2
    assert sliced[-1].ts_utc == origin + timedelta(days=1)


def test_anchored_window_uses_first_fraction_for_selection() -> None:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    bars = [_bar(origin + timedelta(days=index)) for index in range(10)]

    window = anchored_window(bars, in_sample_fraction=Decimal("0.7"))
    split = split_by_window(bars, window)

    assert len(split.in_sample) == 7
    assert len(split.out_of_sample) == 3


# --- rolling multi-window folds ----------------------------------------------------


def _series(count: int) -> list[OhlcvBar]:
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    return [_bar(origin + timedelta(days=index)) for index in range(count)]


def test_rolling_windows_slide_the_selection_window_forward() -> None:
    """Each fold must select on its own data, not re-read the first in-sample block.

    With 100 bars, fraction 0.5 and embargo 2, the in-sample block is 50 bars and each
    out-of-sample block is (100 - 50 - 2) // 4 = 12 bars, so the folds are
    IS[0:50]/OOS[52:64], IS[12:62]/OOS[64:76], IS[24:74]/OOS[76:88], IS[36:86]/OOS[88:100].
    """
    bars = _series(100)
    windows = rolling_windows(bars, folds=4, in_sample_fraction=Decimal("0.5"), embargo_bars=2)

    assert len(windows) == 4
    sizes = [
        (
            len(bars_in_range(bars, start=w.in_sample_start, end=w.in_sample_end)),
            len(bars_in_range(bars, start=w.out_of_sample_start, end=w.out_of_sample_end)),
        )
        for w in windows
    ]
    assert sizes == [(50, 12), (50, 12), (50, 12), (50, 12)]

    starts = [w.in_sample_start for w in windows]
    assert starts == sorted(starts)
    assert len(set(starts)) == 4


def test_rolling_windows_leave_an_embargo_gap() -> None:
    bars = _series(100)
    windows = rolling_windows(bars, folds=4, in_sample_fraction=Decimal("0.5"), embargo_bars=2)
    for window in windows:
        in_sample = bars_in_range(bars, start=window.in_sample_start, end=window.in_sample_end)
        out_of_sample = bars_in_range(
            bars, start=window.out_of_sample_start, end=window.out_of_sample_end
        )
        gap = out_of_sample[0].ts_utc - in_sample[-1].ts_utc
        assert gap == timedelta(days=3)  # one bar of separation plus the 2-bar embargo


def test_rolling_windows_reach_the_most_recent_bar() -> None:
    bars = _series(100)
    windows = rolling_windows(bars, folds=3, in_sample_fraction=Decimal("0.6"), embargo_bars=0)
    last = windows[-1]
    assert last.out_of_sample_end > bars[-1].ts_utc
    assert last.out_of_sample_end <= bars[-1].ts_utc + timedelta(microseconds=1)


def test_rolling_windows_never_overlap_in_sample_and_out_of_sample() -> None:
    bars = _series(120)
    for window in rolling_windows(bars, folds=5, in_sample_fraction=Decimal("0.5"), embargo_bars=3):
        split = split_by_window(bars, window)
        assert split.in_sample[-1].ts_utc < split.out_of_sample[0].ts_utc


def test_rolling_windows_reject_more_folds_than_bars_can_fill() -> None:
    with pytest.raises(InvalidWindowError, match="cannot fill"):
        rolling_windows(_series(40), folds=10, in_sample_fraction=Decimal("0.9"))


def test_rolling_windows_reject_bad_fraction() -> None:
    with pytest.raises(InvalidWindowError, match="in_sample_fraction"):
        rolling_windows(_series(100), folds=2, in_sample_fraction=Decimal("1"))


def test_rolling_windows_reject_zero_folds() -> None:
    with pytest.raises(InvalidWindowError, match="folds must be"):
        rolling_windows(_series(100), folds=0, in_sample_fraction=Decimal("0.5"))
