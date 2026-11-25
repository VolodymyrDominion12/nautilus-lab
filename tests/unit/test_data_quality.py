from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.calendar import (
    TradingCalendar,
    is_trading_bar_close,
    trading_calendar_for_instrument,
)
from nautilus_lab.domain.data_quality import QualityStatus, check_bars


def _build_bars(
    start: datetime,
    end: datetime,
    *,
    interval: timedelta,
    calendar: TradingCalendar,
    instrument_id: str = "MGCZ26.XCEC",
) -> list[OhlcvBar]:
    bars: list[OhlcvBar] = []
    cursor = start
    price = Decimal("2650.00")
    while cursor <= end:
        if is_trading_bar_close(cursor, interval=interval, calendar=calendar):
            bars.append(
                OhlcvBar(
                    instrument_id=instrument_id,
                    ts_utc=cursor,
                    open=price,
                    high=price + Decimal("1"),
                    low=price - Decimal("1"),
                    close=price,
                    volume=Decimal("100"),
                )
            )
        cursor += interval
    return bars


def test_trading_calendar_resolution() -> None:
    assert trading_calendar_for_instrument("GCZ26.XCEC") is TradingCalendar.CME_GLOBEX_23_5
    assert trading_calendar_for_instrument("MGCZ26.XCEC") is TradingCalendar.CME_GLOBEX_23_5
    assert trading_calendar_for_instrument("GC.v.0.GLBX") is TradingCalendar.CME_GLOBEX_23_5
    assert trading_calendar_for_instrument("1OZZ26.XCEC") is TradingCalendar.CME_1OZ_24_7
    assert trading_calendar_for_instrument("1OZ.v.0.GLBX") is TradingCalendar.CME_1OZ_24_7
    assert trading_calendar_for_instrument("PAXG/USDT.SIM") is TradingCalendar.CRYPTO_24_7
    assert trading_calendar_for_instrument("XAUUSDT-PERP.SIM") is TradingCalendar.CRYPTO_24_7


def test_cme_23x5_weekend_is_not_a_gap() -> None:
    # Span two full weeks in EST (January 2026): daily 17:00-18:00 ET breaks and
    # Friday 17:00 ET -> Sunday 18:00 ET weekends must produce zero missing bars.
    start = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 19, 23, 0, tzinfo=UTC)
    interval = timedelta(hours=1)
    bars = _build_bars(start, end, interval=interval, calendar=TradingCalendar.CME_GLOBEX_23_5)

    cme_report = check_bars(
        bars,
        interval=interval,
        calendar=TradingCalendar.CME_GLOBEX_23_5,
    )
    assert cme_report.status() is QualityStatus.OK
    assert cme_report.gaps == ()
    assert cme_report.missing_bars == 0
    assert cme_report.expected_bars == len(bars)

    # Confirm the exact same series would FAIL if mistakenly checked against 24/7 crypto hours.
    crypto_report = check_bars(bars, interval=interval, calendar=TradingCalendar.CRYPTO_24_7)
    assert crypto_report.status() is QualityStatus.FAIL
    assert crypto_report.missing_bars > 0


def test_cme_23x5_handles_us_dst_spring_and_fall_transitions() -> None:
    interval = timedelta(hours=1)
    # 2026 US Spring Forward (Sun Mar 8) & Fall Back (Sun Nov 1)
    spring_bars = _build_bars(
        datetime(2026, 3, 6, 18, 0, tzinfo=UTC),
        datetime(2026, 3, 9, 6, 0, tzinfo=UTC),
        interval=interval,
        calendar=TradingCalendar.CME_GLOBEX_23_5,
    )
    fall_bars = _build_bars(
        datetime(2026, 10, 30, 18, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 6, 0, tzinfo=UTC),
        interval=interval,
        calendar=TradingCalendar.CME_GLOBEX_23_5,
    )
    assert (
        check_bars(
            spring_bars, interval=interval, calendar=TradingCalendar.CME_GLOBEX_23_5
        ).status()
        is QualityStatus.OK
    )
    assert (
        check_bars(fall_bars, interval=interval, calendar=TradingCalendar.CME_GLOBEX_23_5).status()
        is QualityStatus.OK
    )


def test_cme_23x5_ignores_cme_holidays_and_catches_midweek_missing_bars() -> None:
    interval = timedelta(hours=1)
    # Good Friday 2026-04-03: closed Thu 17:00 ET -> Sun 18:00 ET
    bars = _build_bars(
        datetime(2026, 4, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 4, 7, 0, 0, tzinfo=UTC),
        interval=interval,
        calendar=TradingCalendar.CME_GLOBEX_23_5,
    )
    clean = check_bars(bars, interval=interval, calendar=TradingCalendar.CME_GLOBEX_23_5)
    assert clean.status() is QualityStatus.OK
    assert clean.gaps == ()

    # Drop two active Wednesday bars (2026-04-01 14:00 & 15:00 UTC)
    with_hole = [
        bar
        for bar in bars
        if bar.ts_utc
        not in {
            datetime(2026, 4, 1, 14, 0, tzinfo=UTC),
            datetime(2026, 4, 1, 15, 0, tzinfo=UTC),
        }
    ]
    gapped = check_bars(with_hole, interval=interval, calendar=TradingCalendar.CME_GLOBEX_23_5)
    assert gapped.missing_bars == 2
    assert len(gapped.gaps) == 1
    assert gapped.status() is QualityStatus.FAIL  # 2 / ~66 > 1%


def test_cme_1oz_24x7_allows_saturday_maintenance_window_only() -> None:
    interval = timedelta(minutes=15)
    bars = _build_bars(
        datetime(2026, 8, 7, 22, 0, tzinfo=UTC),
        datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        interval=interval,
        calendar=TradingCalendar.CME_1OZ_24_7,
        instrument_id="1OZZ26.XCEC",
    )
    report = check_bars(bars, interval=interval, calendar=TradingCalendar.CME_1OZ_24_7)
    assert report.status() is QualityStatus.OK
    assert report.gaps == ()

    # Dropping one active Sunday bar must be flagged
    without_sunday = [bar for bar in bars if bar.ts_utc != datetime(2026, 8, 9, 6, 0, tzinfo=UTC)]
    gapped = check_bars(without_sunday, interval=interval, calendar=TradingCalendar.CME_1OZ_24_7)
    assert gapped.missing_bars == 1
    assert gapped.status() is QualityStatus.WARN


def test_naive_timestamp_fails_closed_in_calendar() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_trading_bar_close(
            datetime(2026, 1, 5, 12, 0),  # noqa: DTZ001 — naive datetime is the test input
            interval=timedelta(hours=1),
            calendar=TradingCalendar.CME_GLOBEX_23_5,
        )
