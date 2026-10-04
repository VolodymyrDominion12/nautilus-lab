"""Binance public data archive (data.binance.vision). No API keys, research only.

Why the archive and not REST for history (docs/34, B3):

* every file ships with a `.CHECKSUM` (SHA256): a download is either byte-exact or
  rejected, which REST pagination cannot promise;
* monthly files are immutable, so a local cache makes a re-run download nothing —
  that cache *is* the incremental ingest;
* no request weight, no 429/418 bans, and no HTTP 451 for some cloud regions on
  `fapi.binance.com`;
* symbols that were delisted stay in the archive (WAVESUSDT 2019-01..2024-06), which
  is what a survivorship-free universe needs.

Layout, as Binance publishes it:
`data/{spot|futures/um}/{monthly|daily}/{dataset}/{SYMBOL}/[{interval}/]{SYMBOL}-...zip`.
Monthly files cover closed months; the current month exists only as daily files.

Two format traps are handled here, not left to callers:

* spot timestamps from 2025-01-01 on are **microseconds**, older ones and all futures
  files are milliseconds — told apart by magnitude;
* newer futures CSVs carry a header row, older ones do not.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import time
import zipfile
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.errors import DomainError, MarketDataError
from nautilus_lab.domain.funding import FundingSnapshot
from nautilus_lab.domain.premium_index import PremiumIndexBar
from nautilus_lab.infrastructure.binance_klines import parse_binance_kline

ARCHIVE_BASE_URL = "https://data.binance.vision"
LISTING_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_HTTP_TIMEOUT_SECONDS = 60
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
#: Any epoch timestamp at or above this is in microseconds (ms values are ~1.7e12).
_MICROSECONDS_THRESHOLD = 10**14

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class ChecksumMismatchError(DomainError):
    """A downloaded archive file does not match its published SHA256."""


class Market(StrEnum):
    SPOT = "spot"
    USDM = "um"

    @property
    def path(self) -> str:
        return "spot" if self is Market.SPOT else "futures/um"


class Dataset(StrEnum):
    KLINES = "klines"
    FUNDING_RATE = "fundingRate"
    PREMIUM_INDEX_KLINES = "premiumIndexKlines"
    MARK_PRICE_KLINES = "markPriceKlines"
    INDEX_PRICE_KLINES = "indexPriceKlines"

    @property
    def has_interval(self) -> bool:
        return self is not Dataset.FUNDING_RATE


# --- transport ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HttpBytes:
    status: int
    body: bytes


Fetch = Callable[[str], HttpBytes]


def urllib_fetch(url: str) -> HttpBytes:
    """GET a URL; HTTP errors come back as a status instead of an exception."""
    request = Request(url, headers={"User-Agent": "nautilus-lab/research"})  # noqa: S310
    try:
        with urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:  # noqa: S310
            return HttpBytes(status=int(response.status), body=response.read())
    except HTTPError as exc:
        return HttpBytes(status=int(exc.code), body=b"")


class RetryingFetch:
    """Retries transient failures with exponential backoff; 404 is an answer, not a fault."""

    def __init__(
        self,
        fetch: Fetch = urllib_fetch,
        *,
        max_attempts: int = 5,
        base_delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._fetch = fetch
        self._max_attempts = max_attempts
        self._base_delay = base_delay_seconds
        self._sleep = sleep

    def __call__(self, url: str) -> HttpBytes:
        last: HttpBytes | None = None
        for attempt in range(self._max_attempts):
            try:
                result = self._fetch(url)
            except (URLError, TimeoutError, ConnectionError):
                result = HttpBytes(status=0, body=b"")
            if result.status != 0 and result.status not in _RETRYABLE_STATUSES:
                return result
            last = result
            if attempt + 1 < self._max_attempts:
                self._sleep(min(60.0, self._base_delay * 2**attempt))
        raise MarketDataError(
            f"archive request failed after {self._max_attempts} attempts "
            f"(last status {last.status if last else 'n/a'}): {url}"
        )


# --- listing --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Listing:
    keys: tuple[str, ...]
    prefixes: tuple[str, ...]


def parse_listing(xml_body: bytes) -> tuple[Listing, str | None]:
    """One S3 ListObjects page -> (keys and common prefixes, next marker or None)."""
    root = ElementTree.fromstring(xml_body)  # noqa: S314 — fixed public S3 endpoint
    keys = tuple((node.findtext(f"{_S3_NS}Key") or "") for node in root.iter(f"{_S3_NS}Contents"))
    prefixes = tuple(
        (node.findtext(f"{_S3_NS}Prefix") or "") for node in root.iter(f"{_S3_NS}CommonPrefixes")
    )
    truncated = (root.findtext(f"{_S3_NS}IsTruncated") or "").strip().lower() == "true"
    if not truncated:
        return Listing(keys=keys, prefixes=prefixes), None
    marker = root.findtext(f"{_S3_NS}NextMarker") or (keys[-1] if keys else None)
    if marker is None and prefixes:
        marker = prefixes[-1]
    return Listing(keys=keys, prefixes=prefixes), marker


# --- archive client ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArchiveFile:
    key: str
    #: First day the file covers (UTC); the 1st for monthly files.
    day: date
    monthly: bool


class BinanceVisionArchive:
    """Lists, downloads (SHA256-verified) and caches archive files."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        fetch: Fetch | None = None,
        max_workers: int = 8,
    ) -> None:
        self._cache = cache_dir.expanduser().resolve()
        self._fetch = fetch or RetryingFetch()
        self._max_workers = max(1, max_workers)
        #: Files served from the cache vs downloaded, for the run report.
        self.cache_hits = 0
        self.downloads = 0

    @property
    def cache_dir(self) -> Path:
        return self._cache

    # listing

    def list_prefix(self, prefix: str) -> Listing:
        keys: list[str] = []
        prefixes: list[str] = []
        marker: str | None = None
        while True:
            params = {"delimiter": "/", "prefix": prefix}
            if marker:
                params["marker"] = marker
            response = self._fetch(f"{LISTING_URL}?{urlencode(params)}")
            if response.status != 200:
                raise MarketDataError(f"archive listing failed ({response.status}) for {prefix}")
            page, marker = parse_listing(response.body)
            keys.extend(page.keys)
            prefixes.extend(page.prefixes)
            if marker is None:
                return Listing(keys=tuple(keys), prefixes=tuple(prefixes))

    def list_symbols(self, market: Market, dataset: Dataset = Dataset.KLINES) -> list[str]:
        """Every symbol the archive holds for a dataset, delisted ones included."""
        listing = self.list_prefix(f"data/{market.path}/monthly/{dataset.value}/")
        return sorted(item.rstrip("/").rsplit("/", 1)[-1] for item in listing.prefixes)

    def files_for(
        self,
        *,
        market: Market,
        dataset: Dataset,
        symbol: str,
        interval: str | None,
        start: datetime,
        end: datetime,
    ) -> list[ArchiveFile]:
        """Monthly files for closed months in the window, daily files for the rest."""
        if dataset.has_interval and not interval:
            raise ValueError(f"{dataset.value} needs an interval")
        base = f"{symbol}/{interval}/" if dataset.has_interval else f"{symbol}/"
        monthly_prefix = f"data/{market.path}/monthly/{dataset.value}/{base}"
        monthly = _zip_files(self.list_prefix(monthly_prefix).keys, monthly=True)
        covered = {(item.day.year, item.day.month) for item in monthly}
        selected = [item for item in monthly if _month_overlaps(item.day, start, end)]
        for year, month in months_in_window(start, end):
            if (year, month) in covered:
                continue
            stem = f"{symbol}-{interval}" if dataset.has_interval else f"{symbol}-{dataset.value}"
            daily_prefix = (
                f"data/{market.path}/daily/{dataset.value}/{base}{stem}-{year:04d}-{month:02d}-"
            )
            daily = _zip_files(self.list_prefix(daily_prefix).keys, monthly=False)
            selected.extend(item for item in daily if _day_overlaps(item.day, start, end))
        return sorted(selected, key=lambda item: (item.day, not item.monthly))

    # download

    def read_csv(self, key: str) -> list[list[str]]:
        """Rows of the single CSV inside a verified archive file (header kept)."""
        payload = self._verified_bytes(key)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [name for name in archive.namelist() if name.endswith(".csv")]
            if len(names) != 1:
                raise MarketDataError(f"{key}: expected one CSV inside, found {names}")
            text = archive.read(names[0]).decode("utf-8")
        return [row for row in csv.reader(io.StringIO(text)) if row]

    def read_many(self, keys: Sequence[str]) -> list[list[list[str]]]:
        """`read_csv` for many keys, downloaded concurrently, results in input order."""
        if not keys:
            return []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            return list(pool.map(self.read_csv, keys))

    def _verified_bytes(self, key: str) -> bytes:
        target = self._cache / key
        checksum_path = target.with_name(target.name + ".CHECKSUM")
        if target.exists() and checksum_path.exists():
            payload = target.read_bytes()
            if _sha256(payload) == _expected_sha(checksum_path.read_text(), key):
                self.cache_hits += 1
                return payload
        payload = self._download(f"{ARCHIVE_BASE_URL}/{key}", key)
        checksum = self._download(f"{ARCHIVE_BASE_URL}/{key}.CHECKSUM", f"{key}.CHECKSUM")
        expected = _expected_sha(checksum.decode("utf-8"), key)
        actual = _sha256(payload)
        if actual != expected:
            raise ChecksumMismatchError(f"{key}: sha256 {actual} != published {expected}")
        _atomic_write(target, payload)
        _atomic_write(checksum_path, checksum)
        self.downloads += 1
        return payload

    def _download(self, url: str, key: str) -> bytes:
        response = self._fetch(url)
        if response.status != 200:
            raise MarketDataError(f"archive download failed ({response.status}): {key}")
        return response.body


