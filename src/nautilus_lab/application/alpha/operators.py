"""Vectorised, NaN-aware operators on `T x N` panels.

Time-series operators (`ts_*`, `delay`, `delta`, `pct_change`) look backwards only. A
window that is not completely finite gives NaN, never a partial value. Cross-sectional
operators (`cs_*`) work row by row over the finite names and return NaN for a row with
fewer than `min_names` of them: a "ranking" of two coins is a coin flip, not a signal.
"""

from __future__ import annotations

import numpy as np

from nautilus_lab.application.alpha.panel import BoolArray, FloatArray

MIN_NAMES = 5
_RANK_CHUNK = 4096


def _rolling_sums(values: FloatArray, window: int) -> tuple[FloatArray, FloatArray]:
    """Trailing sum and count of finite values over `window` rows, per column."""
    if window < 1:
        raise ValueError("window must be >= 1")
    finite = np.isfinite(values)
    filled = np.where(finite, values, 0.0)
    zero = np.zeros((1, *values.shape[1:]))
    total = np.concatenate([zero, np.cumsum(filled, axis=0)])
    count = np.concatenate([zero, np.cumsum(finite, axis=0, dtype=np.float64)])
    sums = np.full(values.shape, np.nan)
    counts = np.zeros(values.shape)
    if values.shape[0] >= window:
        sums[window - 1 :] = total[window:] - total[:-window]
        counts[window - 1 :] = count[window:] - count[:-window]
    return sums, counts


def ts_sum(values: FloatArray, window: int) -> FloatArray:
    sums, counts = _rolling_sums(values, window)
    return np.where(counts == window, sums, np.nan)


def ts_mean(values: FloatArray, window: int) -> FloatArray:
    return ts_sum(values, window) / window


def ts_std(values: FloatArray, window: int) -> FloatArray:
    if window < 2:
        raise ValueError("ts_std needs window >= 2")
    mean = ts_mean(values, window)
    mean_sq = ts_mean(values * values, window)
    variance = (mean_sq - mean * mean) * window / (window - 1)
    with np.errstate(invalid="ignore"):
        return np.sqrt(np.maximum(variance, 0.0))


def ts_zscore(values: FloatArray, window: int) -> FloatArray:
    spread = ts_std(values, window)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(spread > 0, (values - ts_mean(values, window)) / spread, np.nan)


def ts_max(values: FloatArray, window: int) -> FloatArray:
    if window < 1:
        raise ValueError("window must be >= 1")
    out = np.full(values.shape, np.nan)
    rows = values.shape[0]
    if rows < window:
        return out
    view = np.lib.stride_tricks.sliding_window_view(values, window, axis=0)
    with np.errstate(invalid="ignore"):
        block = view.max(axis=-1)  # NaN propagates: an incomplete window is unknown
    out[window - 1 :] = block
    return out


def delay(values: FloatArray, lag: int) -> FloatArray:
    if lag < 0:
        raise ValueError("lag must be >= 0")
    out = np.full(values.shape, np.nan)
    if lag == 0:
        return values.copy()
    if lag < values.shape[0]:
        out[lag:] = values[:-lag]
    return out


def delta(values: FloatArray, lag: int) -> FloatArray:
    return values - delay(values, lag)


def pct_change(values: FloatArray, lag: int) -> FloatArray:
    previous = delay(values, lag)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(previous > 0, values / previous - 1.0, np.nan)


def lead(values: FloatArray, steps: int) -> FloatArray:
    """`values[t + steps]` on row t. Only targets may use it, never a signal."""
    if steps < 1:
        raise ValueError("steps must be >= 1")
    out = np.full(values.shape, np.nan)
    if steps < values.shape[0]:
        out[:-steps] = values[steps:]
    return out


def cs_count(values: FloatArray) -> FloatArray:
    return np.isfinite(values).sum(axis=1).astype(np.float64)


def cs_mean(values: FloatArray, min_names: int = MIN_NAMES) -> FloatArray:
    """Row mean over finite names, as a `T` vector; NaN below `min_names`."""
    finite = np.isfinite(values)
    count = finite.sum(axis=1)
    total = np.where(finite, values, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count >= min_names, total / np.maximum(count, 1), np.nan)


