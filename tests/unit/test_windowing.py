from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from conftest import make_bars
from nautilus_lab.domain.windowing import bar_span, within_bars


@dataclass(frozen=True)
class _Event:
    ts_utc: datetime


def test_bar_span_is_open_at_first_bar_open_and_closed_at_last_close() -> None:
    bars = make_bars(3, step_minutes=60)
    span = bar_span(bars)
    assert span == (bars[0].ts_utc - timedelta(hours=1), bars[-1].ts_utc)


def test_within_bars_drops_history_and_future() -> None:
    bars = make_bars(3, step_minutes=60, start=datetime(2024, 1, 1, 1, tzinfo=UTC))
    start, end = bar_span(bars) or (None, None)
    assert start is not None
    assert end is not None
    events = [
        _Event(start),  # exactly the open of the first bar: belongs to the bar before
        _Event(start + timedelta(minutes=1)),
        _Event(end),
        _Event(end + timedelta(seconds=1)),  # out-of-sample for this run
    ]
    kept = within_bars(events, bars)
    assert kept == [events[1], events[2]]


def test_within_bars_without_bars_keeps_nothing() -> None:
    assert within_bars([_Event(datetime(2024, 1, 1, tzinfo=UTC))], []) == []


def test_warmup_tail_takes_the_bars_closing_before_the_window() -> None:
    from nautilus_lab.domain.windowing import warmup_tail

    bars = make_bars(10)
    assert warmup_tail(bars, bars[6:], 3) == bars[3:6]
    assert warmup_tail(bars, bars[2:], 5) == bars[:2]  # not enough history: all of it
    assert warmup_tail(bars, bars[6:], 0) == []
    assert warmup_tail(bars, [], 3) == []
