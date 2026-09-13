from decimal import Decimal

import pytest

from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.money import Money


@pytest.mark.parametrize(
    ("equity", "fraction", "expected"),
    [
        (Decimal("10000"), Decimal("0.01"), Decimal("100.00")),
        (Decimal("10000"), Decimal("0"), Decimal("0.00")),
        (Decimal("0"), Decimal("0.01"), Decimal("0.00")),
    ],
)
def test_risk_amount(equity: Decimal, fraction: Decimal, expected: Decimal) -> None:
    assert Money(equity).risk_amount(fraction) == expected


def test_negative_amount_is_rejected() -> None:
    with pytest.raises(InvalidRiskError, match="amount"):
        Money(Decimal("-1"))


def test_invalid_fraction_is_rejected() -> None:
    with pytest.raises(InvalidRiskError, match="fraction"):
        Money(Decimal("100")).risk_amount(Decimal("1.5"))
