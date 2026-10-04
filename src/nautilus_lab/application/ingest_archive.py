"""Ingest history from the Binance public archive into the lab's catalogs (docs/34, P1).

The archive replaces REST for *history*: SHA256-verified files, an immutable monthly
cache that makes re-runs incremental, and delisted symbols that REST no longer
serves. REST stays for the last days the archive has not published yet.

Every bar series that is written is also quality-checked (`domain.data_quality`) and
its report stored beside the catalog, so "the ingest finished" and "the data is fit
for a backtest" are two separate, visible facts.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.data_quality import QualityReport, QualityStatus, check_bars
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.ports import BarCatalog, FundingCatalog, TakerFlowCatalog
from nautilus_lab.domain.premium_index import PremiumIndexBar
from nautilus_lab.domain.trading_mode import TradingMode

INTERVALS: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


@dataclass(frozen=True, slots=True)
class ArchiveFetch:
    """What the archive returned for one series and how much of the window it covered."""

    files: int
    #: Calendar months in the window for which the archive had no file at all.
    missing_months: tuple[str, ...] = ()
    partial_dropped: int = 0


class ArchiveSource(Protocol):
    def klines(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
    ) -> tuple[list[OhlcvBar], ArchiveFetch]: ...

    def funding(
        self, *, symbol: str, start: datetime, end: datetime, with_prices: bool
    ) -> tuple[list[FundingSnapshot], ArchiveFetch]: ...

    def premium_index(
        self, *, symbol: str, interval: str, start: datetime, end: datetime
    ) -> tuple[list[PremiumIndexBar], ArchiveFetch]: ...


class PremiumIndexStore(Protocol):
    def write(self, bars: Sequence[PremiumIndexBar], *, symbol: str, interval: str) -> int: ...


class QualityStore(Protocol):
    def write(self, key: str, report: QualityReport) -> None: ...


#: Registers a derived instrument spec from the bars about to be written.
EnsureInstrument = Callable[[str, Sequence[OhlcvBar]], None]


@dataclass(frozen=True, slots=True)
class ArchiveSeriesReport:
    symbol: str
    series: str
    rows_written: int
    first_ts: datetime | None
    last_ts: datetime | None
    files: int
    requested_start: datetime
    missing_months: tuple[str, ...] = ()
    partial_dropped: int = 0
    quality: QualityStatus | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def late_start_days(self) -> int:
        if self.first_ts is None:
            return 0
        return max(0, (self.first_ts - self.requested_start).days)

    def summary_line(self) -> str:
        first = self.first_ts.isoformat() if self.first_ts else "-"
        last = self.last_ts.isoformat() if self.last_ts else "-"
        parts = [
            f"symbol={self.symbol}",
            f"series={self.series}",
            f"rows={self.rows_written}",
            f"files={self.files}",
            f"first={first}",
            f"last={last}",
        ]
        if self.partial_dropped:
            parts.append(f"partial_dropped={self.partial_dropped}")
        if self.missing_months:
            parts.append(f"missing_months={len(self.missing_months)}")
        if self.quality is not None:
            parts.append(f"quality={self.quality.value}")
        return " ".join(parts)


class IngestArchive:
    """Archive -> catalogs, one series at a time. Research mode only."""

    def __init__(
        self,
        source: ArchiveSource,
        *,
        mode: TradingMode,
        bars: BarCatalog | None = None,
        taker_flow: TakerFlowCatalog | None = None,
        funding: FundingCatalog | None = None,
        premium: PremiumIndexStore | None = None,
        quality: QualityStore | None = None,
        ensure_instrument: EnsureInstrument | None = None,
    ) -> None:
        require_simulated_mode(mode)
        self._source = source
        self._bars = bars
        self._taker_flow = taker_flow
        self._funding = funding
        self._premium = premium
        self._quality = quality
        self._ensure_instrument = ensure_instrument

    def klines(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        instrument_id: str,
        bar_type: str,
    ) -> ArchiveSeriesReport:
        if self._bars is None:
            raise ValueError("no bar catalog configured")
        step = INTERVALS.get(interval)
        if step is None:
            raise ValueError(f"unsupported interval {interval!r}")
        _check_window(start, end)
        bars, fetched = self._source.klines(
            market=market,
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            instrument_id=instrument_id,
        )
        bars = [bar for bar in bars if start <= bar.ts_utc < end]
        report = check_bars(bars, interval=step, partial_dropped=fetched.partial_dropped)
        if self._quality is not None:
            self._quality.write(bar_type, report)
        if not bars:
            return ArchiveSeriesReport(
                symbol=symbol,
                series=f"{market}:klines:{interval}",
                rows_written=0,
                first_ts=None,
                last_ts=None,
                files=fetched.files,
                requested_start=start,
                missing_months=fetched.missing_months,
                partial_dropped=fetched.partial_dropped,
                quality=report.status(),
                notes=("no bars in the archive for this window",),
            )
        if self._ensure_instrument is not None:
            self._ensure_instrument(instrument_id, bars)
        written = self._bars.write(bars, bar_type=bar_type, instrument_id=instrument_id)
        if self._taker_flow is not None and any(
            bar.taker_buy_base_volume is not None for bar in bars
        ):
            flow_symbol = symbol if market == "spot" else f"{symbol}-PERP"
            self._taker_flow.write(bars, symbol=flow_symbol, interval=interval)
        return ArchiveSeriesReport(
            symbol=symbol,
            series=f"{market}:klines:{interval}",
            rows_written=written,
            first_ts=bars[0].ts_utc,
            last_ts=bars[-1].ts_utc,
            files=fetched.files,
            requested_start=start,
            missing_months=fetched.missing_months,
            partial_dropped=fetched.partial_dropped,
            quality=report.status(),
        )

    def funding(
        self, *, symbol: str, start: datetime, end: datetime, with_prices: bool = True
    ) -> ArchiveSeriesReport:
        if self._funding is None:
            raise ValueError("no funding catalog configured")
        _check_window(start, end)
        snapshots, fetched = self._source.funding(
            symbol=symbol, start=start, end=end, with_prices=with_prices
        )
        snapshots = sorted(
            (item for item in snapshots if start <= item.ts_utc < end),
            key=lambda item: item.ts_utc,
        )
        if not snapshots:
            raise CatalogEmptyError(
                f"no archived funding for {symbol} in [{start.isoformat()}, {end.isoformat()})"
            )
        self._funding.write(snapshots, symbol=symbol)
        missing_mark = sum(1 for item in snapshots if item.mark_price is None)
        notes = (f"missing_mark_price={missing_mark}",) if with_prices and missing_mark else ()
        return ArchiveSeriesReport(
            symbol=symbol,
            series="um:funding",
            rows_written=len(snapshots),
            first_ts=snapshots[0].ts_utc,
            last_ts=snapshots[-1].ts_utc,
            files=fetched.files,
            requested_start=start,
            missing_months=fetched.missing_months,
            notes=notes,
        )

    def premium_index(
        self, *, symbol: str, interval: str, start: datetime, end: datetime
    ) -> ArchiveSeriesReport:
        if self._premium is None:
            raise ValueError("no premium index store configured")
        _check_window(start, end)
        bars, fetched = self._source.premium_index(
            symbol=symbol, interval=interval, start=start, end=end
        )
        bars = [bar for bar in bars if start <= bar.ts_utc < end]
        if not bars:
            raise CatalogEmptyError(
                f"no archived premium index for {symbol} {interval} "
                f"in [{start.isoformat()}, {end.isoformat()})"
            )
        written = self._premium.write(bars, symbol=symbol, interval=interval)
        return ArchiveSeriesReport(
            symbol=symbol,
            series=f"um:premium_index:{interval}",
            rows_written=written,
            first_ts=bars[0].ts_utc,
            last_ts=bars[-1].ts_utc,
            files=fetched.files,
            requested_start=start,
            missing_months=fetched.missing_months,
        )


def _check_window(start: datetime, end: datetime) -> None:
    if start >= end:
        raise ValueError("ingest start must be before end")