# --- parsing --------------------------------------------------------------------


def epoch_ms(raw: str | int) -> int:
    """Epoch milliseconds from an archive timestamp in ms or µs (spot 2025+ is µs)."""
    value = int(str(raw).strip())
    return value // 1000 if value >= _MICROSECONDS_THRESHOLD else value


def data_rows(rows: Iterable[list[str]]) -> list[list[str]]:
    """Rows without the header line that newer futures files carry."""
    out = list(rows)
    if out and not out[0][0].strip().lstrip("-").isdigit():
        return out[1:]
    return out


@dataclass(frozen=True, slots=True)
class ParsedKlines:
    bars: list[OhlcvBar]
    #: Bars whose span is shorter than the interval: the last candle before a delisting
    #: (MATICUSDT spot closed 2024-09-10 02:59:59 inside a "1d" file). Never stored as a
    #: full bar; counted so the report can say so.
    partial: int


def parse_kline_rows(
    rows: Iterable[list[str]], *, interval: str, instrument_id: str
) -> ParsedKlines:
    """Archive kline rows -> closed, full-length bars keyed by close time."""
    span_ms = INTERVAL_MS.get(interval)
    if span_ms is None:
        raise ValueError(f"unsupported archive interval {interval!r}")
    bars: list[OhlcvBar] = []
    partial = 0
    for row in data_rows(rows):
        if len(row) < 7:
            raise MarketDataError(f"kline row has {len(row)} fields, expected >= 7: {row}")
        open_ms = epoch_ms(row[0])
        close_ms = epoch_ms(row[6])
        if close_ms + 1 - open_ms != span_ms:
            partial += 1
            continue
        normalised: list[object] = [open_ms, *row[1:6], close_ms, *row[7:]]
        bars.append(parse_binance_kline(normalised, instrument_id=instrument_id))
    return ParsedKlines(bars=bars, partial=partial)


