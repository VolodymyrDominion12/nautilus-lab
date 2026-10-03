from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from nautilus_lab.domain.funding import (
    FundingCashAndCarry,
    FundingParams,
    FundingSnapshot,
)
from nautilus_lab.domain.signals import SignalSide


def _snapshot(
    *,
    funding_rate: Decimal = Decimal("0.0005"),
    mark_price: Decimal | None = Decimal("50000"),
    index_price: Decimal | None = Decimal("50000"),
    ts: datetime | None = None,
) -> FundingSnapshot:
    return FundingSnapshot(
        instrument="BTCUSDT-PERP.SIM",
        funding_rate=funding_rate,
        mark_price=mark_price,
        index_price=index_price,
        ts_utc=ts or datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_funding_params_validation() -> None:
    params = FundingParams(
        min_net_apy=Decimal("0.05"),
        taker_fee=Decimal("0.0005"),
        holding_periods=60,
        min_exit_apy=Decimal("0.01"),
        min_holding_periods=15,
    )
    assert params.holding_periods == 60
    assert params.min_exit_apy == Decimal("0.01")
    assert params.min_holding_periods == 15

    with pytest.raises(ValueError, match="taker_fee must be >= 0"):
        FundingParams(taker_fee=Decimal("-0.001"))

    with pytest.raises(ValueError, match="holding_periods must be >= 1"):
        FundingParams(holding_periods=0)

    with pytest.raises(ValueError, match="min_holding_periods must be >= 0"):
        FundingParams(min_holding_periods=-1)

    with pytest.raises(ValueError, match="basis_max must be >= 0"):
        FundingParams(basis_max=Decimal("-0.005"))


def test_funding_cash_and_carry_entry_gates() -> None:
    # 0.0005 per 8h ~ 54.75% APY, fee drag = (0.0005 * 2 / 60) * 1095 = 1.825% APY
    # net APY ~ 52.9% > min_net_apy (10%)
    params = FundingParams(
        min_net_apy=Decimal("0.10"),
        taker_fee=Decimal("0.0005"),
        holding_periods=60,
        basis_max=Decimal("0.005"),
    )
    carry = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )

    # 1. Normal entry when APY is high and basis is tight
    sig = carry.on_funding(_snapshot(funding_rate=Decimal("0.0005")))
    assert sig is not None
    assert sig.leg_a.side == SignalSide.BUY
    assert sig.leg_b.side == SignalSide.SELL
    assert carry.periods_held == 0

    # 2. Reset and test rejection when funding is too low
    carry2 = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    # Low rate: 0.00001 per 8h ~ 1.095% APY < fee drag (1.825%) -> net APY < 0
    sig_low = carry2.on_funding(_snapshot(funding_rate=Decimal("0.00001")))
    assert sig_low is None
    assert carry2.last_trace[-1].note == "net APY after fees below min_net_apy"

    # 3. Rejection when basis diverges |(mark - index)/index| > basis_max (0.005)
    carry3 = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    sig_divergent = carry3.on_funding(
        _snapshot(
            funding_rate=Decimal("0.0005"),
            mark_price=Decimal("51000"),
            index_price=Decimal("50000"),  # divergence = 2% > 0.5%
        )
    )
    assert sig_divergent is None
    assert carry3.last_trace[-1].note == "APY passes but |basis| above basis_max"


def test_funding_negative_exit() -> None:
    params = FundingParams(
        min_net_apy=Decimal("0.05"),
        holding_periods=60,
        close_on_negative=True,
    )
    carry = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)

    # Entry
    assert carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts)) is not None

    # Next interval: funding turns negative (-0.0001)
    sig_exit = carry.on_funding(
        _snapshot(funding_rate=Decimal("-0.0001"), ts=ts + timedelta(hours=8))
    )
    assert sig_exit is not None
    assert sig_exit.leg_a.side == SignalSide.FLAT
    assert sig_exit.leg_b.side == SignalSide.FLAT
    assert sig_exit.reason == "negative funding"
    assert carry.periods_held == 0


