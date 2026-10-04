from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from nautilus_lab.domain.errors import MarketDataError
from nautilus_lab.infrastructure.binance_vision import (
    ARCHIVE_BASE_URL,
    LISTING_URL,
    BinanceVisionArchive,
    ChecksumMismatchError,
    Dataset,
    HttpBytes,
    Market,
    RetryingFetch,
    epoch_ms,
    months_in_window,
    parse_funding_rows,
    parse_hourly_opens,
    parse_kline_rows,
    parse_listing,
    parse_premium_rows,
)

_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
_DAY = 86_400_000
_T2020 = 1_577_836_800_000  # 2020-01-01T00:00Z


def _zip(csv_text: str, name: str = "x.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, csv_text)
    return buffer.getvalue()


def _listing_xml(
    keys: list[str], prefixes: list[str] | None = None, *, truncated: bool = False
) -> bytes:
    contents = "".join(f"<Contents><Key>{key}</Key></Contents>" for key in keys)
    common = "".join(
        f"<CommonPrefixes><Prefix>{item}</Prefix></CommonPrefixes>" for item in prefixes or []
    )
    flag = "true" if truncated else "false"
    return (
        f'<?xml version="1.0"?><ListBucketResult xmlns="{_NS}">'
        f"<IsTruncated>{flag}</IsTruncated>{contents}{common}</ListBucketResult>"
    ).encode()


class _FakeServer:
    """Serves listings by prefix and files by key; records every URL."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.listings: dict[str, list[bytes]] = {}
        self.calls: list[str] = []

    def add_file(self, key: str, payload: bytes, *, checksum: str | None = None) -> None:
        digest = checksum or hashlib.sha256(payload).hexdigest()
        self.files[key] = payload
        self.files[f"{key}.CHECKSUM"] = f"{digest}  {key.rsplit('/', 1)[-1]}\n".encode()

    def __call__(self, url: str) -> HttpBytes:
        self.calls.append(url)
        if url.startswith(LISTING_URL):
            query = parse_qs(urlparse(url).query)
            prefix = query["prefix"][0]
            pages = self.listings.get(prefix)
            if pages is None:
                keys = sorted(key for key in self.files if key.startswith(prefix))
                return HttpBytes(200, _listing_xml(keys))
            index = 0 if "marker" not in query else 1
            return HttpBytes(200, pages[index])
        key = url.removeprefix(f"{ARCHIVE_BASE_URL}/")
        if key in self.files:
            return HttpBytes(200, self.files[key])
        return HttpBytes(404, b"")

    def downloads(self) -> list[str]:
        return [url for url in self.calls if url.startswith(ARCHIVE_BASE_URL)]


def _kline(open_ms: int, span_ms: int = _DAY, *, close: str = "7200.00000000") -> list[str]:
    return [
        str(open_ms),
        "7195.24000000",
        "7255.00000000",
        "7175.15000000",
        close,
        "16792.38816500",
        str(open_ms + span_ms - 1),
        "121090130.83",
        "194009",
        "8946.95553500",
        "64532.73",
        "0",
    ]


# --- timestamps and headers ----------------------------------------------------------


def test_epoch_ms_reads_milliseconds_and_microseconds() -> None:
    assert epoch_ms("1577836800000") == 1_577_836_800_000
    # Spot files from 2025-01-01 on are in microseconds (binance-public-data README).
    assert epoch_ms("1735689600000000") == 1_735_689_600_000


def test_kline_rows_parse_with_and_without_a_header() -> None:
    header = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "count",
        "taker_buy_volume",
        "taker_buy_quote_volume",
        "ignore",
    ]
    rows = [_kline(_T2020), _kline(_T2020 + _DAY)]
    plain = parse_kline_rows(rows, interval="1d", instrument_id="BTC/USDT.SIM")
    with_header = parse_kline_rows([header, *rows], interval="1d", instrument_id="BTC/USDT.SIM")
    assert plain.bars == with_header.bars
    first = plain.bars[0]
    assert first.ts_utc == datetime(2020, 1, 1, 23, 59, 59, 999000, tzinfo=UTC)
    assert first.open == Decimal("7195.24000000")
    assert first.taker_buy_base_volume == Decimal("8946.95553500")


def test_microsecond_kline_rows_land_on_the_same_close_time() -> None:
    ms_row = _kline(1_735_689_600_000)
    us_row = [str(int(ms_row[0]) * 1000), *ms_row[1:6], f"{ms_row[6]}999", *ms_row[7:]]
    a = parse_kline_rows([ms_row], interval="1d", instrument_id="BTC/USDT.SIM").bars
    b = parse_kline_rows([us_row], interval="1d", instrument_id="BTC/USDT.SIM").bars
    assert a == b


def test_a_partial_last_candle_is_dropped_and_counted() -> None:
    # MATICUSDT spot: the last "1d" candle closed at 02:59:59, three hours in.
    rows = [_kline(_T2020), _kline(_T2020 + _DAY, span_ms=3 * 3_600_000)]
    parsed = parse_kline_rows(rows, interval="1d", instrument_id="MATIC/USDT.SIM")
    assert len(parsed.bars) == 1
    assert parsed.partial == 1


def test_short_kline_rows_fail_loudly() -> None:
    with pytest.raises(MarketDataError, match="fields"):
        parse_kline_rows([["1", "2", "3"]], interval="1d", instrument_id="BTC/USDT.SIM")


def test_funding_rows_use_header_names_and_join_prices_on_the_hour() -> None:
    rows = [
        ["calc_time", "funding_interval_hours", "last_funding_rate"],
        [str(_T2020), "8", "0.00010000"],
        [str(_T2020 + 8 * 3_600_000 + 7), "8", "-0.00002500"],
    ]
    hour0 = datetime(2020, 1, 1, tzinfo=UTC)
    snapshots = parse_funding_rows(
        rows, symbol="BTCUSDT", marks={hour0: Decimal("7200")}, indexes={hour0: Decimal("7195")}
    )
    assert [item.funding_rate for item in snapshots] == [Decimal("0.0001"), Decimal("-0.000025")]
    assert snapshots[0].mark_price == Decimal("7200")
    assert snapshots[0].index_price == Decimal("7195")
    # No price for 08:00 in the joins: unknown, not copied from another hour.
    assert snapshots[1].mark_price is None
    assert snapshots[1].ts_utc == datetime(2020, 1, 1, 8, 0, 0, 7000, tzinfo=UTC)


def test_funding_rows_with_an_unknown_header_are_refused() -> None:
    with pytest.raises(MarketDataError, match="fundingRate header"):
        parse_funding_rows([["a", "b"], ["1", "2"]], symbol="BTCUSDT")


def test_premium_and_hourly_rows() -> None:
    row = [str(_T2020), "-0.0001", "0.0002", "-0.0003", "0.00005", "0", str(_T2020 + 3_599_999)]
    (bar,) = parse_premium_rows([row], symbol="BTCUSDT", interval="1h")
    assert bar.ts_utc == datetime(2020, 1, 1, 0, 59, 59, 999000, tzinfo=UTC)
    assert bar.close == Decimal("0.00005")
    opens = parse_hourly_opens([["open_time", "open"], [str(_T2020), "7200.5"], [str(_T2020), "0"]])
    assert opens == {datetime(2020, 1, 1, tzinfo=UTC): Decimal("7200.5")}


# --- listing ------------------------------------------------------------------------


def test_listing_parses_keys_prefixes_and_the_next_marker() -> None:
    page, marker = parse_listing(_listing_xml(["a.zip", "b.zip"], ["p/"], truncated=True))
    assert page.keys == ("a.zip", "b.zip")
    assert page.prefixes == ("p/",)
    assert marker == "b.zip"
    _page, done = parse_listing(_listing_xml(["c.zip"]))
    assert done is None


def test_listing_follows_pagination(tmp_path: Path) -> None:
    server = _FakeServer()
    prefix = "data/spot/monthly/klines/"
    server.listings[prefix] = [
        _listing_xml([], [f"{prefix}AAAUSDT/"], truncated=True),
        _listing_xml([], [f"{prefix}WAVESUSDT/"]),
    ]
    archive = BinanceVisionArchive(tmp_path, fetch=server)
    assert archive.list_symbols(Market.SPOT) == ["AAAUSDT", "WAVESUSDT"]


def test_months_in_window_is_end_exclusive() -> None:
    assert months_in_window(
        datetime(2019, 11, 15, tzinfo=UTC), datetime(2020, 2, 1, tzinfo=UTC)
    ) == [(2019, 11), (2019, 12), (2020, 1)]


def test_files_for_uses_monthly_files_then_daily_for_the_open_month(tmp_path: Path) -> None:
    server = _FakeServer()
    monthly = "data/spot/monthly/klines/BTCUSDT/1d/"
    daily = "data/spot/daily/klines/BTCUSDT/1d/"
    for name in ("BTCUSDT-1d-2026-08.zip", "BTCUSDT-1d-2026-09.zip"):
        server.add_file(monthly + name, _zip(""))
    for name in ("BTCUSDT-1d-2026-10-01.zip", "BTCUSDT-1d-2026-10-02.zip"):
        server.add_file(daily + name, _zip(""))
    archive = BinanceVisionArchive(tmp_path, fetch=server)
    files = archive.files_for(
        market=Market.SPOT,
        dataset=Dataset.KLINES,
        symbol="BTCUSDT",
        interval="1d",
        start=datetime(2026, 9, 1, tzinfo=UTC),
        end=datetime(2026, 10, 3, tzinfo=UTC),
    )
    assert [(item.day, item.monthly) for item in files] == [
        (date(2026, 9, 1), True),
        (date(2026, 10, 1), False),
        (date(2026, 10, 2), False),
    ]


def test_funding_files_have_no_interval_directory(tmp_path: Path) -> None:
    server = _FakeServer()
    key = "data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2020-01.zip"
    server.add_file(key, _zip(""))
    files = BinanceVisionArchive(tmp_path, fetch=server).files_for(
        market=Market.USDM,
        dataset=Dataset.FUNDING_RATE,
        symbol="BTCUSDT",
        interval=None,
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 2, 1, tzinfo=UTC),
    )
    assert [item.key for item in files] == [key]


# --- download, checksum, cache -----------------------------------------------------------


def test_download_is_verified_then_served_from_the_cache(tmp_path: Path) -> None:
    server = _FakeServer()
    key = "data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip"
    server.add_file(key, _zip("1,2,3\n"))
    archive = BinanceVisionArchive(tmp_path, fetch=server)

    assert archive.read_csv(key) == [["1", "2", "3"]]
    assert archive.downloads == 1
    assert (tmp_path / key).exists()

    again = BinanceVisionArchive(tmp_path, fetch=server)
    assert again.read_csv(key) == [["1", "2", "3"]]
    assert again.cache_hits == 1
    assert len(server.downloads()) == 2, "a cached, verified file is never downloaded again"


def test_a_checksum_mismatch_is_refused_and_not_cached(tmp_path: Path) -> None:
    server = _FakeServer()
    key = "data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip"
    server.add_file(key, _zip("1,2,3\n"), checksum="0" * 64)
    archive = BinanceVisionArchive(tmp_path, fetch=server)
    with pytest.raises(ChecksumMismatchError):
        archive.read_csv(key)
    assert not (tmp_path / key).exists()


def test_a_corrupted_cache_file_is_downloaded_again(tmp_path: Path) -> None:
    server = _FakeServer()
    key = "data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2020-01.zip"
    server.add_file(key, _zip("1,2,3\n"))
    BinanceVisionArchive(tmp_path, fetch=server).read_csv(key)
    (tmp_path / key).write_bytes(b"truncated")

    archive = BinanceVisionArchive(tmp_path, fetch=server)
    assert archive.read_csv(key) == [["1", "2", "3"]]
    assert archive.downloads == 1


def test_a_missing_file_is_a_market_data_error(tmp_path: Path) -> None:
    archive = BinanceVisionArchive(tmp_path, fetch=_FakeServer())
    with pytest.raises(MarketDataError, match="404"):
        archive.read_csv("data/spot/monthly/klines/NOPE/1d/NOPE-1d-2020-01.zip")


def test_retrying_fetch_retries_transient_statuses_only() -> None:
    answers = [HttpBytes(503, b""), HttpBytes(200, b"ok")]
    sleeps: list[float] = []
    fetch = RetryingFetch(lambda _url: answers.pop(0), sleep=sleeps.append)
    assert fetch("u").body == b"ok"
    assert sleeps == [1.0]

    not_found = RetryingFetch(lambda _url: HttpBytes(404, b""), sleep=sleeps.append)
    assert not_found("u").status == 404

    always_down = RetryingFetch(
        lambda _url: HttpBytes(503, b""), max_attempts=2, sleep=lambda _s: None
    )
    with pytest.raises(MarketDataError, match="after 2 attempts"):
        always_down("u")
