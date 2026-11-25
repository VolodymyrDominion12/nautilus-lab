"""Tests for Databento DBN ingest, bars_timestamp_on_close invariant, roll isolation, and CLI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog
from nautilus_trader.persistence.catalog.singleton import clear_singleton_instances

from nautilus_lab.domain.calendar import TradingCalendar, is_trading_bar_close
from nautilus_lab.domain.data_quality import QualityStatus, check_bars
from nautilus_lab.domain.errors import LiveTradingDisabledError
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.archive_source import JsonQualityStore
from nautilus_lab.infrastructure.databento_feed import (
    JsonRollStore,
    download_databento_dbn,
    ingest_databento_dbn,
    load_dbn_bars,
    normalize_databento_instrument_id,
)
from nautilus_lab.infrastructure.nautilus.bar_convert import datetime_to_nanos
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.interfaces import cli


def _make_nautilus_bar(
    *,
    instrument_id: str,
    ts_utc: datetime,
    open_px: str,
    high_px: str,
    low_px: str,
    close_px: str,
    volume: str,
    spec: str = "1-HOUR",
) -> Bar:
    bt = BarType.from_str(f"{instrument_id}-{spec}-LAST-EXTERNAL")
    ts_ns = datetime_to_nanos(ts_utc)
    return Bar(
        bar_type=bt,
        open=Price.from_str(open_px),
        high=Price.from_str(high_px),
        low=Price.from_str(low_px),
        close=Price.from_str(close_px),
        volume=Quantity.from_str(volume),
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


class _RecordingLoader:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars
        self.calls: list[dict[str, Any]] = []

    def from_dbn_file(
        self,
        path: Any,
        instrument_id: InstrumentId | None = None,
        price_precision: int | None = None,
        as_legacy_cython: bool = True,
        include_trades: bool = False,
        use_exchange_as_venue: bool = False,
        bars_timestamp_on_close: bool = True,
        skip_on_error: bool = False,
        expiration_overrides: dict[str, dict[str, str]] | None = None,
    ) -> list[Bar]:
        self.calls.append(
            {
                "path": Path(path),
                "instrument_id": instrument_id,
                "price_precision": price_precision,
                "as_legacy_cython": as_legacy_cython,
                "include_trades": include_trades,
                "use_exchange_as_venue": use_exchange_as_venue,
                "bars_timestamp_on_close": bars_timestamp_on_close,
            }
        )
        return list(self._bars)


def test_normalize_databento_instrument_id_handles_formats_and_fails_closed() -> None:
    assert normalize_databento_instrument_id("MGCZ26.XCEC") == "MGCZ26.XCEC"
    assert normalize_databento_instrument_id("mgc.v.0") == "MGC.v.0.GLBX"
    assert (
        normalize_databento_instrument_id("GCZ6.XCEC", futures_year_digits=2, reference_year=2026)
        == "GCZ26.XCEC"
    )
    with pytest.raises(ValueError, match="unsupported instrument"):
        normalize_databento_instrument_id("ESZ26.XCME")


def test_load_dbn_bars_enforces_timestamp_on_close_invariant(tmp_path: Path) -> None:
    dbn_file = tmp_path / "mgc.dbn.zst"
    dbn_file.write_bytes(b"placeholder")

    with pytest.raises(ValueError, match="bars_timestamp_on_close must remain True"):
        load_dbn_bars(dbn_file, bars_timestamp_on_close=False)

    ts = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)
    loader = _RecordingLoader(
        [
            _make_nautilus_bar(
                instrument_id="MGCZ26.XCEC",
                ts_utc=ts,
                open_px="2620.00",
                high_px="2625.00",
                low_px="2618.00",
                close_px="2624.50",
                volume="100",
            )
        ]
    )
    bars, inst_id, interval, rolls = load_dbn_bars(
        dbn_file,
        loader_factory=lambda: loader,
    )
    assert inst_id == "MGCZ26.XCEC"
    assert interval == "1h"
    assert rolls == ()
    assert len(bars) == 1
    assert bars[0].close == Decimal("2624.50")
    assert loader.calls[0]["bars_timestamp_on_close"] is True
    assert loader.calls[0]["use_exchange_as_venue"] is True


def test_ingest_databento_detects_and_isolates_contract_rolls(tmp_path: Path) -> None:
    clear_singleton_instances(ParquetDataCatalog)
    dbn_file = tmp_path / "mgc_continuous.dbn.zst"
    dbn_file.write_bytes(b"placeholder")

    # Build 20 valid CME Globex 23x5 1h bars where bar 10 rolls from MGCG26 -> MGCJ26
    # right across a weekend / contract transition with a basis step.
    cursor = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)
    raw_bars: list[Bar] = []
    roll_ts: datetime | None = None
    while len(raw_bars) < 20:
        if not is_trading_bar_close(
            cursor,
            interval=timedelta(hours=1),
            calendar=TradingCalendar.CME_GLOBEX_23_5,
        ):
            cursor += timedelta(hours=1)
            continue
        idx = len(raw_bars)
        is_second_contract = idx >= 10
        if idx == 10:
            roll_ts = cursor
        contract = "MGCJ26.XCEC" if is_second_contract else "MGCG26.XCEC"
        # Simulate a large roll jump at idx == 10 after a gap so QC would fail without isolation.
        if is_second_contract:
            px = Decimal("2750.00") + Decimal(idx - 10)
        else:
            px = Decimal("2620.00") + Decimal(idx)
        raw_bars.append(
            _make_nautilus_bar(
                instrument_id=contract,
                ts_utc=cursor,
                open_px=f"{px:.2f}",
                high_px=f"{px + Decimal('1.00'):.2f}",
                low_px=f"{px - Decimal('1.00'):.2f}",
                close_px=f"{px + Decimal('0.50'):.2f}",
                volume="150",
            )
        )
        cursor += timedelta(hours=1)

    assert roll_ts is not None
    catalog_dir = tmp_path / "catalog_comex_1h"
    loader = _RecordingLoader(raw_bars)
    report = ingest_databento_dbn(
        dbn_path=dbn_file,
        catalog_path=catalog_dir,
        mode=TradingMode.RESEARCH,
        instrument_id="MGC.v.0.GLBX",
        loader_factory=lambda: loader,
    )

    assert report.instrument_id == "MGC.v.0.GLBX"
    assert report.interval == "1h"
    assert report.rows_written == 20
    assert report.quality is QualityStatus.OK
    assert len(report.roll_dates) == 1
    assert report.roll_dates[0].ts_utc == roll_ts
    assert report.roll_dates[0].from_contract == "MGCG26.XCEC"
    assert report.roll_dates[0].to_contract == "MGCJ26.XCEC"
    assert any("roll boundary isolated" in note for note in report.notes)

    # Confirm loader preserved raw contract IDs (instrument_id=None) during decode
    assert loader.calls[0]["instrument_id"] is None

    # Confirm roll table & quality store were persisted atomically
    roll_store = JsonRollStore(catalog_dir)
    assert roll_ts in roll_store.timestamps_for(report.bar_type)
    quality_data = JsonQualityStore(catalog_dir).load()
    assert quality_data[report.bar_type]["status"] == "ok"  # type: ignore[index]

    # Confirm catalog round-trip
    loaded = NautilusParquetCatalog(catalog_dir).load(bar_type=report.bar_type)
    assert len(loaded) == 20
    assert loaded[0].instrument_id == "MGC.v.0.GLBX"


def test_check_bars_isolates_declared_roll_boundary_from_relisting_fail() -> None:
    from nautilus_lab.domain.bars import OhlcvBar

    t0 = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)  # 1 missing bar gap + >3x price jump
    bars = [
        OhlcvBar(
            instrument_id="MGC.v.0.GLBX",
            ts_utc=t0,
            open=Decimal("1000"),
            high=Decimal("1005"),
            low=Decimal("995"),
            close=Decimal("1000"),
            volume=Decimal("10"),
        ),
        OhlcvBar(
            instrument_id="MGC.v.0.GLBX",
            ts_utc=t1,
            open=Decimal("4000"),
            high=Decimal("4010"),
            low=Decimal("3990"),
            close=Decimal("4000"),
            volume=Decimal("10"),
        ),
    ]
    unisolated = check_bars(
        bars,
        interval=timedelta(hours=1),
        calendar=TradingCalendar.CME_GLOBEX_23_5,
    )
    assert unisolated.status() is QualityStatus.FAIL
    assert len(unisolated.relisting_suspects) == 1

    isolated = check_bars(
        bars,
        interval=timedelta(hours=1),
        calendar=TradingCalendar.CME_GLOBEX_23_5,
        roll_timestamps=frozenset({t1}),
    )
    assert len(isolated.relisting_suspects) == 0
    assert len(isolated.extreme_moves) == 0
    assert any("roll boundary isolated" in note for note in isolated.notes)


def test_download_databento_dbn_fails_closed_without_leaking_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "db-super-secret-api-key-999"
    out = tmp_path / "out.dbn.zst"

    with pytest.raises(ValueError, match="DATABENTO_API_KEY is required"):
        download_databento_dbn(
            dataset="GLBX.MDP3",
            symbols="MGC.v.0",
            schema="ohlcv-1h",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
            output_path=out,
            api_key="",
        )

    class _ExplodingHistorical:
        def __init__(self, key: str) -> None:
            self.key = key

        @property
        def timeseries(self) -> Any:
            key = self.key

            class _Timeseries:
                def get_range(self, **kwargs: Any) -> Any:
                    raise OSError(f"HTTP 401 unauthorized for key={key}")

            return _Timeseries()

    import sys

    monkeypatch.setitem(sys.modules, "databento", SimpleNamespace(Historical=_ExplodingHistorical))
    with pytest.raises(RuntimeError, match="Databento download failed") as exc_info:
        download_databento_dbn(
            dataset="GLBX.MDP3",
            symbols="MGC.v.0",
            schema="ohlcv-1h",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
            output_path=out,
            api_key=secret,
        )
    assert secret not in str(exc_info.value)


def test_ingest_databento_respects_live_mode_block_and_cli_fail_closed(tmp_path: Path) -> None:
    dbn_file = tmp_path / "missing.dbn.zst"
    with pytest.raises(LiveTradingDisabledError):
        ingest_databento_dbn(
            dbn_path=dbn_file,
            catalog_path=tmp_path / "cat",
            mode=TradingMode.LIVE,
        )

    assert cli.main(["ingest-databento", "--dbn-file", str(dbn_file)]) == 1
    assert cli.main(["ingest-databento"]) == 1
