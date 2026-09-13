from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from nautilus_lab.domain.bars import OhlcvBar, validate_bar
from nautilus_lab.domain.errors import InvalidBarError


def _bar(
    *,
    ts_utc: datetime | None = None,
    high: Decimal | None = None,
    open: Decimal = Decimal("100"),
    close: Decimal = Decimal("100.5"),
    low: Decimal = Decimal("99"),
    volume: Decimal = Decimal("1"),
) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts_utc or datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        open=open,
        high=high if high is not None else Decimal("101"),
        low=low,
        close=close,
        volume=volume,
    )


def test_valid_bar_is_accepted() -> None:
    validate_bar(_bar(), now=datetime(2024, 1, 2, tzinfo=UTC))


def test_inverted_high_is_rejected() -> None:
    with pytest.raises(InvalidBarError, match="high"):
        validate_bar(_bar(high=Decimal("100")))


def test_inverted_low_is_rejected() -> None:
    with pytest.raises(InvalidBarError, match="low"):
        validate_bar(_bar(low=Decimal("100.6")))


def test_future_bar_is_rejected() -> None:
    with pytest.raises(InvalidBarError, match="future"):
        validate_bar(_bar(), now=datetime(2023, 12, 31, tzinfo=UTC))


def test_non_monotonic_timestamps_are_rejected() -> None:
    first = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(InvalidBarError, match="increasing"):
        validate_bar(_bar(ts_utc=first), previous_ts=first)


def test_non_utc_offset_is_rejected() -> None:
    kyiv = datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
    with pytest.raises(InvalidBarError, match="UTC"):
        validate_bar(_bar(ts_utc=kyiv))


def test_negative_volume_is_rejected() -> None:
    with pytest.raises(InvalidBarError, match="volume"):
        validate_bar(_bar(volume=Decimal("-1")))


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(InvalidBarError, match="timezone-aware"):
        validate_bar(_bar(ts_utc=datetime(2024, 1, 1, 12, 0)))
