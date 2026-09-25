"""Regression tests for bugs found in the audit.

Each test names the failure it pins down, so a future refactor that reintroduces the
behaviour fails loudly instead of silently changing research results.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.atr import AverageTrueRange
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.funding import FundingCashAndCarry, FundingParams, FundingSnapshot
from nautilus_lab.domain.glft import GlftMarketMaker, GlftParams
from nautilus_lab.domain.portfolio_risk import historical_var
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type

_ALL_INTERVALS = ("1m", "5m", "15m", "1h", "4h", "1d")


def _bar(ts: datetime, high: str, low: str, close: str) -> OhlcvBar:
    return OhlcvBar(
        instrument_id="ETH/USDT.SIM",
        ts_utc=ts,
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
    )


# --------------------------------------------------------------------------- timeframe


@pytest.mark.parametrize("interval", _ALL_INTERVALS)
def test_interval_round_trips_through_bar_type(interval: str) -> None:
    bar_type = nautilus_bar_type("ETH/USDT.SIM", interval)
    assert interval_from_bar_type(bar_type) == interval


def test_quarter_hour_is_not_read_as_five_minutes() -> None:
    """`"15-MINUTE"` contains `"5-MINUTE"`; a substring test returned 5m for a 15m run."""
    assert interval_from_bar_type("ETH/USDT.SIM-15-MINUTE-LAST-EXTERNAL") == "15m"


def test_interval_parsing_handles_a_perpetual_instrument_id() -> None:
    """`ETHUSDT-PERP.SIM` already contains a dash, so the spec must be matched whole."""
    assert interval_from_bar_type("ETHUSDT-PERP.SIM-1-HOUR-LAST-EXTERNAL") == "1h"


def test_unknown_spec_is_rejected_instead_of_defaulting_to_one_hour() -> None:
    with pytest.raises(ValueError, match="cannot read a bar interval"):
        interval_from_bar_type("ETH/USDT.SIM-3-HOUR-LAST-EXTERNAL")


# ------------------------------------------------------------------------------ ATR


def test_atr_uses_wilders_recursion_not_a_rolling_mean() -> None:
    """A shock must decay gradually, not vanish after exactly `period` bars.

    Wilder: ATR_t = (ATR_{t-1} * (n - 1) + TR_t) / n. A rolling mean of the last `n`
    true ranges would drop the spike completely on bar n + 1.
    """
    atr = AverageTrueRange(3)
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    quiet = [_bar(origin + timedelta(hours=index), "101", "99", "100") for index in range(3)]
    for bar in quiet:
        atr.update(bar)
    assert atr.value == Decimal("2")  # seed = mean(2, 2, 2)

    spike = _bar(origin + timedelta(hours=3), "130", "100", "130")
    atr.update(spike)
    spiked = atr.value
    assert spiked is not None
    assert spiked > Decimal("2")

    # Three more quiet bars: with a rolling mean of 3 the spike would be gone by now.
    for index in range(4, 7):
        atr.update(_bar(origin + timedelta(hours=index), "131", "129", "130"))
    decayed = atr.value
    assert decayed is not None
    assert Decimal("2") < decayed < spiked


def test_atr_period_one_is_the_true_range() -> None:
    atr = AverageTrueRange(1)
    bar = _bar(datetime(2024, 1, 1, tzinfo=UTC), "110", "100", "105")
    assert atr.update(bar) == Decimal("10")


# ------------------------------------------------------------------------------- VaR


def test_var_99_picks_the_worst_return_on_a_hundred_point_sample() -> None:
    """`int((1 - 0.99) * 100)` skipped the worst point and returned the second worst."""
    returns = tuple(Decimal("-0.01") * (index + 1) for index in range(100))
    var = historical_var(returns, confidence=Decimal("0.99"))
    assert var == Decimal("1.00")


def test_var_95_matches_the_empirical_quantile() -> None:
    # Losses run -0.01 .. -1.00, so the 5th worst observation is -0.96.
    returns = tuple(Decimal("-0.01") * (index + 1) for index in range(100))
    assert historical_var(returns, confidence=Decimal("0.95")) == Decimal("0.96")


def test_var_of_an_all_positive_sample_is_zero() -> None:
    assert historical_var((Decimal("0.01"), Decimal("0.02"))) == Decimal("0")


# ---------------------------------------------------------------------------- funding


def _snapshot(rate: str, mark: str = "3500", index: str = "3495") -> FundingSnapshot:
    return FundingSnapshot(
        instrument="ETHUSDT",
        funding_rate=Decimal(rate),
        mark_price=Decimal(mark),
        index_price=Decimal(index),
        ts_utc=datetime(2024, 1, 1, tzinfo=UTC),
    )


def test_funding_trades_a_realistic_binance_rate() -> None:
    """0.01% per 8h (~10.95% APY) must be reachable at a 10% gate.

    Charging the full round-trip taker fee against every funding interval instead
    needs a rate above 0.1% per 8h (~109% APY), so the robot could never open.
    """
    strategy = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM",
        perp_id="ETHUSDT-PERP.SIM",
        params=FundingParams(holding_periods=90),
    )
    signal = strategy.on_funding(_snapshot("0.00012"))
    assert signal is not None
    assert signal.reason == "funding cash-and-carry"


def test_funding_rejects_a_zero_index_price_instead_of_dividing_by_it() -> None:
    strategy = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM",
        perp_id="ETHUSDT-PERP.SIM",
        params=FundingParams(),
    )
    assert strategy.on_funding(_snapshot("0.01", index="0")) is None


def test_funding_closes_an_open_position_when_the_index_price_vanishes() -> None:
    strategy = FundingCashAndCarry(
        spot_id="ETH/USDT.SIM",
        perp_id="ETHUSDT-PERP.SIM",
        params=FundingParams(min_net_apy=Decimal("0.01")),
    )
    assert strategy.on_funding(_snapshot("0.01")) is not None
    exit_signal = strategy.on_funding(_snapshot("0.01", index="0"))
    assert exit_signal is not None
    assert exit_signal.reason == "missing index price"


def test_funding_params_validate_holding_periods() -> None:
    with pytest.raises(ValueError, match="holding_periods"):
        FundingParams(holding_periods=0)


# ------------------------------------------------------------------------------- GLFT


def test_glft_long_inventory_skews_both_quotes_down() -> None:
    """The document's qualitative rule: long inventory lowers Bid *and* Ask."""
    maker = GlftMarketMaker(
        instrument_id="ETH/USDT.SIM",
        params=GlftParams(gamma=Decimal("0.1"), base_half_spread_bps=Decimal("5")),
    )
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    flat = maker.quote(
        mid=Decimal("3500"), inventory=Decimal("0"), volatility=Decimal("20"), ts_utc=ts
    )
    long_inventory = maker.quote(
        mid=Decimal("3500"), inventory=Decimal("1"), volatility=Decimal("20"), ts_utc=ts
    )
    assert long_inventory.bid_price < flat.bid_price
    assert long_inventory.ask_price < flat.ask_price
    # The skew now scales with variance, exactly like the spread term.
    assert flat.bid_price - long_inventory.bid_price == Decimal("40")


def test_glft_quotes_stay_ordered_around_the_mid() -> None:
    maker = GlftMarketMaker(instrument_id="ETH/USDT.SIM", params=GlftParams())
    quote = maker.quote(
        mid=Decimal("3500"),
        inventory=Decimal("-1"),
        volatility=Decimal("20"),
        ts_utc=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert quote.bid_price < quote.ask_price
