from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.application.ingest_archive import ArchiveFetch, IngestArchive
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.data_quality import QualityReport, QualityStatus
from nautilus_lab.domain.errors import CatalogEmptyError, LiveTradingDisabledError
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.premium_index import PremiumIndexBar
from nautilus_lab.domain.trading_mode import TradingMode

_START = datetime(2020, 1, 1, tzinfo=UTC)
_DAY = timedelta(days=1)


def _bar(day: int, *, taker: str | None = "1") -> OhlcvBar:
    return OhlcvBar(
        instrument_id="SOL/USDT.SIM",
        ts_utc=_START + day * _DAY + timedelta(hours=23, minutes=59, seconds=59),
        open=Decimal("1.2345"),
        high=Decimal("1.3"),
        low=Decimal("1.2"),
        close=Decimal("1.25"),
        volume=Decimal("10"),
        taker_buy_base_volume=None if taker is None else Decimal(taker),
    )


class _Source:
    def __init__(self, bars: list[OhlcvBar], funding: list[FundingSnapshot] | None = None) -> None:
        self._bars = bars
        self._funding = funding or []
        self.calls: list[str] = []

    def klines(self, **kwargs: object) -> tuple[list[OhlcvBar], ArchiveFetch]:
        self.calls.append(f"klines:{kwargs['market']}")
        return self._bars, ArchiveFetch(files=3, missing_months=("2020-02",), partial_dropped=1)

    def funding(self, **kwargs: object) -> tuple[list[FundingSnapshot], ArchiveFetch]:
        self.calls.append("funding")
        return self._funding, ArchiveFetch(files=1)

    def premium_index(self, **kwargs: object) -> tuple[list[PremiumIndexBar], ArchiveFetch]:
        return [], ArchiveFetch(files=0)


class _Bars:
    def __init__(self) -> None:
        self.written: list[tuple[str, str, int]] = []

    def write(self, bars: Sequence[OhlcvBar], *, bar_type: str, instrument_id: str) -> int:
        self.written.append((bar_type, instrument_id, len(bars)))
        return len(bars)

    def load(self, **kwargs: object) -> list[OhlcvBar]:
        return []


class _Flow:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    def write(self, bars: Sequence[OhlcvBar], *, symbol: str, interval: str) -> int:
        self.symbols.append(f"{symbol}:{interval}")
        return len(bars)


class _Funding:
    def __init__(self) -> None:
        self.rows: list[FundingSnapshot] = []

    def write(self, snapshots: Sequence[FundingSnapshot], *, symbol: str) -> int:
        self.rows = list(snapshots)
        return len(snapshots)


class _Quality:
    def __init__(self) -> None:
        self.reports: dict[str, QualityReport] = {}

    def write(self, key: str, report: QualityReport) -> None:
        self.reports[key] = report


def _use_case(source: _Source, **stores: object) -> IngestArchive:
    return IngestArchive(source, mode=TradingMode.RESEARCH, **stores)  # type: ignore[arg-type]


def test_klines_are_written_with_flow_quality_and_a_registered_instrument() -> None:
    bars, flow, quality = _Bars(), _Flow(), _Quality()
    registered: list[tuple[str, int]] = []
    use_case = _use_case(
        _Source([_bar(day) for day in range(5)]),
        bars=bars,
        taker_flow=flow,
        quality=quality,
        ensure_instrument=lambda iid, items: registered.append((iid, len(items))),
    )
    report = use_case.klines(
        market="spot",
        symbol="SOLUSDT",
        interval="1d",
        start=_START,
        end=_START + 10 * _DAY,
        instrument_id="SOL/USDT.SIM",
        bar_type="SOL/USDT.SIM-1-DAY-LAST-EXTERNAL",
    )
    assert report.rows_written == 5
    assert report.missing_months == ("2020-02",)
    assert report.partial_dropped == 1
    assert report.quality is QualityStatus.WARN  # the dropped partial bar is worth a look
    assert registered == [("SOL/USDT.SIM", 5)], "the spec is registered before the write"
    assert bars.written == [("SOL/USDT.SIM-1-DAY-LAST-EXTERNAL", "SOL/USDT.SIM", 5)]
    assert flow.symbols == ["SOLUSDT:1d"]
    assert "SOL/USDT.SIM-1-DAY-LAST-EXTERNAL" in quality.reports
    assert "partial_dropped=1" in report.summary_line()


