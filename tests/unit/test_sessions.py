"""Unit tests for DST-aware gold trading session classification (`domain/sessions.py`)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from nautilus_lab.domain.sessions import (
    GoldSession,
    classify_gold_session,
    is_gold_entry_session,
    london_trading_date,
)


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_london_ny_overlap_handles_us_uk_dst_gap() -> None:
    """London-NY overlap shifts cleanly across US/UK spring & autumn DST gaps in 2026."""
    # 1. Winter aligned (2026-01-15, Thu): London GMT (UTC+0), NY EST (UTC-5)
    #    08:00 EST = 13:00 UTC; 07:00 GMT = 07:00 UTC
    assert classify_gold_session(_utc(2026, 1, 15, 6, 0)) is GoldSession.ASIA
    assert classify_gold_session(_utc(2026, 1, 15, 7, 0)) is GoldSession.LONDON
    assert classify_gold_session(_utc(2026, 1, 15, 12, 0)) is GoldSession.LONDON
    assert classify_gold_session(_utc(2026, 1, 15, 13, 0)) is GoldSession.LONDON_NY_OVERLAP
    assert classify_gold_session(_utc(2026, 1, 15, 16, 0)) is GoldSession.LONDON_NY_OVERLAP
    assert classify_gold_session(_utc(2026, 1, 15, 17, 0)) is GoldSession.NY_AFTERNOON

    # 2. Spring US/UK DST gap (2026-03-18, Wed): US already EDT (UTC-4), UK still GMT (UTC+0)
    #    08:00 EDT = 12:00 UTC -> overlap starts 1 hour earlier in UTC than in winter!
    assert classify_gold_session(_utc(2026, 3, 18, 7, 0)) is GoldSession.LONDON
    assert classify_gold_session(_utc(2026, 3, 18, 11, 0)) is GoldSession.LONDON
    assert classify_gold_session(_utc(2026, 3, 18, 12, 0)) is GoldSession.LONDON_NY_OVERLAP
    assert classify_gold_session(_utc(2026, 3, 18, 16, 0)) is GoldSession.LONDON_NY_OVERLAP
    assert classify_gold_session(_utc(2026, 3, 18, 17, 0)) is GoldSession.NY_AFTERNOON

    # 3. Summer aligned (2026-07-15, Wed): London BST (UTC+1), NY EDT (UTC-4)
    #    07:00 BST = 06:00 UTC; 08:00 EDT = 12:00 UTC = 13:00 BST; 17:00 BST = 16:00 UTC
    assert classify_gold_session(_utc(2026, 7, 15, 5, 0)) is GoldSession.ASIA
    assert classify_gold_session(_utc(2026, 7, 15, 6, 0)) is GoldSession.LONDON
    assert classify_gold_session(_utc(2026, 7, 15, 11, 0)) is GoldSession.LONDON
    assert classify_gold_session(_utc(2026, 7, 15, 12, 0)) is GoldSession.LONDON_NY_OVERLAP
    assert classify_gold_session(_utc(2026, 7, 15, 15, 0)) is GoldSession.LONDON_NY_OVERLAP
    assert classify_gold_session(_utc(2026, 7, 15, 16, 0)) is GoldSession.NY_AFTERNOON

    # 4. Autumn US/UK DST gap (2026-10-28, Wed): UK back on GMT (Oct 25), US still EDT (until Nov 1)
    #    08:00 EDT = 12:00 UTC -> overlap starts at 12:00 GMT / 12:00 UTC
    assert classify_gold_session(_utc(2026, 10, 28, 11, 0)) is GoldSession.LONDON
    assert classify_gold_session(_utc(2026, 10, 28, 12, 0)) is GoldSession.LONDON_NY_OVERLAP


def test_weekend_and_maintenance_off_hours() -> None:
    """Weekend closure (Fri 17:00 ET -> Sun 18:00 ET) and daily 17:00 ET break are classified."""
    # Winter EST (UTC-5): 17:00 EST = 22:00 UTC, 18:00 EST = 23:00 UTC
    assert classify_gold_session(_utc(2026, 1, 16, 21, 59)) is GoldSession.NY_AFTERNOON
    assert classify_gold_session(_utc(2026, 1, 16, 22, 0)) is GoldSession.WEEKEND
    assert classify_gold_session(_utc(2026, 1, 17, 12, 0)) is GoldSession.WEEKEND
    assert classify_gold_session(_utc(2026, 1, 18, 22, 59)) is GoldSession.WEEKEND
    assert classify_gold_session(_utc(2026, 1, 18, 23, 0)) is GoldSession.OFF_HOURS
    assert classify_gold_session(_utc(2026, 1, 19, 0, 0)) is GoldSession.ASIA

    # Daily CME maintenance break: Tue 17:00-18:00 EST = 22:00-23:00 UTC
    assert classify_gold_session(_utc(2026, 1, 20, 22, 0)) is GoldSession.OFF_HOURS

    # Summer EDT (UTC-4): Fri 17:00 EDT = 21:00 UTC
    assert classify_gold_session(_utc(2026, 7, 17, 20, 59)) is GoldSession.NY_AFTERNOON
    assert classify_gold_session(_utc(2026, 7, 17, 21, 0)) is GoldSession.WEEKEND


def test_london_trading_date_and_entry_window() -> None:
    # In BST (UTC+1), 23:30 UTC is already 00:30 next calendar day in London -> ASIA session.
    ts = _utc(2026, 7, 15, 23, 30)
    assert london_trading_date(ts) == date(2026, 7, 16)
    assert classify_gold_session(ts) is GoldSession.ASIA

    for session in GoldSession:
        expected = session in (GoldSession.LONDON, GoldSession.LONDON_NY_OVERLAP)
        assert is_gold_entry_session(session) is expected


def test_naive_datetime_rejected() -> None:
    naive = datetime(2026, 1, 15, 12, 0)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        classify_gold_session(naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        london_trading_date(naive)