def test_funding_default_holds_through_negative_blip() -> None:
    # Default close_on_negative is False: position is held through minor negative funding blip
    params = FundingParams(
        min_net_apy=Decimal("0.05"),
        holding_periods=60,
    )
    assert not params.close_on_negative
    carry = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)

    # Entry
    assert carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts)) is not None

    # Next interval: minor negative blip (-0.00001)
    sig_hold = carry.on_funding(
        _snapshot(funding_rate=Decimal("-0.00001"), ts=ts + timedelta(hours=8))
    )
    assert sig_hold is None
    assert carry.periods_held == 1
    assert carry.last_trace[-1].note == "carry still valid: hold"


def test_funding_basis_divergence_exit() -> None:
    params = FundingParams(
        min_net_apy=Decimal("0.05"),
        holding_periods=60,
        basis_max=Decimal("0.005"),
    )
    carry = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)

    # Entry
    assert carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts)) is not None

    # Next interval: basis blows out to 1%
    sig_exit = carry.on_funding(
        _snapshot(
            funding_rate=Decimal("0.0005"),
            mark_price=Decimal("50500"),
            index_price=Decimal("50000"),
            ts=ts + timedelta(hours=8),
        )
    )
    assert sig_exit is not None
    assert sig_exit.leg_a.side == SignalSide.FLAT
    assert sig_exit.reason == "basis divergence"


def test_funding_decay_exit_and_retention_protection() -> None:
    # Exit threshold 2% APY, protected for min 3 periods
    params = FundingParams(
        min_net_apy=Decimal("0.05"),
        holding_periods=60,
        min_exit_apy=Decimal("0.02"),
        min_holding_periods=3,
    )
    carry = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)

    # Entry on strong rate (50% APY)
    sig_entry = carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts))
    assert sig_entry is not None
    assert carry.periods_held == 0

    # Low rate giving ~0.5% net APY (below min_exit_apy of 2%)
    # fee drag = (0.0005 * 2 / 60) * 1095 = 1.825%
    # gross funding rate 0.000021 ~ 2.3% APY -> net APY ~ 0.47%
    low_rate_snap = _snapshot(
        funding_rate=Decimal("0.000021"),
        ts=ts + timedelta(hours=8),
    )

    # Interval 1: held = 1 < min_holding_periods (3) -> Must NOT exit, protection active!
    sig1 = carry.on_funding(low_rate_snap)
    assert sig1 is None
    assert carry.periods_held == 1
    assert carry.last_trace[-1].note == "carry still valid: hold"

    # Interval 2: held = 2 < min_holding_periods (3) -> Must NOT exit!
    sig2 = carry.on_funding(
        _snapshot(funding_rate=Decimal("0.000021"), ts=ts + timedelta(hours=16))
    )
    assert sig2 is None
    assert carry.periods_held == 2

    # Interval 3: held = 3 >= min_holding_periods (3) and net APY < min_exit_apy -> DECAY EXIT!
    sig3 = carry.on_funding(
        _snapshot(funding_rate=Decimal("0.000021"), ts=ts + timedelta(hours=24))
    )
    assert sig3 is not None
    assert sig3.leg_a.side == SignalSide.FLAT
    assert sig3.leg_b.side == SignalSide.FLAT
    assert sig3.reason == "funding decayed below min_exit_apy"
    assert carry.periods_held == 0


