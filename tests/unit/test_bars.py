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
    taker_buy_base_volume: Decimal | None = None,
) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts_utc or datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
        open=open,
        high=high if high is not None else Decimal("101"),
        low=low,
        close=close,
        volume=volume,
        taker_buy_base_volume=taker_buy_base_volume,
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
        validate_bar(_bar(ts_utc=datetime(2024, 1, 1, 12, 0)))  # noqa: DTZ001 — naive on purpose


def test_taker_split_is_unknown_by_default_and_the_sell_side_is_derived() -> None:
    """`None` means unknown, and the sell side is arithmetic, never a second field."""
    unknown = _bar(volume=Decimal("10"))
    assert unknown.taker_buy_base_volume is None
    assert unknown.taker_sell_base_volume is None

    known = _bar(volume=Decimal("10"), taker_buy_base_volume=Decimal("4"))
    validate_bar(known)
    assert known.taker_sell_base_volume == Decimal("6")


def test_taker_volume_above_bar_volume_is_rejected() -> None:
    """Takers cannot buy more base than the bar traded — a mismatch must fail loudly."""
    with pytest.raises(InvalidBarError, match="taker buy"):
        validate_bar(_bar(volume=Decimal("10"), taker_buy_base_volume=Decimal("11")))


def test_negative_taker_volume_is_rejected() -> None:
    with pytest.raises(InvalidBarError, match="taker buy"):
        validate_bar(_bar(volume=Decimal("10"), taker_buy_base_volume=Decimal("-1")))


def test_fully_aggressive_buy_bar_is_valid() -> None:
    """A bar where buyers took everything is a real observation, not an edge case."""
    bar = _bar(volume=Decimal("10"), taker_buy_base_volume=Decimal("10"))
    validate_bar(bar)
    assert bar.taker_sell_base_volume == Decimal("0")
