"""Market trading calendars for data quality checks and Sharpe annualization.

`nautilus-lab` defaults to `CRYPTO_24_7` (365d/yr, 8760h/yr). Exchange-traded
gold futures (`GC`, `MGC` on COMEX/Globex) trade ~23x5 (Sunday 18:00 ET to
Friday 17:00 ET with a daily 17:00-18:00 ET maintenance break and CME holidays),
while `1OZ` transitions to near-24/7 with a Saturday maintenance window. Treating
closed exchange breaks as missing data (`QualityStatus.FAIL`) or annualizing 23x5
hourly Sharpe by sqrt(8760) instead of sqrt(5796) would corrupt both QC and
cross-venue comparisons.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

NEW_YORK_TZ = ZoneInfo("America/New_York")
CHICAGO_TZ = ZoneInfo("America/Chicago")


class TradingCalendar(StrEnum):
    """Supported trading-hours calendars for bar QC and annualization."""

    CRYPTO_24_7 = "crypto_24_7"
    CME_GLOBEX_23_5 = "cme_globex_23_5"
    CME_1OZ_24_7 = "cme_1oz_24_7"


def trading_calendar_for_instrument(instrument_id: str) -> TradingCalendar:
    """Resolve the trading calendar implied by an instrument identifier."""
    upper = instrument_id.strip().upper()
    if upper.endswith((".XCEC", ".GLBX")):
        symbol = upper.rsplit(".", 1)[0]
        if symbol.startswith("1OZ"):
            return TradingCalendar.CME_1OZ_24_7
        return TradingCalendar.CME_GLOBEX_23_5
    return TradingCalendar.CRYPTO_24_7


def _require_utc(ts_utc: datetime) -> datetime:
    if ts_utc.tzinfo is None or ts_utc.utcoffset() is None:
        raise ValueError("ts_utc must be timezone-aware UTC")
    return ts_utc.astimezone(UTC)


def _easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday via the Anonymous Gregorian algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _cme_full_holiday_dates(year: int) -> frozenset[date]:
    """Full-close COMEX Globex holidays (New Year's Day, Good Friday, Christmas)."""
    good_friday = _easter_sunday(year) - timedelta(days=2)
    return frozenset({date(year, 1, 1), good_friday, date(year, 12, 25)})


def _globex_session_window_utc(session_date: date) -> tuple[datetime, datetime] | None:
    """Return `[open_utc, close_utc]` for one COMEX Globex trade date, or None if closed."""
    if session_date.weekday() not in (0, 1, 2, 3, 4):
        return None
    if session_date in _cme_full_holiday_dates(session_date.year):
        return None
    prev_day = session_date - timedelta(days=1)
    start_utc = datetime.combine(prev_day, time(18, 0), tzinfo=NEW_YORK_TZ).astimezone(UTC)
    end_utc = datetime.combine(session_date, time(17, 0), tzinfo=NEW_YORK_TZ).astimezone(UTC)
    return (start_utc, end_utc)


def is_trading_bar_close(
    ts_utc: datetime,
    *,
    interval: timedelta,
    calendar: TradingCalendar = TradingCalendar.CRYPTO_24_7,
) -> bool:
    """Return True if `[ts_utc - interval, ts_utc]` overlaps active market hours."""
    if interval <= timedelta(0):
        raise ValueError("interval must be positive")
    close_utc = _require_utc(ts_utc)
    if calendar is TradingCalendar.CRYPTO_24_7:
        return True

    open_utc = close_utc - interval
    if calendar is TradingCalendar.CME_GLOBEX_23_5:
        base_date = close_utc.astimezone(NEW_YORK_TZ).date()
        start_offset = -(interval.days + 1)
        for delta_days in range(start_offset, 2):
            window = _globex_session_window_utc(base_date + timedelta(days=delta_days))
            if window is not None and min(close_utc, window[1]) > max(open_utc, window[0]):
                return True
        return False

    if calendar is TradingCalendar.CME_1OZ_24_7:
        base_date = close_utc.astimezone(CHICAGO_TZ).date()
        start_offset = -(interval.days + 1)
        for delta_days in range(start_offset, 2):
            candidate = base_date + timedelta(days=delta_days)
            if candidate.weekday() == 5:
                break_start = datetime.combine(candidate, time(2, 0), tzinfo=CHICAGO_TZ).astimezone(
                    UTC
                )
                break_end = datetime.combine(candidate, time(3, 45), tzinfo=CHICAGO_TZ).astimezone(
                    UTC
                )
                if open_utc >= break_start and close_utc <= break_end:
                    return False
        return True

    raise ValueError(f"unsupported calendar: {calendar!r}")


def count_expected_bars_between(
    start_utc: datetime,
    end_utc: datetime,
    *,
    interval: timedelta,
    calendar: TradingCalendar = TradingCalendar.CRYPTO_24_7,
) -> int:
    """Count expected trading bar closes strictly between `start_utc` and `end_utc`."""
    if interval <= timedelta(0):
        raise ValueError("interval must be positive")
    start = _require_utc(start_utc)
    end = _require_utc(end_utc)
    if end <= start + interval:
        return 0
    if calendar is TradingCalendar.CRYPTO_24_7:
        return max(0, int((end - start) / interval) - 1)

    missing = 0
    cursor = start + interval
    while cursor < end:
        if is_trading_bar_close(cursor, interval=interval, calendar=calendar):
            missing += 1
        cursor += interval
    return missing
