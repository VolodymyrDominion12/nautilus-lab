"""Archive ingest from the dashboard, catalog/interval guards and footer-based describe."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi import HTTPException

import nautilus_lab.api.routes.catalog as routes
from nautilus_lab.api.catalog_service import describe_catalog, side_series_coverage
from nautilus_lab.api.requests import IngestRunRequest


def test_archive_command_maps_series_market_and_interval() -> None:
    cmd = routes._archive_command(
        "py",
        IngestRunRequest(
            symbols="all",
            series="klines",
            source="archive",
            market="um",
            interval="4h",
            start="2020-01-01",
        ),
    )
    assert cmd[3:] == [
        "ingest-archive",
        "--dataset",
        "klines",
        "--symbols",
        "all",
        "--market",
        "um",
        "--interval",
        "4h",
        "--start",
        "2020-01-01",
    ]
    funding = routes._archive_command(
        "py", IngestRunRequest(symbols="BTCUSDT", series="funding", source="archive")
    )
    assert "--interval" not in funding
    assert "--market" not in funding


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"source": "ftp"}, "unknown source"),
        ({"source": "archive", "series": "trades"}, "comes from the REST/live path"),
        ({"source": "archive", "incremental": True}, "incremental by its cache"),
    ],
)
def test_impossible_archive_requests_are_refused(body: dict[str, Any], message: str) -> None:
    with pytest.raises(HTTPException) as caught:
        routes._refuse_impossible(IngestRunRequest(symbols="BTCUSDT", **body))
    assert message in str(caught.value.detail)


def _summary(interval: str, market: str) -> dict[str, Any]:
    return {
        "exists": True,
        "name": f"catalog_{market}_{interval}",
        "bar_interval": interval,
        "market_type": market,
        "instruments": [{"instrument_id": "x"}],
    }


def test_bars_of_another_interval_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "describe_catalog_cached", lambda _p: _summary("1d", "spot"))
    request = IngestRunRequest(symbols="BTCUSDT", catalog="catalog_spot_1d", interval="4h")
    with pytest.raises(HTTPException) as caught:
        routes._refuse_catalog_mismatch(request)
    assert "holds 1d bars" in str(caught.value.detail)
    assert "catalog_spot_4h" in str(caught.value.detail)


def test_perp_bars_in_a_spot_catalog_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "describe_catalog_cached", lambda _p: _summary("1d", "spot"))
    request = IngestRunRequest(symbols="BTCUSDT-PERP", catalog="catalog_spot_1d", interval="1d")
    with pytest.raises(HTTPException) as caught:
        routes._refuse_catalog_mismatch(request)
    assert "spot catalog" in str(caught.value.detail)


def test_a_matching_or_empty_catalog_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "describe_catalog_cached", lambda _p: _summary("1d", "perp"))
    routes._refuse_catalog_mismatch(
        IngestRunRequest(
            symbols="all", catalog="catalog_perp_1d", interval="1d", source="archive", market="um"
        )
    )
    monkeypatch.setattr(routes, "describe_catalog_cached", lambda _p: {"exists": False})
    routes._refuse_catalog_mismatch(
        IngestRunRequest(symbols="BTCUSDT", catalog="new_one", interval="4h")
    )


def _bar_file(directory: Path, name: str, rows: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.table({"ts_event": pa.array(range(rows), pa.uint64())})
    pq.write_table(table, directory / name)


def test_describe_reads_footers_and_file_names_not_bars(tmp_path: Path) -> None:
    root = tmp_path / "catalog_spot_1d"
    _bar_file(
        root / "data" / "bar" / "BTCUSDT.SIM-1-DAY-LAST-EXTERNAL",
        "2020-01-01T23-59-59-999000064Z_2026-10-02T23-59-59-999000064Z.parquet",
        2467,
    )
    _bar_file(
        root / "data" / "bar" / "MATICUSDT.SIM-1-DAY-LAST-EXTERNAL",
        "2020-01-01T23-59-59-999000064Z_2024-09-09T23-59-59-999000064Z.parquet",
        1714,
    )
    summary = describe_catalog(str(root))
    assert summary["market_type"] == "spot"
    assert summary["bar_interval"] == "1d"
    assert summary["total_bars"] == 2467 + 1714
    btc = next(item for item in summary["instruments"] if item["instrument_id"] == "BTC/USDT.SIM")
    assert btc["bars_count"] == 2467
    assert btc["first_date"] == "2020-01-01T23:59:59.999000+00:00"
    assert btc["last_date"] == "2026-10-02T23:59:59.999000+00:00"


def test_side_series_coverage_finds_funding_in_any_catalog(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    funding_dir = tmp_path / "catalog_perp_1d" / "data" / "funding" / "SOLUSDT"
    funding_dir.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "ts_utc": pa.array(
                    [datetime(2020, 9, 14, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)],
                    pa.timestamp("us", tz="UTC"),
                )
            }
        ),
        funding_dir / "funding.parquet",
    )
    funding, premium = side_series_coverage([str(tmp_path / "catalog_perp_1d")])
    assert funding["SOLUSDT"]["first"].startswith("2020-09-14")
    assert funding["SOLUSDT"]["rows"] == 2
    assert funding["SOLUSDT"]["catalog"] == "catalog_perp_1d"
    assert premium == {}
