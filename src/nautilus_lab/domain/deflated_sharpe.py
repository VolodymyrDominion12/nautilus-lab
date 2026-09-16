from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from math import e, erf, log, sqrt

# Deflated Sharpe Ratio, as named in `ML Ансамблі У Криптотрейдингу.md` §5.2:  # noqa: RUF003
#
#   «Дефльований коефіцієнт Шарпа (DSR) ... коригує базовий коефіцієнт Шарпа з
#    урахуванням ненормальності розподілу (асиметрії та ексцесу) та математично
#    пеналізує результат на основі загальної кількості проведених випробувань.»
#
# The document states no formula, no threshold and no estimator, so the code below is
# the standard one — Bailey & López de Prado, "The Deflated Sharpe Ratio: Correcting for
# Selection Bias, Backtest Overfitting and Non-Normality" (2014) — and is NOT quoted from
# the research document. It is marked as such so nobody later mistakes it for one.
#
# The sibling question ("does the in-sample winner survive out of sample at all?") is
# answered by PBO in `domain/overfitting.py`. This module answers the other half:
# "given that N configurations were tried, is the winner's Sharpe more than the best of N
# coin flips would have produced?" Both questions matter, and neither replaces the other.

MIN_OBSERVATIONS = 8
"""Below this many observations the skew/kurtosis estimates are noise, not estimates.

Nothing magic happens at eight; it is the published sample size at which the expansion
behind PSR starts to be defensible, and the project's default PBO audit (`--pbo-blocks
8`) lands exactly on it. Callers can raise the block count to buy a wider sample.
"""

EULER_MASCHERONI = Decimal("0.5772156649015329")


@dataclass(frozen=True, slots=True)
class DeflatedSharpeResult:
    """Probability that the observed Sharpe beats the best of `trials` random trials.

    `probability` is None when there is nothing to deflate — too few observations, fewer
    than two trials, zero variance, or a non-positive PSR denominator. `note` says which,
    so the caller can print "undefined" with a reason instead of a confident number.
    """

    probability: Decimal | None
    sharpe: Decimal | None
    threshold_sharpe: Decimal | None
    observations: int
    trials: int
    note: str

    @property
    def is_meaningful(self) -> bool:
        return self.probability is not None

    def summary_line(self) -> str:
        if self.probability is None:
            return f"DSR undefined: {self.note}"
        return (
            f"DSR={self.probability} (observations={self.observations} "
            f"trials={self.trials} sharpe={self.sharpe} threshold={self.threshold_sharpe})"
        )


def sharpe_ratio(returns: Sequence[Decimal]) -> Decimal | None:
    """Mean over sample standard deviation of a per-period return series.

    Deliberately not annualised: DSR's deflation threshold is estimated on the same
    per-period scale, and mixing an annualised Sharpe with a per-period threshold is a
    silent factor of sqrt(periods) in the answer.
    """
    if len(returns) < 2:
        return None
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns) - 1)
    if variance <= 0:
        return None
    deviation = variance.sqrt()
    if deviation == 0:
        return None
    return mean / deviation


def normal_cdf(value: Decimal) -> Decimal:
    """Standard normal CDF, via the error function."""
    scaled = float(value) / sqrt(2.0)
    return Decimal(str(0.5 * (1.0 + erf(scaled))))


