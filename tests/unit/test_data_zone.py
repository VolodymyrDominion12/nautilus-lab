from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from nautilus_lab.domain.data_zone import (
    DEFAULT_ZONE_POLICY,
    DataZone,
    TimeWindow,
    ZonePolicy,
    base_symbol,
)
from nautilus_lab.domain.errors import InvalidWindowError

UNIVERSE = (
    "BTCUSDT",
    "ETHUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "SOLUSDT",
    "XRPUSDT",
)


def _utc(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def test_base_symbol_normalises_engine_and_perp_spellings() -> None:
    assert base_symbol("btcusdt-PERP.SIM") == "BTCUSDT"
    assert base_symbol("ETHUSDT") == "ETHUSDT"


def test_default_time_zones_follow_the_agreed_split() -> None:
    policy = DEFAULT_ZONE_POLICY
    assert policy.time_zone(_utc(2020, 6)) is DataZone.EXPLORATION
    assert policy.time_zone(_utc(2022, 6)) is DataZone.HOLDOUT
    assert policy.time_zone(_utc(2023, 6)) is DataZone.EXPLORATION
    assert policy.time_zone(_utc(2025, 6)) is DataZone.VALIDATION
    assert policy.time_zone(_utc(2026, 8)) is DataZone.HOLDOUT
    assert policy.time_zone(_utc(2026, 10, 2)) is None  # not assigned yet


def test_windows_are_half_open() -> None:
    policy = DEFAULT_ZONE_POLICY
    assert policy.time_zone(_utc(2022)) is DataZone.HOLDOUT
    assert policy.time_zone(_utc(2024)) is DataZone.VALIDATION


def test_market_anchors_are_never_held_out() -> None:
    policy = ZonePolicy(
        exploration=(), validation=(), holdout=(), holdout_symbol_fraction=Decimal("0.99")
    )
    assert not policy.symbol_is_holdout("BTCUSDT-PERP.SIM")
    assert not policy.symbol_is_holdout("ETHUSDT")


def test_symbol_split_is_stable_when_the_universe_grows() -> None:
    policy = DEFAULT_ZONE_POLICY
    before = set(policy.holdout_symbols(UNIVERSE))
    after = set(policy.holdout_symbols([*UNIVERSE, "SUIUSDT", "TONUSDT", "APTUSDT"]))
    assert before <= after
    assert before == {s for s in after if s in UNIVERSE}


def test_held_out_coin_is_holdout_on_every_date() -> None:
    policy = DEFAULT_ZONE_POLICY
    held = policy.holdout_symbols(UNIVERSE)
    assert held, "the default split should hold out at least one of 11 coins"
    assert policy.zone(_utc(2020, 6), held[0]) is DataZone.HOLDOUT
    research = policy.research_symbols(UNIVERSE)
    assert set(research) | set(held) == set(UNIVERSE)
    assert policy.zone(_utc(2020, 6), research[0]) is DataZone.EXPLORATION


def test_overlapping_windows_are_rejected() -> None:
    with pytest.raises(InvalidWindowError, match="overlap"):
        ZonePolicy(
            exploration=(TimeWindow(_utc(2020), _utc(2022)),),
            validation=(TimeWindow(_utc(2021), _utc(2023)),),
            holdout=(),
        )


def test_naive_or_empty_windows_are_rejected() -> None:
    with pytest.raises(InvalidWindowError):
        TimeWindow(datetime(2020, 1, 1), _utc(2021))  # noqa: DTZ001 - the point of the test
    with pytest.raises(InvalidWindowError):
        TimeWindow(_utc(2021), _utc(2021))
