from decimal import Decimal

from nautilus_lab.application.run_overfitting_audit import deflated_sharpe_for_winner
from nautilus_lab.domain.deflated_sharpe import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)


def _steady(offset: Decimal = Decimal("0")) -> tuple[Decimal, ...]:
    """Eight noisy positive returns, enough for skew/kurtosis to be defined."""
    steps = (1, 2, 1, 3, 2, 1, 2, 3)
    return tuple(Decimal("0.01") * Decimal(step) + offset for step in steps)


def test_more_trials_never_raise_the_deflated_probability() -> None:
    returns = _steady()
    few = (Decimal("0.4"), Decimal("0.6"))
    many = tuple(Decimal(str(0.4 + index * 0.002)) for index in range(100))
    with_few = deflated_sharpe_ratio(returns, few)
    with_many = deflated_sharpe_ratio(returns, many)
    assert with_few.probability is not None
    assert with_many.probability is not None
    assert with_few.threshold_sharpe is not None
    assert with_many.threshold_sharpe is not None
    assert with_many.threshold_sharpe > with_few.threshold_sharpe
    assert with_many.probability <= with_few.probability


def test_negative_skew_lowers_the_score() -> None:
    """Same mean, a crash in the tail vs a spike: negative skew must score lower."""
    crash = (
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("0.02"),
        Decimal("-0.06"),
    )
    spike = (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.08"),
    )
    assert sharpe_ratio(crash) == sharpe_ratio(spike)
    trials = (Decimal("0.5"), Decimal("0.4"))
    crash_dsr = deflated_sharpe_ratio(crash, trials)
    spike_dsr = deflated_sharpe_ratio(spike, trials)
    assert crash_dsr.probability is not None
    assert spike_dsr.probability is not None
    assert crash_dsr.probability < spike_dsr.probability


def test_undefined_when_there_is_nothing_to_deflate() -> None:
    trials = (Decimal("0.4"), Decimal("0.5"))
    too_short = deflated_sharpe_ratio((Decimal("0.01"),) * 7, trials)
    assert too_short.probability is None
    assert "observations" in too_short.summary_line()

    one_trial = deflated_sharpe_ratio(_steady(), (Decimal("0.5"),))
    assert one_trial.probability is None
    assert "trials" in one_trial.summary_line()

    flat = deflated_sharpe_ratio((Decimal("0.01"),) * 8, trials)
    assert flat.probability is None
    assert "variance" in flat.summary_line()


def test_zero_sharpe_gives_a_coin_flip() -> None:
    returns = (
        Decimal("0.02"),
        Decimal("-0.02"),
        Decimal("0.01"),
        Decimal("-0.01"),
        Decimal("0.03"),
        Decimal("-0.03"),
        Decimal("0.04"),
        Decimal("-0.04"),
    )
    assert sharpe_ratio(returns) == Decimal("0")
    psr = probabilistic_sharpe_ratio(returns, benchmark_sharpe=Decimal("0"))
    assert psr == Decimal("0.5")


def test_audit_scores_report_a_winner_that_generalises() -> None:
    """DSR is judged on the same blocks x configurations matrix as PBO."""
    winner = _steady(Decimal("0.02"))
    loser = _steady(Decimal("-0.02"))
    matrix = tuple((win, lose) for win, lose in zip(winner, loser, strict=True))
    result = deflated_sharpe_for_winner(matrix, matrix)
    assert result.observations == 8
    assert result.trials == 2
    assert result.probability is not None
    assert result.sharpe == sharpe_ratio(winner)
