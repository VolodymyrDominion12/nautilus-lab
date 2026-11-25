"""DST-aware gold market trading sessions using stdlib IANA `zoneinfo`.

Gold liquidity and intraday range cluster around three institutional windows:
Asia (Tokyo/Shanghai/Sydney), London (LBMA open), and the London-New York overlap
(COMEX open + US macro releases at 08:30 ET). The US and UK shift daylight saving
time on different weeks in spring and autumn (e.g., 2026: US Mar 8 - Nov 1 vs UK
Mar 29 - Oct 25), so hardcoding UTC hours shifts the box and overlap by 1 hour
twice a year. Computing both clocks in `Europe/London` and `America/New_York`
keeps session boundaries exact year-round with zero external dependencies.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

LONDON_TZ = ZoneInfo("Europe/London")
NEW_YORK_TZ = ZoneInfo("America/New_York")


class GoldSession(StrEnum):
    """Institutional trading session for spot/futures gold."""

    ASIA = "asia"
    LONDON = "london"
    LONDON_NY_OVERLAP = "london_ny_overlap"
    NY_AFTERNOON = "ny_afternoon"
    OFF_HOURS = "off_hours"
    WEEKEND = "weekend"


def _require_aware(ts_utc: datetime) -> datetime:
    if ts_utc.tzinfo is None or ts_utc.utcoffset() is None:
        raise ValueError("ts_utc must be timezone-aware")
    return ts_utc


def london_trading_date(ts_utc: datetime) -> date:
    """Local calendar date in `Europe/London`, used to group one Asia->London->NY cycle."""
    return _require_aware(ts_utc).astimezone(LONDON_TZ).date()


def classify_gold_session(ts_utc: datetime) -> GoldSession:
    """Classify a timezone-aware timestamp into its DST-aware gold trading session.

    Boundary rules (all derived from IANA local clocks, never fixed UTC offsets):
    - `WEEKEND`: Friday >= 17:00 ET through Sunday < 18:00 ET (COMEX/OTC gold closure).
    - `OFF_HOURS`: daily 17:00-18:00 ET CME maintenance break, and late evening after
      NY close before 00:00 London.
    - `ASIA`: 00:00-07:00 `Europe/London` (overnight range box formation).
    - `LONDON`: 07:00-17:00 `Europe/London` while `America/New_York` is < 08:00 ET.
    - `LONDON_NY_OVERLAP`: 07:00-17:00 `Europe/London` AND `America/New_York` >= 08:00 ET
      (automatically 12:00-17:00 London during US/UK DST gap weeks, 13:00-17:00 otherwise).
    - `NY_AFTERNOON`: after 17:00 `Europe/London` while `America/New_York` is < 17:00 ET.
    """
    aware = _require_aware(ts_utc)
    ny = aware.astimezone(NEW_YORK_TZ)
    london = aware.astimezone(LONDON_TZ)

    ny_weekday = ny.weekday()  # Mon=0 .. Sun=6
    if ny_weekday == 5:
        return GoldSession.WEEKEND
    if ny_weekday == 4 and ny.hour >= 17:
        return GoldSession.WEEKEND
    if ny_weekday == 6 and ny.hour < 18:
        return GoldSession.WEEKEND

    if ny.hour == 17:
        return GoldSession.OFF_HOURS

    if 0 <= london.hour < 7:
        return GoldSession.ASIA

    if 7 <= london.hour < 17:
        if ny.hour >= 8:
            return GoldSession.LONDON_NY_OVERLAP
        return GoldSession.LONDON

    if ny.hour < 17:
        return GoldSession.NY_AFTERNOON

    return GoldSession.OFF_HOURS


def is_gold_entry_session(session: GoldSession) -> bool:
    """True during the London open and London-NY overlap entry window."""
    return session in (GoldSession.LONDON, GoldSession.LONDON_NY_OVERLAP)
