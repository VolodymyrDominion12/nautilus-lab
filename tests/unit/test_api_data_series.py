"""Contracts for the series-aware dashboard: tick filters, ingest kinds, coverage.

Three things the interface now promises, each of which would silently degrade into a
wrong number rather than an error if it broke:

* a tick-level filter is refused for a robot that does not read ticks, and for a catalog
  that has no tick series — the engine reads a missing series as an empty one, so an
  accepted-but-unusable flag produces a run labelled "tick VPIN" whose every decision
  came from the bar proxy;
* an ingest names the series it writes, because one catalog holds four independent trees;
* `GET /api/data` reports which of those trees exist, since "the run finished" is not
  evidence that the data behind it existed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nautilus_lab.api.app import app
from nautilus_lab.api.data_health import describe_data_health, invalidate_data_health_cache
from nautilus_lab.api.routes.catalog import INGEST_SERIES_FLAGS
from nautilus_lab.domain.stress_slices import StressSliceName


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_tick_filter_is_refused_for_a_robot_that_never_reads_ticks(client: TestClient) -> None:
    """`--tick-vpin` on `ema` is a no-op in the engine, so it must not be accepted."""
    response = client.post(
        "/api/research",
        json={"robot": "ema", "source": "catalog", "tick_vpin": True},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "tick-level VPIN" in detail
    # the supported set must be named, or the user cannot pick a working robot
    assert "regime" in detail


def test_hawkes_filter_is_refused_for_a_robot_without_a_regime_router(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/research",
        json={"robot": "ema", "source": "catalog", "hawkes": True},
    )
    assert response.status_code == 400
    assert "Hawkes" in response.json()["detail"]


def test_tick_filter_is_refused_on_synthetic_bars(client: TestClient) -> None:
    """Synthetic bars carry no ticks, so the filter would run on its own defaults."""
    response = client.post(
        "/api/research",
        json={"robot": "regime", "source": "synthetic", "tick_vpin": True},
    )
    assert response.status_code == 400
    assert "aggregated-trade series" in response.json()["detail"]


def test_tick_filter_is_refused_when_the_catalog_has_no_tick_series(
    client: TestClient, tmp_path: Path
) -> None:
    """An empty catalog must be refused with the ingest command that fixes it."""
    empty = tmp_path / "catalog"
    empty.mkdir()
    response = client.post(
        "/api/research",
        json={
            "robot": "regime",
            "source": "catalog",
            "tick_vpin": True,
            "catalog_path": str(empty),
            "instrument_id": "ETH/USDT.SIM",
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "ETHUSDT" in detail
    assert "--trades" in detail


def test_every_ingest_kind_maps_to_a_real_cli_flag() -> None:
    """The dashboard must not invent flags: each entry is passed straight to `lab ingest`."""
    assert set(INGEST_SERIES_FLAGS) == {"klines", "trades", "funding", "depth"}
    # klines is the default path of `lab ingest` and therefore carries no flag
    assert INGEST_SERIES_FLAGS["klines"] == []
    for series, flags in INGEST_SERIES_FLAGS.items():
        for flag in flags:
            assert flag in {"--trades", "--funding", "--depth"}, (series, flag)


def test_ingest_rejects_an_unknown_series(client: TestClient) -> None:
    response = client.post("/api/catalog/ingest", json={"symbols": "ETHUSDT", "series": "ohlcv"})
    assert response.status_code == 400
    assert "unknown series" in response.json()["detail"]


def test_ingest_rejects_incremental_outside_the_bar_series(client: TestClient) -> None:
    """`--incremental` is bar-only; accepting it would imply a partial fetch."""
    response = client.post(
        "/api/catalog/ingest",
        json={"symbols": "ETHUSDT", "series": "trades", "incremental": True},
    )
    assert response.status_code == 400
    assert "incremental only applies to the bar series" in response.json()["detail"]


def test_depth_ingest_takes_one_symbol_and_no_window(client: TestClient) -> None:
    """A depth capture is one blocking WebSocket with no start/end to request."""
    multi = client.post(
        "/api/catalog/ingest",
        json={"symbols": "ETHUSDT,BTCUSDT", "series": "depth"},
    )
    assert multi.status_code == 400
    assert "one symbol at a time" in multi.json()["detail"]

    windowed = client.post(
        "/api/catalog/ingest",
        json={"symbols": "ETHUSDT", "series": "depth", "start": "2024-01-01"},
    )
    assert windowed.status_code == 400
    assert "no window to request" in windowed.json()["detail"]


def test_data_health_lists_every_series_tree() -> None:
    invalidate_data_health_cache()
    payload = describe_data_health("catalog")
    assert "instruments" in payload
    for entry in payload["instruments"]:
        # bars always exist for a described instrument; the other three are optional and
        # must be reported as present/absent rather than omitted.
        assert set(entry) >= {"instrument_id", "symbol", "bars", "taker_flow", "ticks", "funding"}
        assert entry["bars"]["present"] is True
        assert entry["taker_flow"]["present"] in (True, False)
        assert entry["ticks"]["present"] in (True, False)
    assert payload["tick_filters_ready"] == any(
        entry["ticks"]["present"] for entry in payload["instruments"]
    )


def test_data_health_endpoint_reports_the_selected_catalog(client: TestClient) -> None:
    response = client.get("/api/data", params={"catalog_path": "catalog"})
    assert response.status_code == 200
    body = response.json()
    assert body["catalog_path"]
    assert isinstance(body["instruments"], list)
    assert "bar_interval" in body


def test_status_reports_which_robots_read_ticks(client: TestClient) -> None:
    body = client.get("/api/status").json()
    assert "regime" in body["tick_vpin_robots"]
    assert "vpin_momentum" in body["tick_vpin_robots"]
    assert body["hawkes_robots"]
    # a robot with no regime router must not be advertised as tick-capable
    assert "ema" not in body["tick_vpin_robots"]
    assert "ema" not in body["hawkes_robots"]


def test_status_reports_stress_slice_windows(client: TestClient) -> None:
    """The UI shows the window a slice actually covers, because it replaces the load window.

    A slice the catalog does not hold loads zero bars, so the browser has to be able to
    compare the two date ranges before launching rather than after a failed run.
    """
    body = client.get("/api/status").json()
    slices = body["stress_slices"]
    assert {item["name"] for item in slices} == {name.value for name in StressSliceName}
    for item in slices:
        start = datetime.fromisoformat(item["start"])
        end = datetime.fromisoformat(item["end"])
        assert start.tzinfo is not None
        assert end.tzinfo is not None
        assert start < end
        assert item["description"]


def test_command_center_reports_catalog_freshness(client: TestClient) -> None:
    """The UI showed "data last date" only if the field existed; it did not."""
    body = client.get("/api/command-center").json()
    assert "catalog_last_date" in body
    assert "catalog_total_bars" in body
    assert "data_series" in body
    for row in body["data_series"]:
        assert set(row) >= {"instrument_id", "bars", "taker_flow", "ticks", "funding"}