def cs_demean(values: FloatArray, min_names: int = MIN_NAMES) -> FloatArray:
    return values - cs_mean(values, min_names)[:, None]


def cs_zscore(values: FloatArray, min_names: int = MIN_NAMES) -> FloatArray:
    centred = cs_demean(values, min_names)
    finite = np.isfinite(centred)
    count = finite.sum(axis=1)
    sq = np.where(finite, centred * centred, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        spread = np.sqrt(sq / np.maximum(count - 1, 1))
        return np.where(spread[:, None] > 0, centred / spread[:, None], np.nan)


def cs_rank(values: FloatArray, min_names: int = MIN_NAMES) -> FloatArray:
    """Row percentile rank in `[-0.5, 0.5]`, ties averaged; mean 0 over each row.

    Ties matter here: funding sits at exactly 0.01% for many coins at once, and an
    arbitrary tie-break would turn that into a fake ranking.
    """
    out = np.full(values.shape, np.nan)
    finite = np.isfinite(values)
    for start in range(0, values.shape[0], _RANK_CHUNK):
        stop = start + _RANK_CHUNK
        block = values[start:stop]
        valid = finite[start:stop]
        a = block[:, :, None]
        b = block[:, None, :]
        other = valid[:, None, :]
        less = ((b < a) & other).sum(axis=-1)
        equal = ((b == a) & other).sum(axis=-1)
        rank = less + (equal - 1) / 2.0
        count = valid.sum(axis=1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            pct = rank / np.maximum(count - 1, 1) - 0.5
        ok = valid & (count >= min_names)
        out[start:stop] = np.where(ok, pct, np.nan)
    return out


def rolling_beta(
    returns: FloatArray, market: FloatArray, window: int, min_fraction: float = 0.8
) -> FloatArray:
    """Trailing OLS beta of each column on `market` (a `T` vector), past rows only."""
    if window < 2:
        raise ValueError("rolling_beta needs window >= 2")
    pair: BoolArray = np.isfinite(returns) & np.isfinite(market)[:, None]
    x = np.where(pair, market[:, None], 0.0)
    y = np.where(pair, returns, 0.0)
    pair_f = pair.astype(np.float64)
    n, _ = _rolling_sums(pair_f, window)
    sx, _ = _rolling_sums(x, window)
    sy, _ = _rolling_sums(y, window)
    sxy, _ = _rolling_sums(x * y, window)
    sxx, _ = _rolling_sums(x * x, window)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy - sx * sy / n
        var = sxx - sx * sx / n
        beta = np.where((n >= min_fraction * window) & (var > 0), cov / var, np.nan)
    return beta


def neutralise(weights: FloatArray, exposures: FloatArray) -> FloatArray:
    """Project each row of `weights` off a constant and `exposures` (dollar + beta).

    Rows where the 2x2 system is singular (all betas equal, too few names) fall back
    to dollar neutrality only. NaN weights stay NaN.
    """
    valid = np.isfinite(weights) & np.isfinite(exposures)
    w = np.where(valid, weights, 0.0)
    b = np.where(valid, exposures, 0.0)
    one = valid.astype(np.float64)
    s11 = one.sum(axis=1)
    s1b = b.sum(axis=1)
    sbb = (b * b).sum(axis=1)
    s1w = w.sum(axis=1)
    sbw = (b * w).sum(axis=1)
    det = s11 * sbb - s1b * s1b
    with np.errstate(invalid="ignore", divide="ignore"):
        good = np.abs(det) > 1e-12 * np.maximum(s11 * sbb, 1e-300)
        c1 = np.where(good, (sbb * s1w - s1b * sbw) / det, s1w / np.maximum(s11, 1))
        cb = np.where(good, (s11 * sbw - s1b * s1w) / det, 0.0)
    projected = w - c1[:, None] * one - cb[:, None] * b
    return np.where(valid, projected, np.nan)


def unit_gross(weights: FloatArray) -> FloatArray:
    """Scale each row to `sum |w| = 1`; an all-zero row stays zero."""
    gross = np.nansum(np.abs(weights), axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(gross[:, None] > 0, weights / gross[:, None], 0.0)
