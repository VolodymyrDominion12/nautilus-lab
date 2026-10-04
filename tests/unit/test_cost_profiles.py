"""Cost scenarios: the tariff a run pays, and the stress case it is judged against.

Costs are the lever that decides whether a strategy survives — in the 2026-10 batches the
gross return was positive almost everywhere while fees ate it — so "which costs did this
run pay" is a value with a name, recorded in the run manifest, not a habit (docs/33 §4).
These tests pin the registry, the settings application, the batch dimension and the
manifest line.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from nautilus_lab.application.batch_plan import BatchRequest, BatchVariant, plan_cells
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.fees import (
    BINANCE_VIP0_BNB,
    COST_PROFILES,
    DEFAULT_COST_PROFILE,
    cost_profile,
)
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import run_manifest


def test_the_registry_names_every_scenario_and_is_self_consistent() -> None:
    """A profile's name is its key, and each one is a usable schedule."""
    assert DEFAULT_COST_PROFILE in COST_PROFILES
    for name, profile in COST_PROFILES.items():
        assert profile.name == name, "the key is what a run records"
        assert profile.note, "a scenario a reader cannot interpret is not worth naming"
        assert profile.spot_taker >= profile.spot_maker


def test_the_stress_scenario_is_the_base_tariff_times_one_and_a_half() -> None:
    """The stress case is defined, not hand-tuned: 1.5x the tariff the account has."""
    stress = cost_profile("stress_x1_5")
    assert stress.spot_taker == BINANCE_VIP0_BNB.spot_taker * Decimal("1.5")
    assert stress.usdm_taker == BINANCE_VIP0_BNB.usdm_taker * Decimal("1.5")
    assert stress.spot_taker > BINANCE_VIP0_BNB.spot_taker, "stress must cost more"


def test_an_unknown_profile_fails_closed_instead_of_paying_base_fees() -> None:
    """A typo must stop the run: paying the wrong tariff silently is a wrong experiment."""
    with pytest.raises(InvalidRiskError, match="unknown cost profile"):
        cost_profile("stress_x2")
    # `Settings` reports it as a validation error (that is how a bad .env fails a run);
    # the message still names the typo and lists what exists.
    with pytest.raises(ValidationError, match="unknown cost profile"):
        Settings(  # type: ignore[call-arg]
            _env_file=None, cost_profile="bnb_typo"
        )
    with pytest.raises(InvalidRiskError, match="must be > 0"):
        BINANCE_VIP0_BNB.stressed(Decimal("0"), name="zero")


def test_a_named_profile_is_the_schedule() -> None:
    """The profile wins over the fee fields, so a run cannot claim one scenario and pay another."""
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        cost_profile="stress_x1_5",
        spot_taker_fee=Decimal("0.001"),
    )
    assert settings.spot_taker_fee == cost_profile("stress_x1_5").spot_taker
    assert settings.usdm_taker_fee == cost_profile("stress_x1_5").usdm_taker

    # No profile named: the fields are used as written (the old behaviour, unchanged).
    plain = Settings(  # type: ignore[call-arg]
        _env_file=None, spot_taker_fee=Decimal("0.002")
    )
    assert plain.spot_taker_fee == Decimal("0.002")


def test_the_manifest_says_which_costs_the_run_paid() -> None:
    """`paid_cost_bps` alone cannot tell a base run from a stressed one; the name can."""
    stressed = run_manifest(
        Settings(  # type: ignore[call-arg]
            _env_file=None, cost_profile="stress_x1_5"
        ),
        with_catalog=False,
    )
    assert stressed.cost_profile == "stress_x1_5"
    assert "cost=stress_x1_5" in stressed.summary_line()

    unnamed = run_manifest(Settings(_env_file=None), with_catalog=False)  # type: ignore[call-arg]
    assert unnamed.cost_profile is None
    assert "cost=" not in unnamed.summary_line()


def test_a_batch_can_run_one_hypothesis_at_two_cost_scenarios() -> None:
    """The stress case is a variant, not a second batch: same cells, named scenarios."""
    request = BatchRequest(
        robots=("regime",),
        symbols=("BTCUSDT",),
        cost_profile="binance_vip0_bnb",
        variants=(
            BatchVariant("BASE", {"REGIME_LEGS": "uptrend,range"}),
            BatchVariant("STRESS", {"REGIME_LEGS": "uptrend,range"}, cost_profile="stress_x1_5"),
        ),
    )
    cells = {cell.cell_id: cell for cell in plan_cells(request, exists=lambda _path: True)}

    assert cells["regime_BTC__BASE"].cost_profile == "binance_vip0_bnb"
    assert cells["regime_BTC__STRESS"].cost_profile == "stress_x1_5"
    # The child process learns it the same way it learns every other setting.
    assert cells["regime_BTC__BASE"].env["COST_PROFILE"] == "binance_vip0_bnb"
    assert cells["regime_BTC__STRESS"].env["COST_PROFILE"] == "stress_x1_5"


def test_a_variant_that_only_names_a_cost_scenario_is_still_a_variant() -> None:
    """Overriding costs is a hypothesis about the edge, so the variant needs no other env."""
    variant = BatchVariant("COST-STRESS", cost_profile="stress_x1_5")
    request = BatchRequest(robots=("ema",), symbols=("BTCUSDT",), variants=(variant,))
    (cell,) = plan_cells(request, exists=lambda _path: True)
    assert cell.env == {"COST_PROFILE": "stress_x1_5"}

    with pytest.raises(ValueError, match="overrides nothing"):
        BatchVariant("EMPTY")
