from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from nautilus_lab.infrastructure.nautilus.instrument import (
    clear_registry_cache,
    decimal_places,
    infer_precision,
    register_instrument,
    registered_instrument_ids,
    resolve_instrument,
    supported_instrument_ids,
)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "instruments.json"
    monkeypatch.setenv("NAUTILUS_LAB_INSTRUMENTS", str(path))
    clear_registry_cache()
    yield path
    clear_registry_cache()


def test_decimal_places_ignore_trailing_zeros() -> None:
    assert decimal_places(Decimal("7195.24000000")) == 2
    assert decimal_places(Decimal("0.00001234")) == 8
    assert decimal_places(Decimal("100")) == 0
    assert decimal_places(Decimal("0")) == 0


def test_infer_precision_takes_the_finest_value_capped_at_eight() -> None:
    assert infer_precision([Decimal("1.5"), Decimal("1.2345")]) == 4
    assert infer_precision([Decimal("0.000000001")]) == 8
    assert infer_precision([]) == 0


def test_a_registered_spot_coin_resolves_with_its_derived_precision(
    isolated_registry: Path,
) -> None:
    assert register_instrument("PEPE/USDT.SIM", price_precision=8, size_precision=0, source="test")
    instrument = resolve_instrument("PEPE/USDT.SIM")
    assert instrument.price_precision == 8
    assert instrument.size_precision == 0
    assert "PEPE/USDT.SIM" in registered_instrument_ids()
    stored = json.loads(isolated_registry.read_text())
    assert stored["PEPE/USDT.SIM"]["base"] == "PEPE"


def test_a_registered_perp_resolves_as_a_perpetual() -> None:
    register_instrument("WIFUSDT-PERP.SIM", price_precision=4, size_precision=1, source="test")
    instrument = resolve_instrument("WIFUSDT-PERP.SIM")
    assert type(instrument).__name__ == "CryptoPerpetual"
    assert instrument.price_precision == 4


def test_precision_only_widens() -> None:
    register_instrument("ARB/USDT.SIM", price_precision=4, size_precision=1, source="test")
    register_instrument("ARB/USDT.SIM", price_precision=2, size_precision=0, source="test")
    assert resolve_instrument("ARB/USDT.SIM").price_precision == 4
    register_instrument("ARB/USDT.SIM", price_precision=5, size_precision=1, source="test")
    assert resolve_instrument("ARB/USDT.SIM").price_precision == 5


def test_curated_ids_are_never_overridden() -> None:
    assert not register_instrument(
        "BTC/USDT.SIM", price_precision=8, size_precision=8, source="test"
    )
    assert resolve_instrument("BTC/USDT.SIM").price_precision == 2
    assert "BTC/USDT.SIM" in supported_instrument_ids()
    assert registered_instrument_ids() == ()


def test_an_unregistered_unknown_id_still_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported instrument_id"):
        resolve_instrument("NOPE/USDT.SIM")
