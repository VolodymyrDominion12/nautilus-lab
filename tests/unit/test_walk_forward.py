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
