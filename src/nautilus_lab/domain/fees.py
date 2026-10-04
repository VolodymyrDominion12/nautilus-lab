from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.errors import InvalidRiskError


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """Exchange fee schedule in decimal fractions (not bps)."""

    maker: Decimal
    taker: Decimal

    def __post_init__(self) -> None:
        if self.maker < 0 or self.taker < 0:
            raise InvalidRiskError("fees must be >= 0")
        if self.maker > Decimal("0.01") or self.taker > Decimal("0.01"):
            raise InvalidRiskError("fees look too large; use decimal fractions")

    @classmethod
    def binance_spot_vip0(cls) -> FeeSchedule:
        """Conservative VIP0 spot defaults from MFT doc (0.10% maker/taker)."""
        return cls(maker=Decimal("0.001"), taker=Decimal("0.001"))

    @classmethod
    def binance_usdm_vip0(cls) -> FeeSchedule:
        """Conservative VIP0 USD-M futures defaults (0.020% / 0.050%)."""
        return cls(maker=Decimal("0.0002"), taker=Decimal("0.0005"))


@dataclass(frozen=True, slots=True)
class CostProfile:
    """A named cost scenario: one tariff, or a stress multiplier on it.

    Costs decide whether an edge survives — in the 2026-10 batches the gross return was
    positive almost everywhere while fees ate it — so "which costs did this run pay" has to
    be a value, not a habit. Two scenarios are the point (docs/33 §4): the tariff the
    account really has, and a stress case that stands in for slippage and for the BNB
    discount disappearing.

    The market is not part of the profile: spot and USD-M tariffs are both carried, and the
    instrument decides which one a fill pays. A carry run pays both, which is why the two
    schedules live together.
    """

    name: str
    spot_maker: Decimal
    spot_taker: Decimal
    usdm_maker: Decimal
    usdm_taker: Decimal
    note: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidRiskError("a cost profile needs a name")
        # Same bounds the schedules enforce, checked here so a bad profile fails at import
        # of the registry rather than in the middle of a run.
        FeeSchedule(self.spot_maker, self.spot_taker)
        FeeSchedule(self.usdm_maker, self.usdm_taker)

    def stressed(self, factor: Decimal, *, name: str, note: str = "") -> CostProfile:
        """The same tariffs multiplied by `factor` — how the stress scenario is defined."""
        if factor <= 0:
            raise InvalidRiskError("a stress factor must be > 0")
        round_to = Decimal("0.0000001")
        return CostProfile(
            name=name,
            spot_maker=(self.spot_maker * factor).quantize(round_to),
            spot_taker=(self.spot_taker * factor).quantize(round_to),
            usdm_maker=(self.usdm_maker * factor).quantize(round_to),
            usdm_taker=(self.usdm_taker * factor).quantize(round_to),
            note=note,
        )


#: Binance VIP0 with the BNB discount: what the project's account actually pays today.
BINANCE_VIP0_BNB = CostProfile(
    name="binance_vip0_bnb",
    spot_maker=Decimal("0.00075"),
    spot_taker=Decimal("0.00075"),
    usdm_maker=Decimal("0.0002"),
    usdm_taker=Decimal("0.0005"),
    note="Binance VIP0 з оплатою комісій у BNB: спот 7.5 bps, USD-M 2/5 bps",
)

#: The same account without the BNB discount.
BINANCE_VIP0_NO_BNB = CostProfile(
    name="binance_vip0_no_bnb",
    spot_maker=Decimal("0.001"),
    spot_taker=Decimal("0.001"),
    usdm_maker=Decimal("0.00022"),
    usdm_taker=Decimal("0.00055"),
    note="Binance VIP0 без BNB: спот 10 bps, USD-M 2.2/5.5 bps",
)

#: Stress: base tariff x1.5, standing in for slippage beyond the fill model and for the
#: discount vanishing. A strategy whose edge needs the exact tariff is not robust, and
#: "breakeven > paid + 5 bps" (GateCriteria) is what this scenario puts to the test.
COST_STRESS_X1_5 = BINANCE_VIP0_BNB.stressed(
    Decimal("1.5"),
    name="stress_x1_5",
    note="стрес: базовий тариф x1.5 (проковзування понад модель філу або втрата знижки BNB)",
)

COST_PROFILES: dict[str, CostProfile] = {
    profile.name: profile for profile in (BINANCE_VIP0_BNB, BINANCE_VIP0_NO_BNB, COST_STRESS_X1_5)
}

#: What a run uses when nothing says otherwise: the tariff the account actually has.
DEFAULT_COST_PROFILE = BINANCE_VIP0_BNB.name


def cost_profile(name: str) -> CostProfile:
    """Look a profile up by name; an unknown name fails closed, never falls back."""
    try:
        return COST_PROFILES[name]
    except KeyError:
        allowed = ", ".join(sorted(COST_PROFILES))
        raise InvalidRiskError(
            f"unknown cost profile {name!r}; known profiles: {allowed}"
        ) from None
