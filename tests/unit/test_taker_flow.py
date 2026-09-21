"""Taker flow (kline field 9): parser -> series -> feed join -> VPIN.

The defect this closes is D4 in docs/23-infrastruktura-danyh-plan.md: Binance returns
twelve fields per kline and the parser read seven, so the only real maker/taker split in
the response was dropped and every order-flow feature had to guess from the price path.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.application.dtos import BacktestRequest, IngestRequest
from nautilus_lab.application.ingest_historical_bars import IngestHistoricalBars
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar
from nautilus_lab.domain.errors import CatalogEmptyError, InvalidBarError
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.vpin import BarVpin
from nautilus_lab.infrastructure.binance_klines import BinancePublicKlines
from nautilus_lab.infrastructure.nautilus.bar_feed import ResearchBarFeed
from nautilus_lab.infrastructure.nautilus.instrument import (
    binance_symbol_for_instrument,
    binance_symbol_to_instrument_id,
)
from nautilus_lab.infrastructure.taker_flow_catalog import ParquetTakerFlowCatalog

_ORIGIN = datetime(2024, 1, 1, tzinfo=UTC)
_BAR_TYPE = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"


def _bar(
    hour: int,
    *,
    volume: str = "100",
    taker_buy: str | None = None,
    price: str = "2200",
) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=_ORIGIN + timedelta(hours=hour),
        open=Decimal(price),
        high=Decimal(price) + Decimal("5"),
        low=Decimal(price) - Decimal("5"),
        close=Decimal(price),
        volume=Decimal(volume),
        taker_buy_base_volume=None if taker_buy is None else Decimal(taker_buy),
    )


def _request(*, instrument_id: str = "ETH/USDT.SIM") -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.RESEARCH,
        instrument_id=instrument_id,
        bar_count=10,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.VPIN_MOMENTUM,
        source=BarOrigin.CATALOG,
        bar_type=_BAR_TYPE,
    )


class _FakeBarCatalog:
    """Bar catalog that stores nothing: these tests are about the flow join."""

    def __init__(self, bars: Sequence[OhlcvBar]) -> None:
        self._bars = list(bars)

    def write(self, *args: object, **kwargs: object) -> int:
        raise AssertionError("read-only test catalog")

    def load(
        self,
        *,
        bar_type: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[OhlcvBar]:
        return list(self._bars)


class _RecordingCatalog:
    """Bar catalog that records what ingest handed it."""

    def __init__(self) -> None:
        self.written: list[OhlcvBar] = []

    def write(
        self,
        bars: Sequence[OhlcvBar],
        *,
        bar_type: str,
        instrument_id: str = "",
    ) -> int:
        self.written = list(bars)
        return len(self.written)

    def load(self, **kwargs: object) -> list[OhlcvBar]:
        raise AssertionError("ingest does not load")


def test_taker_flow_series_round_trips_and_merges_by_timestamp(tmp_path: Path) -> None:
    store = ParquetTakerFlowCatalog(tmp_path)
    assert store.series_exists("ETHUSDT") is False

    assert store.write([_bar(0, taker_buy="40"), _bar(1, taker_buy="60")], symbol="ethusdt") == 2
    assert store.series_exists("ETHUSDT") is True
    assert store.load(symbol="ETHUSDT") == {
        _bar(0).ts_utc: Decimal("40"),
        _bar(1).ts_utc: Decimal("60"),
    }

    # A re-ingest of an overlapping window replaces its timestamps instead of leaving
    # two rows for one bar — the same rule the bar catalog follows.
    merged = store.write([_bar(1, taker_buy="55"), _bar(2, taker_buy="10")], symbol="ETHUSDT")
    assert merged == 3
    series = store.load(symbol="ETHUSDT")
    assert series[_bar(1).ts_utc] == Decimal("55")
    assert series[_bar(2).ts_utc] == Decimal("10")
    assert len(series) == 3

    windowed = store.load(symbol="ETHUSDT", start=_bar(1).ts_utc, end=_bar(2).ts_utc)
    assert windowed == {_bar(1).ts_utc: Decimal("55")}


def test_taker_flow_writer_refuses_a_series_without_the_field(tmp_path: Path) -> None:
    store = ParquetTakerFlowCatalog(tmp_path)
    with pytest.raises(CatalogEmptyError, match="field 9"):
        store.write([_bar(0), _bar(1)], symbol="ETHUSDT")
    assert store.series_exists("ETHUSDT") is False


def test_taker_flow_writer_skips_unknown_bars_instead_of_storing_zero(tmp_path: Path) -> None:
    store = ParquetTakerFlowCatalog(tmp_path)
    assert store.write([_bar(0, taker_buy="0"), _bar(1)], symbol="ETHUSDT") == 1
    series = store.load(symbol="ETHUSDT")
    # A genuine "no aggressive buying" bar is stored as 0; an unknown bar is absent.
    assert series == {_bar(0).ts_utc: Decimal("0")}
    assert _bar(1).ts_utc not in series


def test_bar_feed_enriches_only_matching_timestamps(tmp_path: Path) -> None:
    store = ParquetTakerFlowCatalog(tmp_path)
    store.write([_bar(0, taker_buy="40")], symbol="ETHUSDT")
    feed = ResearchBarFeed(_FakeBarCatalog([_bar(0), _bar(1)]), taker_flow=store)

    loaded = feed.load(_request())
    assert loaded[0].taker_buy_base_volume == Decimal("40")
    assert loaded[1].taker_buy_base_volume is None


def test_bar_feed_rejects_a_flow_series_that_cannot_belong_to_these_bars(
    tmp_path: Path,
) -> None:
    """A mismatched flow series must fail closed, not tilt the feature."""
    store = ParquetTakerFlowCatalog(tmp_path)
    store.write([_bar(0, volume="100", taker_buy="150")], symbol="ETHUSDT")
    feed = ResearchBarFeed(_FakeBarCatalog([_bar(0, volume="100")]), taker_flow=store)

    with pytest.raises(InvalidBarError, match="taker buy"):
        feed.load(_request())


def test_bar_feed_without_a_flow_store_returns_the_bars_unchanged() -> None:
    bars = [_bar(0), _bar(1)]
    assert ResearchBarFeed(_FakeBarCatalog(bars)).load(_request()) == bars


def test_bar_feed_leaves_instruments_without_a_spot_symbol_alone(tmp_path: Path) -> None:
    store = ParquetTakerFlowCatalog(tmp_path)
    store.write([_bar(0, taker_buy="40")], symbol="ETHUSDT")
    feed = ResearchBarFeed(_FakeBarCatalog([_bar(0)]), taker_flow=store)

    loaded = feed.load(_request(instrument_id="ETHUSDT-PERP.SIM"))
    assert loaded[0].taker_buy_base_volume is None


def test_instrument_symbol_lookup_round_trips_spot_only() -> None:
    assert binance_symbol_for_instrument(binance_symbol_to_instrument_id("ETHUSDT")) == "ETHUSDT"
    assert binance_symbol_for_instrument("ETHUSDT-PERP.SIM") is None
    assert binance_symbol_for_instrument("not-an-instrument") is None


def test_ingest_keeps_the_taker_split_from_the_kline_field_nine(tmp_path: Path) -> None:
    """Raw kline JSON -> parsed bar -> its own series, in one ingest pass."""

    class _FakeHttp:
        def get_json(self, url: str, params: object) -> object:
            return [
                [
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
            ]

    catalog = _RecordingCatalog()
    flow = ParquetTakerFlowCatalog(tmp_path)
    use_case = IngestHistoricalBars(
        BinancePublicKlines(_FakeHttp()),
        catalog,
        catalog_path=str(tmp_path),
        taker_flow=flow,
    )
    report = use_case.execute(
        IngestRequest(
            mode=TradingMode.RESEARCH,
            symbol="ETHUSDT",
            interval="1h",
            instrument_id="ETH/USDT.SIM",
            bar_type=_BAR_TYPE,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )
    )

    assert report.bars_written == 1
    assert report.taker_flow_rows == 1
    assert catalog.written[0].taker_buy_base_volume == Decimal("9.75")
    assert list(flow.load(symbol="ETHUSDT").values()) == [Decimal("9.75")]


def test_ingest_skips_the_flow_series_when_the_feed_does_not_carry_it(tmp_path: Path) -> None:
    class _Feed:
        def fetch(self, **kwargs: object) -> list[OhlcvBar]:
            return [_bar(0)]

    flow = ParquetTakerFlowCatalog(tmp_path)
    report = IngestHistoricalBars(
        _Feed(),
        _RecordingCatalog(),
        catalog_path=str(tmp_path),
        taker_flow=flow,
    ).execute(
        IngestRequest(
            mode=TradingMode.RESEARCH,
            symbol="ETHUSDT",
            interval="1h",
            instrument_id="ETH/USDT.SIM",
            bar_type=_BAR_TYPE,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )
    )

    assert report.taker_flow_rows == 0
    assert flow.series_exists("ETHUSDT") is False


def test_vpin_uses_the_real_taker_split_when_the_bar_carries_it() -> None:
    """Half bought, half sold is a balanced bar — however the price path looks."""
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.7"))
    state = None
    for index in range(5):
        state = vpin.update(_bar(index, volume="100", taker_buy="50", price=str(2200 + index)))

    assert state is not None
    assert state.value == Decimal("0")
    assert state.toxic is False


def test_vpin_falls_back_to_the_tick_rule_when_the_split_is_unknown() -> None:
    """The same rising series without field 9 stays the old proxy: fully one-sided."""
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.7"))
    state = None
    for index in range(5):
        state = vpin.update(_bar(index, volume="100", price=str(2200 + index)))

    assert state is not None
    assert state.value == Decimal("1")
    assert state.toxic is True


def test_vpin_mixes_the_real_split_across_buckets() -> None:
    """The split is bucketed in real units, so 60/40 lands strictly between 0 and 1."""
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.7"))
    state = None
    for index in range(3):
        state = vpin.update(_bar(index, volume="100", taker_buy="80", price=str(2200 + index)))

    assert state is not None
    assert state.value == Decimal("0.6")
    assert state.toxic is False


def test_a_bar_larger_than_a_bucket_keeps_its_split_inside_every_bucket() -> None:
    """Balanced flow must not look toxic merely because one bar spans several buckets.

    Pouring the buying first and the selling afterwards produced a fully one-sided
    first bucket for every bar wider than a bucket: measured on ETHUSDT 1h that would
    have pushed the median VPIN of balanced flow from ~0.01 to 1.0. The regression is
    pinned here, in the smallest form of that shape.
    """
    vpin = BarVpin(bucket_volume=Decimal("100"), toxic_threshold=Decimal("0.7"))
    emitted: list[Decimal] = []
    for index in range(3):
        state = vpin.update(_bar(index, volume="250", taker_buy="125", price=str(2200 + index)))
        if state is not None:
            emitted.append(state.value)

    assert emitted, "250 of volume against a 100 bucket must complete buckets"
    assert set(emitted) == {Decimal("0")}
    assert state is not None
    assert state.toxic is False
