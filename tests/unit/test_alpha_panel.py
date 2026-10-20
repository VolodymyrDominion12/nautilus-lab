from __future__ import annotations

import numpy as np
import pytest

from nautilus_lab.application.alpha.panel import (
    Panel,
    align_columns,
    bucket_events,
    minutes_from_ns,
)


def test_close_stamps_round_to_the_minute() -> None:
    # 2026-10-04T23:59:59.999000064Z, as the catalog folders spell it
    ns = np.array([1_791_158_399_999_000_064], dtype=np.int64)
    assert int(minutes_from_ns(ns)[0]) * 60 == 1_791_158_400


def test_align_columns_leaves_missing_rows_nan() -> None:
    grid = np.array([10, 20, 30, 40], dtype=np.int64)
    out = align_columns(
        grid,
        {
            "A": (np.array([10, 30], dtype=np.int64), np.array([1.0, 3.0])),
            "B": (np.array([20, 40, 50], dtype=np.int64), np.array([2.0, 4.0, 5.0])),
        },
    )
    np.testing.assert_array_equal(out[:, 0], [1.0, np.nan, 3.0, np.nan])
    np.testing.assert_array_equal(out[:, 1], [np.nan, 2.0, np.nan, 4.0])


def test_funding_lands_on_the_bar_that_closes_at_settlement() -> None:
    grid = np.array([420, 480, 540, 600], dtype=np.int64)  # closes at 07:00 .. 10:00
    events = np.array([480, 540, 541], dtype=np.int64)  # 08:00, 09:00, 09:01
    paid, last = bucket_events(grid, events, np.array([0.0001, 0.0002, 0.0003]))
    assert np.isnan(paid[0])  # before the first settlement: unknown, not zero
    assert paid[1] == pytest.approx(0.0001)
    assert paid[2] == pytest.approx(0.0002)
    assert paid[3] == pytest.approx(0.0003)  # 09:01 is paid by the bar closing 10:00
    assert np.isnan(last[0])
    np.testing.assert_allclose(last[1:], [0.0001, 0.0002, 0.0003])


def test_two_events_in_one_bar_sum_and_the_later_rate_is_last() -> None:
    grid = np.array([1440, 2880], dtype=np.int64)
    paid, last = bucket_events(
        grid, np.array([1500, 2000, 2400], dtype=np.int64), np.array([1.0, 2.0, 3.0])
    )
    assert paid[1] == pytest.approx(6.0)
    assert last[1] == pytest.approx(3.0)


def test_events_after_the_last_close_are_dropped() -> None:
    paid, last = bucket_events(
        np.array([60], dtype=np.int64), np.array([120], dtype=np.int64), np.array([1.0])
    )
    assert np.isnan(paid[0])
    assert np.isnan(last[0])


def _panel(**overrides: object) -> Panel:
    ts = np.array([1, 2, 3], dtype=np.int64)
    fields = {name: np.ones((3, 2)) for name in ("close", "high", "low", "volume")}
    kwargs: dict[str, object] = {
        "ts_min": ts,
        "symbols": ("A", "B"),
        "fields": fields,
        "bar_minutes": 60,
    }
    kwargs.update(overrides)
    return Panel(**kwargs)  # type: ignore[arg-type]


def test_panel_validates_shape_order_and_fields() -> None:
    assert _panel().shape == (3, 2)
    with pytest.raises(ValueError, match="strictly increasing"):
        _panel(ts_min=np.array([1, 1, 2], dtype=np.int64))
    with pytest.raises(ValueError, match="missing required field"):
        _panel(fields={"close": np.ones((3, 2))})
    with pytest.raises(ValueError, match="shape"):
        _panel(fields={n: np.ones((2, 2)) for n in ("close", "high", "low", "volume")})


def test_select_symbols_reorders_columns() -> None:
    fields = {name: np.array([[1.0, 2.0]] * 3) for name in ("close", "high", "low", "volume")}
    view = _panel(fields=fields).select_symbols(["B"])
    assert view.symbols == ("B",)
    assert float(view.get("close")[0, 0]) == 2.0
