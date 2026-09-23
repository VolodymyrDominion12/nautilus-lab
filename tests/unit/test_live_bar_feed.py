from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.live_bar_feed import (
    LiveBarCollector,
    SeededLiveBarFeed,
)

START = datetime(2024, 1, 1, tzinfo=UTC)


def _bars(count: int, *, start: datetime = START, step_hours: int = 1) -> list[OhlcvBar]:
    return [
        OhlcvBar(
            instrument_id="ETH/USDT.SIM",
            ts_utc=start + timedelta(hours=index * step_hours),
            open=Decimal("2000"),
            high=Decimal("2010"),
            low=Decimal("1990"),
            close=Decimal("2000") + Decimal(index),
            volume=Decimal("10"),
        )
        for index in range(count)
    ]


class _Source:
    """A stand-in for the WebSocket stream: yields a fixed list, records stop()."""

    def __init__(self, bars: list[OhlcvBar]) -> None:
        self._bars = bars
        self.stopped = False

    def bars(self) -> Any:
        yield from self._bars

    def stop(self) -> None:
        self.stopped = True


class _History:
    def __init__(self, bars: list[OhlcvBar]) -> None:
        self._bars = bars

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        return list(self._bars)

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        raise AssertionError("live paper refuses multi-leg")


def _request(bars: int = 10) -> BacktestRequest:
    return BacktestRequest(
        mode=TradingMode.PAPER,
        instrument_id="ETH/USDT.SIM",
        bar_count=bars,
        starting_equity=Decimal("100000"),
        risk=RiskLimits(
            risk_per_trade=Decimal("0.005"),
            stop_pct=Decimal("0.01"),
            max_daily_loss=Decimal("0.02"),
            max_drawdown=Decimal("0.06"),
        ),
        robot=RobotName.REGIME,
    )


def test_collector_stops_the_source_when_the_window_is_full() -> None:
    """An infinite stream must be closed, not abandoned, once enough bars arrived."""
    source = _Source(_bars(50))
    collector = LiveBarCollector(source=source, count=3, timeout_seconds=60.0)

    result = collector.collect()

    assert [bar.ts_utc for bar in result.bars] == [bar.ts_utc for bar in _bars(3)]
    assert result.timed_out is False
    assert source.stopped is True


def test_collector_reports_a_shortfall_instead_of_hanging() -> None:
    """A quiet market must surface as a reported shortfall, not as a hang."""
    clock = {"now": 0.0}

    def now() -> float:
        clock["now"] += 10.0
        return clock["now"]

    source = _Source(_bars(100))
    collector = LiveBarCollector(
        source=source, count=5, timeout_seconds=15.0, now=now, sleep=lambda _s: None
    )

    result = collector.collect()

    assert result.timed_out is True
    assert len(result.bars) < 5
    assert result.requested == 5
    assert source.stopped is True


def test_live_feed_concatenates_history_and_live_bars_by_timestamp() -> None:
    """Warm-up history plus live bars, in time order, with no duplicate timestamps."""
    history = _bars(4)
    live = tuple(_bars(3, start=START + timedelta(hours=4)))
    feed = SeededLiveBarFeed(
        history=_History(history),
        collector=LiveBarCollector(source=_Source(list(live)), count=3, timeout_seconds=60.0),
        live_bars=3,
    )

    bars = feed.load(_request(bars=7))

    assert len(bars) == 7
    assert [bar.ts_utc for bar in bars] == sorted(bar.ts_utc for bar in bars)
    assert bars[-1].ts_utc == START + timedelta(hours=6)


def test_live_bar_replaces_a_history_bar_with_the_same_timestamp() -> None:
    """The socket value wins: it is what the session would actually have seen."""
    history = _bars(4)
    # A live re-send of the last historical bar, with a corrected close.
    live = (
        OhlcvBar(
            instrument_id="ETH/USDT.SIM",
            ts_utc=history[-1].ts_utc,
            open=history[-1].open,
            high=history[-1].high,
            low=history[-1].low,
            close=Decimal("9999"),
            volume=history[-1].volume,
        ),
    )
    feed = SeededLiveBarFeed(
        history=_History(history),
        collector=LiveBarCollector(source=_Source(list(live)), count=1, timeout_seconds=60.0),
        live_bars=1,
    )

    bars = feed.load(_request(bars=10))

    assert len(bars) == 4
    assert bars[-1].close == Decimal("9999")


def test_live_feed_refuses_a_window_with_no_room_for_warmup() -> None:
    feed = SeededLiveBarFeed(
        history=_History(_bars(4)),
        collector=LiveBarCollector(source=_Source([]), count=1, timeout_seconds=1.0),
        live_bars=5,
    )
    with pytest.raises(ValueError, match="warm-up"):
        feed.load(_request(bars=5))


def test_live_feed_refuses_multi_leg() -> None:
    feed = SeededLiveBarFeed(
        history=_History(_bars(4)),
        collector=LiveBarCollector(source=_Source([]), count=1, timeout_seconds=1.0),
        live_bars=1,
    )
    with pytest.raises(ValueError, match="single-instrument"):
        feed.load_multi(_request())
