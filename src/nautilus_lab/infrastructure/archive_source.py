"""`ArchiveSource` over data.binance.vision, plus the stores the archive ingest writes."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from nautilus_lab.application.ingest_archive import ArchiveFetch
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.data_quality import QualityReport
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.premium_index import PremiumIndexBar
from nautilus_lab.infrastructure.binance_vision import (
    ArchiveFile,
    BinanceVisionArchive,
    Dataset,
    Market,
    months_in_window,
    parse_funding_rows,
    parse_hourly_opens,
    parse_kline_rows,
    parse_premium_rows,
)
from nautilus_lab.infrastructure.nautilus.instrument import infer_precision, register_instrument


class BinanceVisionSource:
    """Reads one series from the archive and reports how much of the window it covered."""

    def __init__(self, archive: BinanceVisionArchive) -> None:
        self._archive = archive

    def klines(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
    ) -> tuple[list[OhlcvBar], ArchiveFetch]:
        files = self._archive.files_for(
            market=Market(market),
            dataset=Dataset.KLINES,
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
        )
        by_ts: dict[datetime, OhlcvBar] = {}
        partial = 0
        for rows in self._archive.read_many([item.key for item in files]):
            parsed = parse_kline_rows(rows, interval=interval, instrument_id=instrument_id)
            partial += parsed.partial
            for bar in parsed.bars:
                by_ts[bar.ts_utc] = bar  # a daily file overlapping a monthly one: same bar
        bars = [by_ts[key] for key in sorted(by_ts)]
        return bars, _fetch_summary(files, start, end, partial)

    def funding(
        self, *, symbol: str, start: datetime, end: datetime, with_prices: bool
    ) -> tuple[list[FundingSnapshot], ArchiveFetch]:
        files = self._archive.files_for(
            market=Market.USDM,
            dataset=Dataset.FUNDING_RATE,
            symbol=symbol,
            interval=None,
            start=start,
            end=end,
        )
        marks: dict[datetime, Decimal] = {}
        indexes: dict[datetime, Decimal] = {}
        if with_prices and files:
            marks = self._hourly(Dataset.MARK_PRICE_KLINES, symbol, start, end)
            indexes = self._hourly(Dataset.INDEX_PRICE_KLINES, symbol, start, end)
        snapshots: list[FundingSnapshot] = []
        for rows in self._archive.read_many([item.key for item in files]):
            snapshots.extend(parse_funding_rows(rows, symbol=symbol, marks=marks, indexes=indexes))
        unique = {item.ts_utc: item for item in snapshots}
        ordered = [unique[key] for key in sorted(unique)]
        return ordered, _fetch_summary(files, start, end, 0)

    def premium_index(
        self, *, symbol: str, interval: str, start: datetime, end: datetime
    ) -> tuple[list[PremiumIndexBar], ArchiveFetch]:
        files = self._archive.files_for(
            market=Market.USDM,
            dataset=Dataset.PREMIUM_INDEX_KLINES,
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
        )
        by_ts: dict[datetime, PremiumIndexBar] = {}
        for rows in self._archive.read_many([item.key for item in files]):
            for bar in parse_premium_rows(rows, symbol=symbol, interval=interval):
                by_ts[bar.ts_utc] = bar
        return [by_ts[key] for key in sorted(by_ts)], _fetch_summary(files, start, end, 0)

    def _hourly(
        self, dataset: Dataset, symbol: str, start: datetime, end: datetime
    ) -> dict[datetime, Decimal]:
        files = self._archive.files_for(
            market=Market.USDM,
            dataset=dataset,
            symbol=symbol,
            interval="1h",
            start=start,
            end=end,
        )
        prices: dict[datetime, Decimal] = {}
        for rows in self._archive.read_many([item.key for item in files]):
            prices.update(parse_hourly_opens(rows))
        return prices


def _fetch_summary(
    files: Sequence[ArchiveFile], start: datetime, end: datetime, partial: int
) -> ArchiveFetch:
    """Months of the window with no file at all, from the first covered month on.

    Months before the first file are a listing date, not a hole; months after it
    without a file are a hole and are reported.
    """
    covered = {(item.day.year, item.day.month) for item in files}
    missing: list[str] = []
    if covered:
        first = min(covered)
        for year, month in months_in_window(start, end):
            if (year, month) >= first and (year, month) not in covered:
                missing.append(f"{year:04d}-{month:02d}")
    return ArchiveFetch(files=len(files), missing_months=tuple(missing), partial_dropped=partial)


def ensure_instrument(instrument_id: str, bars: Sequence[OhlcvBar]) -> None:
    """Register a spec derived from the series' own decimals (no-op for curated ids)."""
    prices = [value for bar in bars for value in (bar.open, bar.high, bar.low, bar.close)]
    register_instrument(
        instrument_id,
        price_precision=infer_precision(prices),
        size_precision=infer_precision(bar.volume for bar in bars),
        source="binance-vision:derived-from-history",
    )


class JsonQualityStore:
    """`<catalog>/quality.json`: one QC report per bar type, merged on every write."""

    _lock = threading.Lock()

    def __init__(self, catalog_path: Path) -> None:
        self._path = catalog_path.expanduser().resolve() / "quality.json"

    @property
    def path(self) -> Path:
        return self._path

    def write(self, key: str, report: QualityReport) -> None:
        with self._lock:
            current: dict[str, object] = {}
            if self._path.exists():
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    current = loaded
            current[key] = quality_to_dict(report)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_name(self._path.name + ".tmp")
            temporary.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self._path)

    def load(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        loaded = json.loads(self._path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}


#: Lists in the stored report are capped: a dead series can have thousands of gaps,
#: and the panel needs the count and the worst few, not a megabyte of JSON.
_MAX_LISTED = 20


def quality_to_dict(report: QualityReport) -> dict[str, object]:
    return {
        "status": report.status().value,
        "bars": report.bars,
        "first": report.first.isoformat() if report.first else None,
        "last": report.last.isoformat() if report.last else None,
        "expected_bars": report.expected_bars,
        "missing_bars": report.missing_bars,
        "gaps": [
            {
                "after": gap.after.isoformat(),
                "before": gap.before.isoformat(),
                "missing_bars": gap.missing_bars,
            }
            for gap in sorted(report.gaps, key=lambda g: -g.missing_bars)[:_MAX_LISTED]
        ],
        "gap_count": len(report.gaps),
        "zero_volume": report.zero_volume,
        "extreme_moves": [
            {"ts": jump.ts_utc.isoformat(), "ratio": str(jump.ratio)}
            for jump in report.extreme_moves[:_MAX_LISTED]
        ],
        "extreme_move_count": len(report.extreme_moves),
        "relisting_suspects": [
            {"ts": jump.ts_utc.isoformat(), "ratio": str(jump.ratio)}
            for jump in report.relisting_suspects
        ],
        "partial_dropped": report.partial_dropped,
    }
