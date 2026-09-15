from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

# `Стратегії MFT Криптоторгівлі 2026.md` §2.2 names the problem and gives no estimator:
#
#   «Однією з найбільших проблем використання машинного навчання у трейдингу є  # noqa: RUF003
#    ймовірність перенавчання на історичних даних (Probability of Backtest
#    Overfitting, PBO). Додавання сотень оптимізованих параметрів до бектесту часто
#    призводить до ідеальної кривої прибутковості в минулому, але до швидких збитків
#    на реальному ринку.»
#
# The document states no formula, no threshold and no CSCV reference, so the estimator
# below is the standard one (Bailey, Borwein, López de Prado & Zhu, "The Probability of
# Backtest Overfitting", 2016) and is NOT taken from the research document. It is
# documented as such so nobody later mistakes it for a quoted method.
#
# The project's previous defence against overfitting was informal — "keep the parameter
# grid small (3-6 combinations)". This module turns that defence into a number by
# asking the only question that matters: when you pick the best configuration on one
# half of the history, how often does it land in the *bottom* half on the other?


@dataclass(frozen=True, slots=True)
class CscvResult:
    """Outcome of a CSCV run over a `splits x configurations` score matrix.

    `pbo` is the probability of backtest overfitting: the fraction of symmetric
    splits where the in-sample winner ranks at or below the median out of sample.
    `logits` holds one value per split, `logit = ln(omega / (1 - omega))` where
    `omega` is the winner's relative out-of-sample rank in `(0, 1]`.
    """

    pbo: Decimal
    split_count: int
    configuration_count: int
    logits: tuple[Decimal, ...]

    @property
    def is_meaningful(self) -> bool:
        """A PBO needs enough split/configuration pairs to say anything at all.

        With fewer than two configurations there is nothing to select between, and
        the winner's rank is then trivially the median — PBO would report 1.0 for a
        single configuration and look like a damning result instead of an undefined
        one. Callers must check this before quoting `pbo`.
        """
        return self.configuration_count >= 2 and self.split_count >= 2

    def summary_line(self) -> str:
        if not self.is_meaningful:
            return (
                f"PBO undefined: {self.configuration_count} configurations across "
                f"{self.split_count} splits (need >= 2 of each)"
            )
        return (
            f"PBO={self.pbo} over {self.split_count} splits x "
            f"{self.configuration_count} configurations"
        )


def probability_of_backtest_overfitting(scores: tuple[tuple[Decimal, ...], ...]) -> CscvResult:
    """Estimate PBO from a `blocks x configurations` out-of-sample score matrix.

    Combinatorially Symmetric Cross-Validation. The rows are contiguous, equal-length
    blocks of history and the columns are the parameter configurations evaluated on
    each block. For every way of splitting the blocks into two equal halves, one half
    plays in-sample (pick the best column) and the other plays out-of-sample (rank
    that column among all columns).

    A low PBO means in-sample selection generalises; a PBO near 0.5 means the winner is
    a coin flip; above 0.5 means selection is actively counter-productive. It never
    certifies an edge — a low PBO on a strategy that loses money everywhere is still a
    losing strategy with a consistent ranking.

    The matrix must describe *disjoint* stretches of history scored independently
    (one simulation per block, as `RunOverfitAudit` does), never the full-sample fit
    of each configuration. Handing it full-sample scores measures the optimism of the
    search itself rather than whether the selection survives unseen data.
    """
    blocks = len(scores)
    if blocks == 0:
        raise ValueError("score matrix is empty")
    config_count = len(scores[0])
    if config_count == 0:
        raise ValueError("score matrix has no configurations")
    for index, row in enumerate(scores):
        if len(row) != config_count:
            raise ValueError(
                f"score matrix row {index} has {len(row)} values, expected {config_count}"
            )
    if blocks < 2:
        return CscvResult(
            pbo=Decimal("1"),
            split_count=0,
            configuration_count=config_count,
            logits=(),
        )

    half = blocks // 2
    logits: list[Decimal] = []
    overfit = 0
    # Each combination defines a train half; its complement is the test half. `half`
    # blocks out of `blocks` therefore enumerates every symmetric split exactly once.
    for train_indices in combinations(range(blocks), half):
        train_set = set(train_indices)
        test_indices = tuple(index for index in range(blocks) if index not in train_set)
        if not test_indices:
            continue
        in_sample = _column_means(scores, train_indices, config_count)
        # A train half where every configuration scores the same selects nothing.
        # Counting it would let an arbitrary tie-break decide the verdict, so the
        # split is skipped instead of resolved by column order.
        if all(value == in_sample[0] for value in in_sample):
            continue
        out_of_sample = _column_means(scores, test_indices, config_count)
        winner = _argmax(in_sample)
        rank = _relative_rank(out_of_sample, winner)
        if rank <= Decimal("0.5"):
            overfit += 1
        logits.append(_logit(rank))

    split_count = len(logits)
    if split_count == 0:
        return CscvResult(
            pbo=Decimal("1"),
            split_count=0,
            configuration_count=config_count,
            logits=(),
        )
    pbo = Decimal(overfit) / Decimal(split_count)
    return CscvResult(
        pbo=pbo,
        split_count=split_count,
        configuration_count=config_count,
        logits=tuple(logits),
    )


def _column_means(
    scores: tuple[tuple[Decimal, ...], ...],
    block_indices: tuple[int, ...],
    config_count: int,
) -> tuple[Decimal, ...]:
    """Mean score per configuration over one set of blocks."""
    return tuple(
        _column_mean(scores, block_indices, config_index) for config_index in range(config_count)
    )


def _column_mean(
    scores: tuple[tuple[Decimal, ...], ...],
    block_indices: tuple[int, ...],
    config_index: int,
) -> Decimal:
    total = sum((scores[block][config_index] for block in block_indices), Decimal("0"))
    return total / Decimal(len(block_indices))


def _argmax(values: tuple[Decimal, ...]) -> int:
    best = 0
    for index in range(1, len(values)):
        if values[index] > values[best]:
            best = index
    return best


def _relative_rank(values: tuple[Decimal, ...], winner: int) -> Decimal:
    """Out-of-sample rank of `winner` in `(0, 1]`, CSCV convention.

    Ranks run from 1 (worst column) to N (best), normalised by `N + 1` rather than
    `N` so the value is strictly inside `(0, 1)` and `logit = ln(omega / (1 - omega))`
    is always finite. Ties share their average rank, which puts a winner that ties
    every other column at exactly 0.5 — the honest reading of a split that contains
    no ranking information.
    """
    worse = sum(1 for value in values if value < values[winner])
    equal = sum(1 for value in values if value == values[winner])
    average_rank = Decimal(worse) + (Decimal(equal) + Decimal("1")) / Decimal("2")
    return average_rank / Decimal(len(values) + 1)


def _logit(rank: Decimal) -> Decimal:
    if rank >= 1:
        # Defensive clamp: `_relative_rank` cannot actually reach 1, but an infinite
        # logit would poison every downstream mean if it ever did.
        return Decimal("3")
    if rank <= 0:
        return Decimal("-3")
    return (rank / (Decimal("1") - rank)).ln()
