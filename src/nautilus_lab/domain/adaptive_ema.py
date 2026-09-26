"""Selective (input-dependent) smoothing: the scalar form of the Mamba idea.

Source of the idea: the Transformer-vs-SSM review in the repo root (see
`docs/18-transformery-ssm-vidpovidnist.md`), §2.2 — in Mamba the
discretisation step delta and the matrices B, C are functions of the input
(selectivity), unlike the fixed-parameter S4. In the scalar case that recurrence is
just an EMA, i.e. `h_t = (1 - alpha)*h_{t-1} + alpha*x_t` — the one already in
`domain/ema.py`. So "selectivity" has exactly one measurable meaning here: **alpha_t
depends on market state** (Kaufman efficiency ratio on closed bars) instead of being
a constant.

When the efficiency ratio is low the market is mostly noise, and the filter smooths
harder; when it is high the filter reacts faster. `selectivity=0` reproduces the
fixed-alpha EMA exactly, which makes every grid over this parameter contain its own null
hypothesis — see specs/strategies/adaptive_ema.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import TraceStep, warmup_step
from nautilus_lab.domain.donchian import DowntrendBreakout, UptrendBreakout
from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.mean_reversion import RangeMeanReversion
from nautilus_lab.domain.regime import MarketRegime
from nautilus_lab.domain.regime_router import (
    regime_change_step,
    regime_step,
    regime_warmup_bars,
)
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.windows import RollingWindow

ONE = Decimal("1")
TWO = Decimal("2")
# alpha is clamped away from the ends: alpha = 1 would copy the last price (no memory) and
# alpha = 0 would freeze the filter forever, so selectivity = 1 at ER extremes must not
# be able to produce either.
MIN_ALPHA = Decimal("0.001")
MAX_ALPHA = Decimal("0.999")


@dataclass(frozen=True, slots=True)
class AdaptiveEmaParams:
    """Base EMA period plus the gain that makes its step input-dependent."""

    base_period: int = 40
    er_period: int = 20
    selectivity: Decimal = Decimal("0.5")
    slope_lookback: int = 10
    enter_trend_er: Decimal = Decimal("0.30")
    exit_trend_er: Decimal = Decimal("0.20")
    donchian_period: int = 20
    bb_period: int = 20
    bb_k: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if self.base_period < 2:
            raise InvalidRiskError("base_period must be >= 2")
        if self.er_period < 2:
            raise InvalidRiskError("er_period must be >= 2")
        if self.slope_lookback < 1:
            raise InvalidRiskError("slope_lookback must be >= 1")
        if self.selectivity < 0 or self.selectivity > 1:
            raise InvalidRiskError("selectivity must be in [0, 1]")
        if self.enter_trend_er <= self.exit_trend_er:
            raise InvalidRiskError("enter_trend_er must be > exit_trend_er")
        if self.enter_trend_er > 1 or self.exit_trend_er < 0:
            raise InvalidRiskError("ER thresholds must be in [0, 1]")
        if self.donchian_period < 2:
            raise InvalidRiskError("donchian_period must be >= 2")
        if self.bb_period < 2:
            raise InvalidRiskError("bb_period must be >= 2")
        if self.bb_k <= 0:
            raise InvalidRiskError("bb_k must be > 0")


@dataclass(frozen=True, slots=True)
class AdaptiveEmaSnapshot:
    regime: MarketRegime
    efficiency_ratio: Decimal
    slope: Decimal
    alpha: Decimal


class AdaptiveEma:
    """EMA whose step alpha_t = alpha_base * (1 + selectivity * (2*ER_t - 1)). No look-ahead.

    Only closed bars are used, and the efficiency ratio that drives alpha is computed
    from the same closed-bar window as the regime gate — so the filter cannot see
    the bar it is about to be tested on.
    """

    def __init__(self, params: AdaptiveEmaParams) -> None:
        self._params = params
        self._alpha_base = TWO / (Decimal(params.base_period) + ONE)
        self._closes = RollingWindow(params.er_period + 1)
        self._seed_sum = Decimal("0")
        self._seed_count = 0
        self._value: Decimal | None = None
        self._ema_history = RollingWindow(params.slope_lookback + 1)
        self._regime: MarketRegime = MarketRegime.RANGE

    @property
    def alpha_base(self) -> Decimal:
        return self._alpha_base

    @property
    def value(self) -> Decimal | None:
        """Current filter value; None until the seeding window closes."""
        return self._value

    @property
    def initialized(self) -> bool:
        return self._value is not None and self._ema_history.full

    @property
    def regime(self) -> MarketRegime | None:
        if not self.initialized:
            return None
        return self._regime

    def update(self, close: Decimal) -> AdaptiveEmaSnapshot | None:
        if close <= 0:
            raise InvalidRiskError("close must be > 0")
        self._closes.push(close)
        if self._value is None:
            self._seed_sum += close
            self._seed_count += 1
            if self._seed_count == self._params.base_period:
                self._value = self._seed_sum / Decimal(self._params.base_period)
                self._ema_history.push(self._value)
            return None

        efficiency_ratio = efficiency_ratio_of(self._closes.values())
        alpha = self.effective_alpha(efficiency_ratio)
        self._value = (close * alpha) + (self._value * (ONE - alpha))
        self._ema_history.push(self._value)
        if not self._closes.full or not self._ema_history.full:
            return None
        history = self._ema_history.values()
        slope = history[-1] - history[0]
        self._regime = self.next_regime(efficiency_ratio, slope)
        return AdaptiveEmaSnapshot(
            regime=self._regime,
            efficiency_ratio=efficiency_ratio,
            slope=slope,
            alpha=alpha,
        )

    def effective_alpha(self, efficiency_ratio: Decimal) -> Decimal:
        """Input-dependent step. selectivity = 0 returns exactly the fixed-alpha EMA step."""
        span = (TWO * efficiency_ratio) - ONE
        alpha = self._alpha_base * (ONE + (self._params.selectivity * span))
        if alpha < MIN_ALPHA:
            return MIN_ALPHA
        if alpha > MAX_ALPHA:
            return MAX_ALPHA
        return alpha

    def next_regime(self, efficiency_ratio: Decimal, slope: Decimal) -> MarketRegime:
        """Same hysteresis as RegimeClassifier, so the filter is the only difference."""
        trending = (
            efficiency_ratio >= self._params.enter_trend_er
            if self._regime is MarketRegime.RANGE
            else efficiency_ratio > self._params.exit_trend_er
        )
        if not trending or slope == 0:
            return MarketRegime.RANGE
        if slope > 0:
            return MarketRegime.UPTREND
        return MarketRegime.DOWNTREND


def efficiency_ratio_of(closes: tuple[Decimal, ...]) -> Decimal:
    """Kaufman efficiency ratio: net movement divided by the path walked.

    Same definition as `domain/regime.py::_efficiency_ratio` and
    `domain/formulaic_alphas.py::_efficiency_ratio`. Kept local rather than shared
    because those two are private to their modules; a shared home for the one
    formula would be a separate refactor, not a side effect of this robot.
    """
    if len(closes) < 2:
        return Decimal("0")
    net = abs(closes[-1] - closes[0])
    path = sum(
        (abs(closes[index] - closes[index - 1]) for index in range(1, len(closes))),
        Decimal("0"),
    )
    if path == 0:
        return Decimal("0")
    return net / path


class AdaptiveEmaRouter:
    """Classify the closed bar with the selective filter, then run the matching leg.

    The breakout and mean-reversion legs, the flatten-on-regime-change rule and the
    risk layer are byte-for-byte the ones `regime` uses (`domain/regime_router.py`).
    That is deliberate: the experiment is "adaptive filter or fixed filter?", so
    everything else has to stay identical, otherwise a difference would prove
    nothing about selectivity.
    """

    def __init__(self, *, instrument_id: str, params: AdaptiveEmaParams) -> None:
        self._instrument_id = instrument_id
        self._classifier = AdaptiveEma(params)
        self._uptrend = UptrendBreakout(
            instrument_id=instrument_id,
            channel_period=params.donchian_period,
            ema_period=params.base_period,
        )
        self._downtrend = DowntrendBreakout(
            instrument_id=instrument_id,
            channel_period=params.donchian_period,
            ema_period=params.base_period,
        )
        self._range = RangeMeanReversion(
            instrument_id=instrument_id,
            period=params.bb_period,
            band_k=params.bb_k,
        )
        self._last_regime: MarketRegime | None = None
        self._last_snapshot: AdaptiveEmaSnapshot | None = None
        self._params = params
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        """Why the last bar produced (or did not produce) a signal."""
        return self._trace

    @property
    def last_effective_regime(self) -> MarketRegime | None:
        """No flow filter here: the effective regime is the classified one."""
        return None if self._last_snapshot is None else self._last_snapshot.regime

    @property
    def last_snapshot(self) -> AdaptiveEmaSnapshot | None:
        return self._last_snapshot

    @property
    def uptrend_breakout(self) -> UptrendBreakout:
        return self._uptrend

    @property
    def downtrend_breakout(self) -> DowntrendBreakout:
        return self._downtrend

    @property
    def range_mean_reversion(self) -> RangeMeanReversion:
        return self._range

    @property
    def classifier(self) -> AdaptiveEma:
        return self._classifier

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        previous = self._classifier.regime or MarketRegime.RANGE
        self._last_snapshot = self._classifier.update(bar.close)
        if self._last_snapshot is None:
            self._warm_up(bar)
            self._trace = (
                warmup_step(
                    "AdaptiveEma",
                    seen=self._seen,
                    required=regime_warmup_bars(
                        er_period=self._params.er_period,
                        ema_period=self._params.base_period,
                        slope_lookback=self._params.slope_lookback,
                    ),
                ),
            )
            return None
        regime = regime_step(
            "AdaptiveEma",
            regime=self._last_snapshot.regime,
            previous=previous,
            efficiency_ratio=self._last_snapshot.efficiency_ratio,
            slope=self._last_snapshot.slope,
            enter_trend_er=self._params.enter_trend_er,
            exit_trend_er=self._params.exit_trend_er,
            extra={"alpha": self._last_snapshot.alpha},
        )
        if self._last_regime is not None and self._last_snapshot.regime is not self._last_regime:
            changed_from = self._last_regime
            self._last_regime = self._last_snapshot.regime
            self._warm_up(bar)
            self._trace = (
                regime,
                regime_change_step(
                    "AdaptiveEmaRouter", old=changed_from, new=self._last_snapshot.regime
                ),
            )
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.FLAT,
                bar_ts_utc=bar.ts_utc,
                reason=f"regime change to {self._last_snapshot.regime.value}",
                regime=self._last_snapshot.regime,
            )
        self._last_regime = self._last_snapshot.regime
        if self._last_snapshot.regime is MarketRegime.UPTREND:
            leg: UptrendBreakout | DowntrendBreakout | RangeMeanReversion = self._uptrend
        elif self._last_snapshot.regime is MarketRegime.DOWNTREND:
            leg = self._downtrend
        else:
            leg = self._range
        signal = leg.on_bar(bar)
        self._trace = (regime, *leg.last_trace)
        return signal

    def _warm_up(self, bar: OhlcvBar) -> None:
        """Feed every leg while the filter is not ready, so their windows stay aligned."""
        self._uptrend.on_bar(bar)
        self._downtrend.on_bar(bar)
        self._range.on_bar(bar)
