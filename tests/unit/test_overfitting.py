from decimal import Decimal

import pytest

from nautilus_lab.application.dtos import index_of_best_configuration
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


def test_best_configuration_is_the_strongest_column_not_always_the_first() -> None:
    """A nested walk of every column would make every total identical and pick index 0."""
    matrix = (
        (Decimal("0.01"), Decimal("0.40"), Decimal("0.03")),
        (Decimal("0.00"), Decimal("0.60"), Decimal("0.07")),
    )
    assert index_of_best_configuration(matrix) == 1


def test_best_configuration_sums_only_values_inside_each_column() -> None:
    matrix = (
        (None, Decimal("0.05"), Decimal("0.01")),
        (Decimal("0.01"), Decimal("0.05"), Decimal("0.01")),
    )
    assert index_of_best_configuration(matrix) == 1


def test_best_configuration_keeps_the_first_index_on_a_tie() -> None:
    matrix = (
        (Decimal("0.02"), Decimal("0.02")),
        (Decimal("0.01"), Decimal("0.01")),
    )
    assert index_of_best_configuration(matrix) == 0


def test_odd_block_count_is_not_cscv() -> None:
    """Audit B6: 7 blocks gave 35 train=3/test=4 splits, reported as symmetric CSCV."""
    rows = tuple((Decimal(index), Decimal(-index)) for index in range(7))
    with pytest.raises(ValueError, match="even number of blocks"):
        probability_of_backtest_overfitting(rows)