def parse_premium_rows(
    rows: Iterable[list[str]], *, symbol: str, interval: str
) -> list[PremiumIndexBar]:
    """Premium index kline rows -> bars keyed by close time (same rule as REST)."""
    out: list[PremiumIndexBar] = []
    for row in data_rows(rows):
        close_ms = epoch_ms(row[6])
        out.append(
            PremiumIndexBar(
                symbol=symbol,
                interval=interval,
                ts_utc=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
            )
        )
    return out


def parse_hourly_opens(rows: Iterable[list[str]]) -> dict[datetime, Decimal]:
    """1h mark/index kline rows -> open price per open hour (the settlement join)."""
    out: dict[datetime, Decimal] = {}
    for row in data_rows(rows):
        try:
            price = Decimal(row[1])
        except InvalidOperation:
            continue
        if price.is_finite() and price > 0:
            out[datetime.fromtimestamp(epoch_ms(row[0]) / 1000, tz=UTC)] = price
    return out


def parse_funding_rows(
    rows: Sequence[list[str]],
    *,
    symbol: str,
    marks: dict[datetime, Decimal] | None = None,
    indexes: dict[datetime, Decimal] | None = None,
) -> list[FundingSnapshot]:
    """`fundingRate` archive rows -> settlements.

    The file is `calc_time,funding_interval_hours,last_funding_rate`. Columns are
    found by header name when there is one, so a reordered file fails loudly instead
    of reading the interval as the rate.
    """
    if not rows:
        return []
    time_col, rate_col = 0, 2
    body: Sequence[list[str]] = rows
    header = [cell.strip().lower() for cell in rows[0]]
    if header and not header[0].lstrip("-").isdigit():
        try:
            time_col = next(i for i, name in enumerate(header) if "time" in name)
            rate_col = next(i for i, name in enumerate(header) if "rate" in name)
        except StopIteration as exc:
            raise MarketDataError(f"unexpected fundingRate header: {rows[0]}") from exc
        body = rows[1:]
    out: list[FundingSnapshot] = []
    for row in body:
        ts = datetime.fromtimestamp(epoch_ms(row[time_col]) / 1000, tz=UTC)
        hour = ts.replace(minute=0, second=0, microsecond=0)
        out.append(
            FundingSnapshot(
                instrument=symbol,
                funding_rate=Decimal(row[rate_col]),
                mark_price=(marks or {}).get(hour),
                index_price=(indexes or {}).get(hour),
                ts_utc=ts,
            )
        )
    return out


