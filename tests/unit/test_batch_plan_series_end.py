"""A cell whose data stops long before the rest of the batch is blocked in the plan.

The 2026-10-13 4h batch ran MATICUSDT (spot bars end 2024-09-10) on 2023-05..2024-09 while
the other coins ran on 2025-06..2026-10, and averaged it in as the same months.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from nautilus_lab.application.batch_plan import BatchRequest, parse_parquet_end, plan_cells

END = datetime(2026, 10, 6, 23, 59, 59, tzinfo=UTC)


def _all_exist(_path: str) -> bool:
    return True


def _ends(**by_base: datetime | None) -> Callable[[str, str, str], datetime | None]:
    def probe(_catalog: str, instrument: str, _interval: str) -> datetime | None:
        return by_base.get(instrument.split("/")[0], END)

    return probe


def test_parquet_end_is_read_from_the_nautilus_file_name() -> None:
    name = "2020-01-01T03-59-59-999000064Z_2024-09-10T02-59-59-999000064Z.parquet"
    assert parse_parquet_end(name) == datetime(2024, 9, 10, 2, 59, 59, tzinfo=UTC)


def test_unparseable_file_names_give_no_end() -> None:
    assert parse_parquet_end("bars.parquet") is None
    assert parse_parquet_end("a_b.parquet") is None


def test_a_series_that_ended_months_earlier_is_blocked() -> None:
    request = BatchRequest(robots=("regime",), symbols=("BTCUSDT", "MATICUSDT"))
    cells = plan_cells(
        request,
        exists=_all_exist,
        series_end=_ends(MATIC=datetime(2024, 9, 10, 2, 59, 59, tzinfo=UTC)),
    )
    by_id = {cell.cell_id: cell for cell in cells}
    assert by_id["regime_BTC"].runnable
    blocked = by_id["regime_MATIC"].blocked
    assert blocked is not None
    assert "2024-09-10" in blocked
    assert "another period" in blocked


def test_a_few_days_of_ingest_lag_is_not_blocked() -> None:
    request = BatchRequest(robots=("ema",), symbols=("BTCUSDT", "ETHUSDT"))
    cells = plan_cells(
        request,
        exists=_all_exist,
        series_end=_ends(ETH=datetime(2026, 10, 3, tzinfo=UTC)),
    )
    assert all(cell.runnable for cell in cells)


def test_an_unknown_end_never_blocks() -> None:
    request = BatchRequest(robots=("ema",), symbols=("BTCUSDT", "ETHUSDT"))
    cells = plan_cells(request, exists=_all_exist, series_end=_ends(ETH=None))
    assert all(cell.runnable for cell in cells)


def test_without_a_probe_the_plan_is_unchanged() -> None:
    request = BatchRequest(robots=("ema",), symbols=("BTCUSDT", "MATICUSDT"))
    assert all(cell.runnable for cell in plan_cells(request, exists=_all_exist))
