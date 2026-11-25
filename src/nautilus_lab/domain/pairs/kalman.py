from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.pairs.cointegration import (
    _MIN_OBSERVATIONS,
    CointegrationResult,
    _adf_test,
    _std,
)

_DEFAULT_DELTA = Decimal("0.005")
_DEFAULT_OBS_NOISE = Decimal("1")
_DEFAULT_INITIAL_COV = Decimal("1000000")
_EWMA_ALPHA = Decimal("0.05")
_ONE = Decimal("1")
_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class KalmanStep:
    """Single causal update of the 2-state (beta, intercept) Kalman filter."""

    beta: Decimal
    intercept: Decimal
    innovation: Decimal
    innovation_std: Decimal
    z_score: Decimal


class KalmanHedgeFilter:
    """Causal exponential-forgetting Kalman / RLS filter for ``y_t = alpha_t + beta_t * x_t``.

    Uses forgetting factor ``lambda = 1 - delta`` (diffuse prior ``P_0 = initial_cov * I``,
    state ``theta = [beta, intercept]``) so covariance inflation adapts proportionally to
    ``x`` scale without overfitting un-cointegrated random walks tick-by-tick.

    All arithmetic is pure ``Decimal`` and strictly causal (1-step-ahead innovation
    ``e_t = y_t - (alpha_{t|t-1} + beta_{t|t-1} * x_t)`` is evaluated before updating).
    """

    def __init__(
        self,
        *,
        delta: Decimal = _DEFAULT_DELTA,
        obs_noise: Decimal = _DEFAULT_OBS_NOISE,
        initial_cov: Decimal = _DEFAULT_INITIAL_COV,
    ) -> None:
        if not (_ZERO < delta < _ONE):
            raise ValueError("kalman delta must be in (0, 1)")
        if obs_noise <= _ZERO:
            raise ValueError("obs_noise must be positive")
        if initial_cov <= _ZERO:
            raise ValueError("initial_cov must be positive")
        self._lam = _ONE - delta
        self._obs_noise = obs_noise
        self._beta = _ZERO
        self._intercept = _ZERO
        self._p00 = initial_cov
        self._p01 = _ZERO
        self._p11 = initial_cov
        self._ewma_var: Decimal | None = None
        self._steps = 0

    @property
    def beta(self) -> Decimal:
        return self._beta

    @property
    def intercept(self) -> Decimal:
        return self._intercept

    @property
    def steps(self) -> int:
        return self._steps

    def update(self, y: Decimal, x: Decimal) -> KalmanStep:
        """Advance one closed bar ``(y, x)`` and return the updated state and causal innovation."""
        if self._steps == 0:
            self._beta = y / x if x != _ZERO else _ZERO
            self._intercept = _ZERO
            self._steps = 1
            return KalmanStep(
                beta=self._beta,
                intercept=self._intercept,
                innovation=_ZERO,
                innovation_std=_ZERO,
                z_score=_ZERO,
            )

        # Predict covariance: P_{t|t-1} = P_{t-1} / lambda
        r00 = self._p00 / self._lam
        r01 = self._p01 / self._lam
        r11 = self._p11 / self._lam

        # 1-step-ahead causal innovation before state update
        innovation = y - (self._intercept + self._beta * x)
        sq_err = innovation * innovation
        if self._ewma_var is None:
            self._ewma_var = sq_err
        else:
            self._ewma_var = (_ONE - _EWMA_ALPHA) * self._ewma_var + _EWMA_ALPHA * sq_err
        innovation_std = self._ewma_var.sqrt() if self._ewma_var > _ZERO else _ZERO
        z = innovation / innovation_std if innovation_std > _ZERO else _ZERO

        # Kalman gain K = (R * H^T) / (H * R * H^T + R_obs), with H = [x, 1]
        ph0 = r00 * x + r01
        ph1 = r01 * x + r11
        s = x * ph0 + ph1 + self._obs_noise
        k0 = ph0 / s
        k1 = ph1 / s

        self._beta = self._beta + k0 * innovation
        self._intercept = self._intercept + k1 * innovation

        # Symmetric PSD covariance update: P_t = P_{t|t-1} - K * (R * H^T)^T
        self._p00 = max(_ZERO, r00 - k0 * ph0)
        self._p11 = max(_ZERO, r11 - k1 * ph1)
        self._p01 = _ZERO if (self._p00 == _ZERO or self._p11 == _ZERO) else r01 - k0 * ph1
        self._steps += 1
        return KalmanStep(
            beta=self._beta,
            intercept=self._intercept,
            innovation=innovation,
            innovation_std=innovation_std,
            z_score=z,
        )


def fit_kalman_cointegration(
    y: tuple[Decimal, ...],
    x: tuple[Decimal, ...],
    *,
    delta: Decimal = _DEFAULT_DELTA,
) -> CointegrationResult:
    """Estimate a dynamic ``(beta, intercept)`` via Kalman filter and run ADF on its innovations."""
    if len(y) != len(x) or len(y) < _MIN_OBSERVATIONS:
        raise ValueError(f"need at least {_MIN_OBSERVATIONS} aligned observations")
    mean_x = sum(x, _ZERO) / Decimal(len(x))
    if all(item == mean_x for item in x):
        raise ValueError("x has zero variance")

    filt = KalmanHedgeFilter(delta=delta)
    innovations: list[Decimal] = []
    last_step: KalmanStep | None = None
    for item_y, item_x in zip(y, x, strict=True):
        last_step = filt.update(item_y, item_x)
        innovations.append(last_step.innovation)
    if last_step is None:
        raise RuntimeError("kalman filter received zero aligned observations")

    series = tuple(innovations[1:] if len(innovations) > _MIN_OBSERVATIONS else innovations)
    adf_stat, adf_p, lags = _adf_test(series)
    return CointegrationResult(
        hedge_ratio=last_step.beta,
        intercept=last_step.intercept,
        adf_statistic=adf_stat,
        adf_pvalue=adf_p,
        residual_std=_std(series),
        adf_lags=lags,
    )
