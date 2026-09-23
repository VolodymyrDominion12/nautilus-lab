from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nautilus_lab.application.collect_live_agg_trades import CollectLiveAggTrades
from nautilus_lab.domain.ticks import AggTrade

START = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def _trade(index: int, *, ts: datetime | None = None) -> AggTrade:
    return AggTrade(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts or START + timedelta(seconds=index),
        agg_id=1000 + index,
        price="2700.00",
        qty="0.5",
        is_buyer_maker=index % 2 == 0,
    )


class _Source:
    def __init__(self, trades: list[AggTrade]) -> None:
        self._trades = trades
        self.stopped = False

    def trades(self) -> Any:
        yield from self._trades

    def stop(self) -> None:
        self.stopped = True


class _Catalog:
    def __init__(self) -> None:
        self.batches: list[list[AggTrade]] = []

    def write(self, trades: Any, *, symbol: str) -> int:
        self.batches.append(list(trades))
        return len(trades)

    def load(self, **kwargs: Any) -> list[AggTrade]:
        raise AssertionError("collector must not read")


def _clock(values: list[datetime]) -> Any:
    """A clock that returns the next scripted instant on each call."""
    state = {"index": 0}

    def now() -> datetime:
        index = min(state["index"], len(values) - 1)
        state["index"] += 1
        return values[index]

    return now


def test_collector_flushes_in_batches_and_stops_the_source() -> None:
    """Bounded memory: everything collected lands on disk as it arrives, not at the end."""
    catalog = _Catalog()
    source = _Source([_trade(index) for index in range(7)])
    seen: list[tuple[int, datetime | None]] = []
    collector = CollectLiveAggTrades(
        source,
        catalog,
        symbol="ETHUSDT",
        batch_size=3,
        progress=lambda written, last: seen.append((written, last)),
    )

    report = collector.execute(duration=timedelta(minutes=5))

    assert report.trades_written == 7
    # 3 + 3 + the final partial batch of 1.
    assert [len(batch) for batch in catalog.batches] == [3, 3, 1]
    assert report.batches == 3
    assert source.stopped is True
    assert seen[0][0] == 3
    assert report.first_ts == _trade(0).ts_utc
    assert report.last_ts == _trade(6).ts_utc


def test_collector_honours_the_trade_cap() -> None:
    catalog = _Catalog()
    source = _Source([_trade(index) for index in range(100)])
    collector = CollectLiveAggTrades(source, catalog, symbol="ETHUSDT", batch_size=4)

    report = collector.execute(max_trades=10, duration=timedelta(hours=1))

    assert report.trades_written == 10
    assert report.stopped_reason == "trade cap reached"
    assert source.stopped is True


def test_collector_honours_the_deadline_on_a_quiet_market() -> None:
    """A duration limit must end the run even if the socket keeps feeding trades."""
    catalog = _Catalog()
    source = _Source([_trade(index) for index in range(50)])
    clock = _clock([START, START, START, START + timedelta(minutes=6)])
    collector = CollectLiveAggTrades(source, catalog, symbol="ETHUSDT", batch_size=2, now=clock)

    report = collector.execute(duration=timedelta(minutes=5))

    assert report.stopped_reason == "duration reached"
    assert 0 < report.trades_written < 50
    assert source.stopped is True


def test_collector_refuses_an_unbounded_run() -> None:
    collector = CollectLiveAggTrades(_Source([]), _Catalog(), symbol="ETHUSDT")
    with pytest.raises(ValueError, match="unbounded"):
        collector.execute()


def test_collector_reports_an_empty_stream_instead_of_writing_nothing() -> None:
    """An empty series must not look like a collected one."""
    catalog = _Catalog()
    source = _Source([])
    collector = CollectLiveAggTrades(source, catalog, symbol="ETHUSDT")

    with pytest.raises(ValueError, match="no aggTrades arrived"):
        collector.execute(duration=timedelta(seconds=1))

    assert catalog.batches == []
    assert source.stopped is True
