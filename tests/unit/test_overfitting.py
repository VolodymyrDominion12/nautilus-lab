from decimal import Decimal

import pytest

from nautilus_lab.domain.overfitting import probability_of_backtest_overfitting


def test_pbo_is_low_when_one_configuration_dominates_every_block() -> None:
    """A configuration that wins everywhere is not an artifact of the split."""
    scores = (
        (Decimal("0.01"), Decimal("0.05"), Decimal("-0.02")),
        (Decimal("0.01"), Decimal("0.06"), Decimal("-0.03")),
        (Decimal("0.02"), Decimal("0.05"), Decimal("-0.01")),
        (Decimal("0.01"), Decimal("0.07"), Decimal("-0.02")),
    )
    result = probability_of_backtest_overfitting(scores)
    assert result.pbo == Decimal("0")
    assert result.split_count == 6
    assert result.configuration_count == 3
    assert result.is_meaningful


def test_pbo_is_total_when_the_best_in_sample_column_is_always_last() -> None:
    """Perfectly anti-correlated blocks: selection is actively counter-productive."""
    scores = (
        (Decimal("0.05"), Decimal("-0.05")),
        (Decimal("-0.05"), Decimal("0.05")),
        (Decimal("0.05"), Decimal("-0.05")),
        (Decimal("-0.05"), Decimal("0.05")),
    )
    result = probability_of_backtest_overfitting(scores)
    assert result.pbo == Decimal("1")
    assert result.is_meaningful


def test_identical_configurations_carry_no_information() -> None:
    """An uninformative matrix must report undefined, not a damning PBO.

    Every train half ties, so no split actually selects anything. Counting those
    splits would let the tie-break order decide the verdict.
    """
    scores = tuple((Decimal("0.02"), Decimal("0.02")) for _ in range(4))
    result = probability_of_backtest_overfitting(scores)
    assert result.split_count == 0
    assert not result.is_meaningful
    assert "undefined" in result.summary_line()


def test_pbo_needs_two_configurations_to_mean_anything() -> None:
    result = probability_of_backtest_overfitting(
        ((Decimal("0.01"),), (Decimal("0.02"),), (Decimal("0.03"),), (Decimal("0.04"),))
    )
    assert not result.is_meaningful
    assert "undefined" in result.summary_line()


def test_single_block_is_not_a_split() -> None:
    result = probability_of_backtest_overfitting(((Decimal("0.01"), Decimal("0.02")),))
    assert result.split_count == 0
    assert not result.is_meaningful


def test_ragged_matrix_is_rejected() -> None:
    with pytest.raises(ValueError, match="row 1 has 1 values"):
        probability_of_backtest_overfitting(
            (
                (Decimal("0.01"), Decimal("0.02")),
                (Decimal("0.01"),),
            )
        )


def test_empty_matrix_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        probability_of_backtest_overfitting(())