# --- helpers ----------------------------------------------------------------------


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _expected_sha(checksum_text: str, key: str) -> str:
    parts = checksum_text.strip().split()
    if not parts or len(parts[0]) != 64:
        raise ChecksumMismatchError(f"{key}: unreadable CHECKSUM file {checksum_text[:80]!r}")
    return parts[0].lower()


def _atomic_write(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, target)


def _zip_files(keys: Iterable[str], *, monthly: bool) -> list[ArchiveFile]:
    files: list[ArchiveFile] = []
    for key in keys:
        if not key.endswith(".zip"):
            continue
        stem = key.rsplit("/", 1)[-1].removesuffix(".zip")
        parts = stem.split("-")
        try:
            if monthly:
                day = date(int(parts[-2]), int(parts[-1]), 1)
            else:
                day = date(int(parts[-3]), int(parts[-2]), int(parts[-1]))
        except (ValueError, IndexError):
            continue
        files.append(ArchiveFile(key=key, day=day, monthly=monthly))
    return files


def months_in_window(start: datetime, end: datetime) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    year, month = start.year, start.month
    last = end - timedelta(microseconds=1)
    while (year, month) <= (last.year, last.month):
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _month_overlaps(first_day: date, start: datetime, end: datetime) -> bool:
    month_start = datetime(first_day.year, first_day.month, 1, tzinfo=UTC)
    if first_day.month == 12:
        month_end = datetime(first_day.year + 1, 1, 1, tzinfo=UTC)
    else:
        month_end = datetime(first_day.year, first_day.month + 1, 1, tzinfo=UTC)
    return month_start < end and month_end > start


def _day_overlaps(day: date, start: datetime, end: datetime) -> bool:
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return day_start < end and day_start + timedelta(days=1) > start


__all__ = [
    "ARCHIVE_BASE_URL",
    "INTERVAL_MS",
    "LISTING_URL",
    "ArchiveFile",
    "BinanceVisionArchive",
    "ChecksumMismatchError",
    "Dataset",
    "HttpBytes",
    "Listing",
    "Market",
    "ParsedKlines",
    "RetryingFetch",
    "data_rows",
    "epoch_ms",
    "months_in_window",
    "parse_funding_rows",
    "parse_hourly_opens",
    "parse_kline_rows",
    "parse_listing",
    "parse_premium_rows",
]
