from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    TraceValue,
    Verdict,
    step,
    warmup_step,
)
from nautilus_lab.domain.donchian import DowntrendBreakout, UptrendBreakout
from nautilus_lab.domain.hawkes import ExponentialHawkes, HawkesIntensity
from nautilus_lab.domain.mean_reversion import RangeMeanReversion
from nautilus_lab.domain.regime import (
    MarketRegime,
    RegimeClassifier,
    RegimeParams,
    RegimeSnapshot,
)
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.vpin import VpinModel, VpinState


class RegimeRouter:
    """Classify the closed bar, then run the matching strategy. Flatten on regime change."""

    def __init__(
        self,
        *,
        instrument_id: str,
        params: RegimeParams,
        vpin: VpinModel | None = None,
        hawkes: ExponentialHawkes | None = None,
    ) -> None:
        self._instrument_id = instrument_id
        self._params = params
        self._classifier = RegimeClassifier(params)
        self._vpin = vpin
        self._hawkes = hawkes
        self._uptrend = UptrendBreakout(
            instrument_id=instrument_id,
            channel_period=params.donchian_period,
            ema_period=params.trend_ema_period,
        )
        self._downtrend = DowntrendBreakout(
            instrument_id=instrument_id,
            channel_period=params.donchian_period,
            ema_period=params.trend_ema_period,
        )
        self._range = RangeMeanReversion(
            instrument_id=instrument_id,
            period=params.bb_period,
            band_k=params.bb_k,
        )
        self._last_regime: MarketRegime | None = None
        self._last_snapshot: RegimeSnapshot | None = None
        self._last_vpin_state: VpinState | None = None
        self._last_hawkes_state: HawkesIntensity | None = None
        self._last_effective_regime: MarketRegime | None = None
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        """Why the last bar produced (or did not produce) a signal."""
        return self._trace

    @property
    def last_snapshot(self) -> RegimeSnapshot | None:
        return self._last_snapshot

    @property
    def last_vpin_state(self) -> VpinState | None:
        return self._last_vpin_state

    @property
    def last_hawkes_state(self) -> HawkesIntensity | None:
        return self._last_hawkes_state

    @property
    def last_effective_regime(self) -> MarketRegime | None:
        return self._last_effective_regime

    @property
    def uptrend_breakout(self) -> UptrendBreakout:
        return self._uptrend

    @property
    def downtrend_breakout(self) -> DowntrendBreakout:
        return self._downtrend

    @property
    def range_mean_reversion(self) -> RangeMeanReversion:
        return self._range

    def on_trade_tick(self, *, is_buy: bool, volume: Decimal, dt_seconds: Decimal) -> None:
        if self._vpin is not None and hasattr(self._vpin, "update_from_trade"):
            self._vpin.update_from_trade(is_buy=is_buy, volume=volume)
        if self._hawkes is not None:
            self._hawkes.on_trade(
                side="buy" if is_buy else "sell", volume=volume, dt_seconds=dt_seconds
            )

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        self._last_vpin_state = self._vpin.update(bar) if self._vpin is not None else None
        self._last_hawkes_state = self._hawkes.last if self._hawkes is not None else None
        previous = self._classifier.regime or MarketRegime.RANGE
        self._last_snapshot = self._classifier.update(bar.close)
        if self._last_snapshot is None:
            self._uptrend.on_bar(bar)
            self._downtrend.on_bar(bar)
            self._range.on_bar(bar)
            self._last_effective_regime = None
            self._trace = (
                warmup_step(
                    "RegimeClassifier",
                    seen=self._seen,
                    required=regime_warmup_bars(
                        er_period=self._params.er_period,
                        ema_period=self._params.trend_ema_period,
                        slope_lookback=self._params.slope_lookback,
                    ),
                ),
            )
            return None
        regime = regime_step(
            "RegimeClassifier",
            regime=self._last_snapshot.regime,
            previous=previous,
            efficiency_ratio=self._last_snapshot.efficiency_ratio,
            slope=self._last_snapshot.slope,
            enter_trend_er=self._params.enter_trend_er,
            exit_trend_er=self._params.exit_trend_er,
        )
        if self._last_regime is not None and self._last_snapshot.regime is not self._last_regime:
            changed_from = self._last_regime
            self._last_regime = self._last_snapshot.regime
            self._last_effective_regime = self._last_snapshot.regime
            self._uptrend.on_bar(bar)
            self._downtrend.on_bar(bar)
            self._range.on_bar(bar)
            self._trace = (
                regime,
                regime_change_step(
                    "RegimeRouter", old=changed_from, new=self._last_snapshot.regime
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
        self._last_effective_regime = self._effective_regime(
            self._last_snapshot, self._last_vpin_state, self._last_hawkes_state
        )
        filters = self._filter_steps(self._last_snapshot, self._last_effective_regime)
        if self._last_effective_regime is MarketRegime.UPTREND:
            leg: UptrendBreakout | DowntrendBreakout | RangeMeanReversion = self._uptrend
        elif self._last_effective_regime is MarketRegime.DOWNTREND:
            leg = self._downtrend
        else:
            leg = self._range
        signal = leg.on_bar(bar)
        self._trace = (regime, *filters, *leg.last_trace)
        return signal

    def _filter_steps(
        self, snapshot: RegimeSnapshot, effective: MarketRegime
    ) -> tuple[TraceStep, ...]:
        """VPIN / Hawkes do not veto a trade: toxic flow re-routes RANGE to a trend leg."""
        modified = effective is not snapshot.regime
        steps: list[TraceStep] = []
        if self._vpin is not None:
            state = self._last_vpin_state
            if state is None:
                steps.append(step(Stage.FILTER, "vpin", Verdict.SKIP, note="bucket not filled"))
            else:
                steps.append(
                    step(
                        Stage.FILTER,
                        "vpin",
                        Verdict.MODIFY if (state.toxic and modified) else Verdict.PASS,
                        result="toxic" if state.toxic else "normal",
                        values={"vpin": state.value, "bucket_filled": state.bucket_filled},
                        note=(
                            f"toxic flow re-routed {snapshot.regime.value} -> {effective.value}"
                            if state.toxic and modified
                            else None
                        ),
                    )
                )
        if self._hawkes is not None:
            hawkes = self._last_hawkes_state
            if hawkes is None:
                steps.append(step(Stage.FILTER, "hawkes", Verdict.SKIP, note="no trades yet"))
            else:
                steps.append(
                    step(
                        Stage.FILTER,
                        "hawkes",
                        Verdict.MODIFY if (hawkes.toxic_flow and modified) else Verdict.PASS,
                        result="toxic" if hawkes.toxic_flow else "normal",
                        values={
                            "buy_intensity": hawkes.buy_intensity,
                            "sell_intensity": hawkes.sell_intensity,
                        },
                        note=(
                            f"toxic flow re-routed {snapshot.regime.value} -> {effective.value}"
                            if hawkes.toxic_flow and modified
                            else None
                        ),
                    )
                )
        return tuple(steps)

    def _effective_regime(
        self,
        snapshot: RegimeSnapshot,
        vpin_state: VpinState | None,
        hawkes_state: HawkesIntensity | None,
    ) -> MarketRegime:
        toxic = False
        if vpin_state is not None and vpin_state.toxic:
            toxic = True
        if hawkes_state is not None and hawkes_state.toxic_flow:
            toxic = True

        if not toxic:
            return snapshot.regime

        if snapshot.regime is MarketRegime.RANGE:
            if snapshot.slope > 0:
                return MarketRegime.UPTREND
            if snapshot.slope < 0:
                return MarketRegime.DOWNTREND
        return snapshot.regime


def regime_warmup_bars(*, er_period: int, ema_period: int, slope_lookback: int) -> int:
    """Closed bars a trend/range classifier needs before its first verdict (approximate)."""
    return max(er_period + 1, ema_period + slope_lookback)


def regime_step(
    component: str,
    *,
    regime: MarketRegime,
    previous: MarketRegime,
    efficiency_ratio: Decimal,
    slope: Decimal,
    enter_trend_er: Decimal,
    exit_trend_er: Decimal,
    extra: dict[str, TraceValue] | None = None,
) -> TraceStep:
    """The classifier's verdict with the hysteresis threshold that actually applied."""
    from_range = previous is MarketRegime.RANGE
    applied = enter_trend_er if from_range else exit_trend_er
    if regime is MarketRegime.RANGE:
        why = (
            f"ER {efficiency_ratio:.3f} below the {'entry' if from_range else 'exit'} "
            f"threshold {applied}"
            if (efficiency_ratio < applied if from_range else efficiency_ratio <= applied)
            else "EMA slope is 0"
        )
    else:
        direction = "up" if slope > 0 else "down"
        why = f"ER {efficiency_ratio:.3f} passes {applied}, EMA slope {direction}"
    values: dict[str, TraceValue] = {"er": efficiency_ratio, "slope": slope}
    values.update(extra or {})
    return step(
        Stage.REGIME,
        component,
        Verdict.PASS,
        result=regime.value,
        values=values,
        thresholds={
            "enter_trend_er": enter_trend_er,
            "exit_trend_er": exit_trend_er,
            "applied_er": applied,
        },
        note=f"{why} (previous regime {previous.value})",
    )


def regime_change_step(component: str, *, old: MarketRegime, new: MarketRegime) -> TraceStep:
    return step(
        Stage.STRATEGY,
        component,
        Verdict.EMIT,
        result="flat",
        values={"from_regime": old.value, "to_regime": new.value},
        note="regime changed: flatten before trading the new regime",
    )
