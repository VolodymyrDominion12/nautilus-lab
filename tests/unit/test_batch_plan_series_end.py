"""A cell whose data stops long before the rest of the batch is blocked in the plan.

The 2026-10-13 4h batch ran MATICUSDT (spot bars end 2024-09-10) on 2023-05..2024-09 while
the other coins ran on 2025-06..2026-10, and averaged it in as the same months.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

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


# ---- market: spot or perp ----------------------------------------------------------------


def test_perp_market_runs_single_instrument_robots_on_the_perpetual() -> None:
    request = BatchRequest(robots=("regime", "funding"), symbols=("BTCUSDT",), market="perp")
    cells = {cell.cell_id: cell for cell in plan_cells(request, exists=_all_exist)}
    assert cells["regime_BTC"].instrument_id == "BTCUSDT-PERP.SIM"
    # the funding robot keeps its own spot-and-perp pair
    assert cells["funding_BTC"].instrument_id == "BTC/USDT.SIM"


def test_perp_series_is_checked_on_the_perpetual() -> None:
    request = BatchRequest(robots=("regime",), symbols=("LTCUSDT",), market="perp")
    (cell,) = plan_cells(
        request,
        exists=_all_exist,
        series=lambda _catalog, instrument, _interval: not instrument.endswith("-PERP.SIM"),
    )
    assert cell.blocked is not None
    assert "LTCUSDT-PERP.SIM" in cell.blocked


def test_unknown_market_is_refused() -> None:
    with pytest.raises(ValueError, match="market must be"):
        BatchRequest(robots=("regime",), symbols=("BTCUSDT",), market="margin")


# ---- pre-registration from a batch (plan 2026-10-16, P0.5) -------------------------------


def test_cells_register_the_batch_hypothesis_tagged_with_their_id() -> None:
    from nautilus_lab.application.batch_plan import BatchVariant, research_job_config

    request = BatchRequest(
        robots=("regime",),
        symbols=("BTCUSDT",),
        hypothesis="fixed donchian 40 beats VM buy&hold",
        variants=(
            BatchVariant(name="R1", env={"PARAM_SEARCH": "false"}),
            BatchVariant(name="R4", env={"REGIME_LEGS": "uptrend"}, hypothesis="longs alone"),
        ),
    )
    cells = {cell.cell_id: cell for cell in plan_cells(request, exists=_all_exist)}
    r1, r4 = cells["regime_BTC__R1"], cells["regime_BTC__R4"]
    assert r1.hypothesis == "fixed donchian 40 beats VM buy&hold [regime_BTC__R1]"
    assert r4.hypothesis == "longs alone [regime_BTC__R4]"
    assert research_job_config(request, r1)["preregister"] == r1.hypothesis


def test_a_batch_without_a_hypothesis_stays_exploratory() -> None:
    from nautilus_lab.application.batch_plan import research_job_config

    request = BatchRequest(robots=("regime",), symbols=("BTCUSDT",))
    (cell,) = plan_cells(request, exists=_all_exist)
    assert cell.hypothesis is None
    assert "preregister" not in research_job_config(request, cell)
