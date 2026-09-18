"""Empirical quantile used by the `pairs` entry gate.

The helper is pure `Decimal` (no numpy inside `domain/`), so it is checked
against the definition it claims to implement — the type-7 linear-interpolation
quantile that numpy defaults to — rather than against hand-copied numbers alone.
"""

from decimal import Decimal

import pytest

from nautilus_lab.domain.quantiles import empirical_quantile


def test_half_quantile_interpolates_between_the_two_middle_points() -> None:
    # n = 4, h = (4 - 1) * 0.5 = 1.5 -> halfway between the 2nd and 3rd points.
    assert empirical_quantile(_values("1", "2", "3", "4"), Decimal("0.5")) == Decimal("2.5")


def test_quartiles_interpolate_within_the_right_pair() -> None:
    values = _values("1", "2", "3", "4")
    assert empirical_quantile(values, Decimal("0.25")) == Decimal("1.75")
    assert empirical_quantile(values, Decimal("0.75")) == Decimal("3.25")


def test_single_observation_is_returned_unchanged() -> None:
    assert empirical_quantile(_values("7"), Decimal("0.025")) == Decimal("7")


def test_quantile_is_monotone_in_probability() -> None:
    values = _values("5", "-3", "11", "0", "2", "9", "-7")
    probabilities = [Decimal(str(p)) for p in (0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99)]
    quantiles = [empirical_quantile(values, probability) for probability in probabilities]
    assert quantiles == sorted(quantiles)


def test_empty_input_is_rejected_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="at least one observation"):
        empirical_quantile((), Decimal("0.5"))


@pytest.mark.parametrize("probability", ["0", "1", "-0.1", "1.5"])
def test_probability_outside_the_open_unit_interval_is_rejected(probability: str) -> None:
    with pytest.raises(ValueError, match=r"probability must be in \(0, 1\)"):
        empirical_quantile(_values("1", "2", "3"), Decimal(probability))


def test_matches_numpys_default_quantile_definition() -> None:
    """Cross-check against the implementation the type-7 claim refers to."""
    np = pytest.importorskip("numpy")
    values = _values("5", "-3", "11", "0", "2", "9", "-7", "4")
    sample = np.asarray([float(item) for item in values], dtype=np.float64)
    for probability in ("0.01", "0.1", "0.25", "0.5", "0.9", "0.975"):
        expected = np.percentile(sample, float(probability) * 100.0)
        actual = empirical_quantile(values, Decimal(probability))
        # Decimal arithmetic is exact here; the tolerance only absorbs the float
        # round trip through numpy.
        assert abs(float(actual) - float(expected)) < 1e-9


def _values(*items: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(item) for item in items)
