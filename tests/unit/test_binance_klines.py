from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.infrastructure.binance_klines import BinancePublicKlines, parse_binance_kline
from nautilus_lab.infrastructure.timeframe import nautilus_bar_type


def test_parse_binance_kline_uses_close_time() -> None:
    row = [
        1_704_067_200_000,
        "2200.00",
        "2210.00",
        "2190.00",
        "2205.50",
        "15.5",
        1_704_070_799_999,
    ]
    bar = parse_binance_kline(row, instrument_id="ETH/USDT.SIM")
    assert bar.close == Decimal("2205.50")
    assert bar.volume == Decimal("15.5")
    assert bar.ts_utc == datetime(2024, 1, 1, 0, 59, 59, 999000, tzinfo=UTC)
    # A short row cannot answer "how much did takers buy?", so the field stays unknown
    # instead of being defaulted to zero (which would read as "no aggressive buying").
    assert bar.taker_buy_base_volume is None


def test_parse_binance_kline_keeps_the_taker_buy_field() -> None:
    """Field 9 is the only real maker/taker split a kline carries (defect D4)."""
    row = [
        1_704_067_200_000,
        "2200.00",
        "2210.00",
        "2190.00",
        "2205.50",
        "15.5",
        1_704_070_799_999,
        "34185.25",
        42,
        "9.75",
        "21488.625",
        "0",
    ]
    bar = parse_binance_kline(row, instrument_id="ETH/USDT.SIM")
    assert bar.taker_buy_base_volume == Decimal("9.75")
    assert bar.taker_sell_base_volume == Decimal("5.75")
    assert isinstance(bar.taker_buy_base_volume, Decimal)


def test_binance_feed_paginates_and_stops_before_end() -> None:
    page1 = [
        [
            1_704_067_200_000,
            "2200",
            "2210",
            "2190",
            "2205",
            "10",
            1_704_070_799_999,
        ]
    ]
    page2 = [
        [
            1_704_070_800_000,
            "2205",
            "2220",
            "2200",
            "2210",
            "11",
            1_704_074_399_999,
        ]
    ]

    class FakeHttp:
        def __init__(self) -> None:
            self.calls: list[Mapping[str, str]] = []
            self.pages = [page1, page2, []]

        def get_json(self, url: str, params: Mapping[str, str]) -> object:
            self.calls.append(params)
            assert "api.binance.com" in url
            return self.pages.pop(0)

    feed = BinancePublicKlines(FakeHttp(), now=datetime(2024, 1, 2, tzinfo=UTC), page_limit=1)
    bars = feed.fetch(
        symbol="ETHUSDT",
        interval="1h",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 1, 2, 0, tzinfo=UTC),
        instrument_id="ETH/USDT.SIM",
    )
    assert len(bars) == 2
    assert bars[0].close == Decimal("2205")
    assert bars[1].close == Decimal("2210")


def test_parse_rejects_short_row() -> None:
    with pytest.raises(ValueError, match="at least 7"):
        parse_binance_kline([1, 2], instrument_id="ETH/USDT.SIM")


def test_nautilus_bar_type_maps_hour_interval() -> None:
    assert nautilus_bar_type("ETH/USDT.SIM", "1h") == "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"


def test_nautilus_bar_type_rejects_unknown_interval() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        nautilus_bar_type("ETH/USDT.SIM", "3h")


def test_fetch_drops_the_still_forming_candle_instead_of_failing() -> None:
    """An ingest may run at any minute of the hour, not only just after a boundary.

    REST returns the in-progress candle as its last row, and the domain's lookahead
    guard rightly refuses a bar whose close time is in the future. Before this, the
    whole ingest died with "bar timestamp is in the future" whenever it was run
    mid-hour — the exact moment `--incremental` catch-up is normally used.
    """
    closed = [
        1_704_067_200_000,
        "2200.00",
        "2210.00",
        "2190.00",
        "2205.50",
        "15.5",
        1_704_070_799_999,
    ]
    # The candle that opened at 01:00 and closes at 01:59:59.999 — while the injected
    # clock still reads 01:30, i.e. it has not closed yet.
    forming = [
        1_704_070_800_000,
        "2205.50",
        "2230.00",
        "2200.00",
        "2222.00",
        "9.0",
        1_704_074_399_999,
    ]

    class FakeHttp:
        def __init__(self) -> None:
            self.pages: list[object] = [[closed, forming], []]

        def get_json(self, url: str, params: Mapping[str, str]) -> object:
            assert "api.binance.com" in url
            return self.pages.pop(0)

    feed = BinancePublicKlines(FakeHttp(), now=datetime(2024, 1, 1, 1, 30, tzinfo=UTC))

    bars = feed.fetch(
        symbol="ETHUSDT",
        interval="1h",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 1, 2, 0, tzinfo=UTC),
        instrument_id="ETH/USDT.SIM",
    )

    assert [bar.ts_utc for bar in bars] == [datetime(2024, 1, 1, 0, 59, 59, 999000, tzinfo=UTC)]
    assert bars[0].close == Decimal("2205.50")


def test_fetch_keeps_the_candle_once_the_clock_passes_its_close() -> None:
    """The same row is data as soon as it has closed; dropping must not be permanent."""
    forming = [
        1_704_070_800_000,
        "2205.50",
        "2230.00",
        "2200.00",
        "2222.00",
        "9.0",
        1_704_074_399_999,
    ]

    class FakeHttp:
        def __init__(self) -> None:
            self.pages: list[object] = [[forming], []]

        def get_json(self, url: str, params: Mapping[str, str]) -> object:
            return self.pages.pop(0)

    feed = BinancePublicKlines(FakeHttp(), now=datetime(2024, 1, 1, 2, 0, tzinfo=UTC))

    bars = feed.fetch(
        symbol="ETHUSDT",
        interval="1h",
        start=datetime(2024, 1, 1, 1, 0, tzinfo=UTC),
        end=datetime(2024, 1, 1, 2, 0, tzinfo=UTC),
        instrument_id="ETH/USDT.SIM",
    )

    assert len(bars) == 1
    assert bars[0].close == Decimal("2222.00")