def test_holding_periods_amortisation_math() -> None:
    # With holding_periods = 60, taker_fee = 0.00125:
    # Round-trip fee drag per year = (0.00125 * 2 / 60) * 1095 = 4.5625% APY
    params_60 = FundingParams(taker_fee=Decimal("0.00125"), holding_periods=60)
    carry_60 = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM", perp_id="BTCUSDT-PERP.SIM", params=params_60
    )
    fee_per_interval_60 = carry_60._round_trip_fee_per_interval()
    annual_fee_drag_60 = fee_per_interval_60 * Decimal("3") * Decimal("365")
    assert round(annual_fee_drag_60, 4) == Decimal("0.0456")

    # With holding_periods = 15:
    # Round-trip fee drag per year = (0.00125 * 2 / 15) * 1095 = 18.25% APY
    params_15 = FundingParams(taker_fee=Decimal("0.00125"), holding_periods=15)
    carry_15 = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM", perp_id="BTCUSDT-PERP.SIM", params=params_15
    )
    fee_per_interval_15 = carry_15._round_trip_fee_per_interval()
    annual_fee_drag_15 = fee_per_interval_15 * Decimal("3") * Decimal("365")
    assert annual_fee_drag_15 == Decimal("0.1825")


def test_funding_max_holding_periods_exit() -> None:
    params = FundingParams(
        min_net_apy=Decimal("0.05"),
        holding_periods=60,
        max_holding_periods=3,
    )
    carry = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)

    # Entry
    assert carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts)) is not None
    assert carry.is_open
    assert carry.periods_held == 0

    # Interval 1: held = 1 < 3
    sig1 = carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts + timedelta(hours=8)))
    assert sig1 is None
    assert carry.periods_held == 1

    # Interval 2: held = 2 < 3
    sig2 = carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts + timedelta(hours=16)))
    assert sig2 is None
    assert carry.periods_held == 2

    # Interval 3: held = 3 >= max_holding_periods (3) -> timeout exit!
    sig3 = carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts + timedelta(hours=24)))
    assert sig3 is not None
    assert sig3.leg_a.side == SignalSide.FLAT
    assert sig3.leg_b.side == SignalSide.FLAT
    assert sig3.reason == "max holding periods reached"
    assert not carry.is_open
    assert carry.periods_held == 0


def test_funding_abort_entry_and_is_open_sync() -> None:
    params = FundingParams(
        min_net_apy=Decimal("0.05"),
        holding_periods=60,
    )
    carry = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM",
        perp_id="BTCUSDT-PERP.SIM",
        params=params,
    )
    ts = datetime(2026, 1, 1, tzinfo=UTC)

    # 1. Emit entry
    assert carry.on_funding(_snapshot(funding_rate=Decimal("0.0005"), ts=ts)) is not None
    assert carry.is_open

    # 2. Entry aborted (e.g. warmup, risk refusal, sizing skip)
    carry.abort_entry()
    assert not carry.is_open
    assert carry.periods_held == 0

    # 3. Next settlement receives is_open=False explicitly from execution layer
    # If conditions still pass, it can emit entry again rather than saying "carry still valid: hold"
    sig_retry = carry.on_funding(
        _snapshot(funding_rate=Decimal("0.0005"), ts=ts + timedelta(hours=8)),
        is_open=False,
    )
    assert sig_retry is not None
    assert sig_retry.leg_a.side == SignalSide.BUY


def test_unknown_mark_means_unknown_basis_not_a_flat_one() -> None:
    # Pre-2023 Binance settlements carry no mark. The settlement is kept, but its
    # basis is "unknown", never 0: a flat basis would let the entry gate pass blind.
    snapshot = _snapshot(mark_price=None)
    assert snapshot.basis() is None

    robot = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM", perp_id="BTCUSDT-PERP.SIM", params=FundingParams()
    )
    assert robot.on_funding(snapshot) is None
    (trace,) = robot.last_trace
    assert trace.note == "mark price unknown: basis cannot be judged"


def test_unknown_mark_closes_an_open_carry() -> None:
    robot = FundingCashAndCarry(
        spot_id="BTC/USDT.SIM", perp_id="BTCUSDT-PERP.SIM", params=FundingParams()
    )
    signal = robot.on_funding(_snapshot(mark_price=None), is_open=True)
    assert signal is not None
    assert signal.leg_a.side is SignalSide.FLAT
    assert signal.reason == "missing mark price"