def normal_ppf(probability: Decimal) -> Decimal:
    """Inverse standard normal CDF (Acklam's rational approximation, |error| < 1.2e-9).

    Only the two tails the deflation formula needs are exercised, but the whole domain
    (0, 1) is implemented because a half-accurate quantile would quietly bias the
    threshold on which the entire metric rests.
    """
    if probability <= 0 or probability >= 1:
        raise ValueError("probability must be strictly inside (0, 1)")
    p = float(probability)
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = sqrt(-2.0 * log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    else:
        q = sqrt(-2.0 * log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    return Decimal(str(x))


def expected_max_sharpe(
    *,
    trials: int,
    sharpe_variance: Decimal,
) -> Decimal | None:
    """Expected best Sharpe among `trials` independent zero-skill trials.

    The Gumbel approximation of the maximum of `trials` normal draws with variance
    `sharpe_variance`: as trials grow, the best of pure noise grows with them — which is
    exactly the number a grid-search winner has to beat. Returns 0 when the trials show
    no spread at all (there is then nothing for the search to have selected on), and None
    for fewer than two trials.
    """
    if trials < 2:
        return None
    if sharpe_variance < 0:
        raise ValueError("sharpe_variance must be >= 0")
    if sharpe_variance == 0:
        return Decimal("0")
    left = normal_ppf(Decimal("1") - Decimal("1") / Decimal(trials))
    right = normal_ppf(Decimal("1") - Decimal("1") / (Decimal(trials) * Decimal(str(e))))
    return sharpe_variance.sqrt() * (
        (Decimal("1") - EULER_MASCHERONI) * left + EULER_MASCHERONI * right
    )


def probabilistic_sharpe_ratio(
    returns: Sequence[Decimal],
    *,
    benchmark_sharpe: Decimal = Decimal("0"),
) -> Decimal | None:
    """Probability the true Sharpe exceeds `benchmark_sharpe`, correcting for shape.

    PSR = Phi( (SR - SR*) * sqrt(T - 1) / sqrt(1 - skew*SR + (kurtosis - 1)/4 * SR^2) ).
    Skew and kurtosis are the Pearson (non-excess) moments of the return series; for a
    normal sample the kurtosis term vanishes at 3. Returns None when the series cannot
    support the formula — fewer than two observations, zero variance, or a non-positive
    denominator (possible only with extreme skew and a Sharpe far outside the range a
    bar-level strategy produces; reported rather than clamped).
    """
    observations = len(returns)
    if observations < 2:
        return None
    sharpe = sharpe_ratio(returns)
    if sharpe is None:
        return None
    skew = _skewness(returns)
    kurtosis = _kurtosis(returns)
    if skew is None or kurtosis is None:
        return None
    denominator = (
        Decimal("1") - skew * sharpe + (kurtosis - Decimal("1")) / Decimal("4") * (sharpe**2)
    )
    if denominator <= 0:
        return None
    z_score = (sharpe - benchmark_sharpe) * Decimal(observations - 1).sqrt() / denominator.sqrt()
    return normal_cdf(z_score)


def deflated_sharpe_ratio(
    returns: Sequence[Decimal],
    trial_sharpes: Sequence[Decimal],
) -> DeflatedSharpeResult:
    """Deflate the observed Sharpe by the number of trials that produced it.

    `returns` is the track record being judged (one entry per period — a block, a fold,
    a bar: whatever unit the caller's Sharpe is expressed in). `trial_sharpes` are the
    Sharpes of every configuration that was compared, the winner included; their variance
    is the estimate of how much Sharpe a zero-skill search would have spread over the
    same trials.

    Always returns a result object; when the inputs cannot support the formula the
    probability is None and `note` explains why. A number invented from eight noisy
    observations would be read as evidence, and there is none to read.
    """
    observations = len(returns)
    trials = len(trial_sharpes)
    sharpe = sharpe_ratio(returns)
    if observations < MIN_OBSERVATIONS:
        return _undefined(
            observations,
            trials,
            sharpe,
            f"{observations} observations (need >= {MIN_OBSERVATIONS} for skew/kurtosis)",
        )
    if trials < 2:
        return _undefined(observations, trials, sharpe, "fewer than 2 trials: nothing to deflate")
    if sharpe is None:
        return _undefined(observations, trials, sharpe, "return series has zero variance")

    variance = _variance(trial_sharpes)
    if variance is None:
        return _undefined(observations, trials, sharpe, "trial Sharpes are not a usable sample")
    threshold = expected_max_sharpe(trials=trials, sharpe_variance=variance)
    if threshold is None:
        return _undefined(observations, trials, sharpe, "no expected-maximum-Sharpe for < 2 trials")
    probability = probabilistic_sharpe_ratio(returns, benchmark_sharpe=threshold)
    if probability is None:
        return _undefined(
            observations,
            trials,
            sharpe,
            "PSR denominator is not positive (extreme skew and Sharpe)",
        )
    return DeflatedSharpeResult(
        probability=probability,
        sharpe=sharpe,
        threshold_sharpe=threshold,
        observations=observations,
        trials=trials,
        note=(
            "PSR against the expected best Sharpe of "
            f"{trials} zero-skill trials with variance {variance}"
        ),
    )


def _undefined(
    observations: int,
    trials: int,
    sharpe: Decimal | None,
    note: str,
) -> DeflatedSharpeResult:
    return DeflatedSharpeResult(
        probability=None,
        sharpe=sharpe,
        threshold_sharpe=None,
        observations=observations,
        trials=trials,
        note=note,
    )


def _variance(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    return sum((item - mean) ** 2 for item in values) / Decimal(len(values) - 1)


def _moment(returns: Sequence[Decimal], power: int) -> Decimal | None:
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns))
    if variance <= 0:
        return None
    deviation = variance.sqrt()
    return sum(((item - mean) / deviation) ** power for item in returns) / Decimal(len(returns))


def _skewness(returns: Sequence[Decimal]) -> Decimal | None:
    """Third standardised moment (Pearson skewness)."""
    return _moment(returns, 3)


def _kurtosis(returns: Sequence[Decimal]) -> Decimal | None:
    """Fourth standardised moment, Pearson convention (3 for a normal sample)."""
    return _moment(returns, 4)