def test_perp_taker_flow_goes_under_the_perp_symbol() -> None:
    flow = _Flow()
    _use_case(_Source([_bar(0)]), bars=_Bars(), taker_flow=flow).klines(
        market="um",
        symbol="SOLUSDT",
        interval="1d",
        start=_START,
        end=_START + _DAY * 2,
        instrument_id="SOLUSDT-PERP.SIM",
        bar_type="SOLUSDT-PERP.SIM-1-DAY-LAST-EXTERNAL",
    )
    assert flow.symbols == ["SOLUSDT-PERP:1d"]


def test_bars_outside_the_window_are_not_written() -> None:
    bars = _Bars()
    _use_case(_Source([_bar(day) for day in range(10)]), bars=bars).klines(
        market="spot",
        symbol="SOLUSDT",
        interval="1d",
        start=_START + 2 * _DAY,
        end=_START + 5 * _DAY,
        instrument_id="SOL/USDT.SIM",
        bar_type="b",
    )
    assert bars.written[0][2] == 3


def test_an_empty_window_is_reported_not_written() -> None:
    bars, quality = _Bars(), _Quality()
    report = _use_case(_Source([]), bars=bars, quality=quality).klines(
        market="spot",
        symbol="SOLUSDT",
        interval="1d",
        start=_START,
        end=_START + _DAY,
        instrument_id="SOL/USDT.SIM",
        bar_type="b",
    )
    assert report.rows_written == 0
    assert report.quality is QualityStatus.FAIL
    assert bars.written == []


def test_funding_is_windowed_sorted_and_reports_a_late_start() -> None:
    def snap(days: int, mark: str | None) -> FundingSnapshot:
        return FundingSnapshot(
            instrument="BTCUSDT",
            funding_rate=Decimal("0.0001"),
            mark_price=None if mark is None else Decimal(mark),
            index_price=None,
            ts_utc=_START + days * _DAY,
        )

    store = _Funding()
    source = _Source([], funding=[snap(40, "1"), snap(30, None), snap(400, "1")])
    report = _use_case(source, funding=store).funding(
        symbol="BTCUSDT", start=_START, end=_START + 100 * _DAY
    )
    assert [item.ts_utc for item in store.rows] == [_START + 30 * _DAY, _START + 40 * _DAY]
    assert report.late_start_days == 30
    assert report.notes == ("missing_mark_price=1",)


def test_funding_with_nothing_archived_fails() -> None:
    with pytest.raises(CatalogEmptyError, match="no archived funding"):
        _use_case(_Source([]), funding=_Funding()).funding(
            symbol="BTCUSDT", start=_START, end=_START + _DAY
        )


def test_live_mode_is_refused() -> None:
    with pytest.raises(LiveTradingDisabledError):
        IngestArchive(_Source([]), mode=TradingMode.LIVE)


def test_unknown_interval_and_inverted_window_are_refused() -> None:
    use_case = _use_case(_Source([]), bars=_Bars())
    with pytest.raises(ValueError, match="unsupported interval"):
        use_case.klines(
            market="spot",
            symbol="X",
            interval="2h",
            start=_START,
            end=_START + _DAY,
            instrument_id="X",
            bar_type="b",
        )
    with pytest.raises(ValueError, match="start must be before end"):
        use_case.klines(
            market="spot",
            symbol="X",
            interval="1d",
            start=_START,
            end=_START,
            instrument_id="X",
            bar_type="b",
        )
