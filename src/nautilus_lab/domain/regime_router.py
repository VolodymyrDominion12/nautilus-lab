from __future__ import annotations

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.donchian import DowntrendBreakout, UptrendBreakout
from nautilus_lab.domain.mean_reversion import RangeMeanReversion
from nautilus_lab.domain.regime import (
    MarketRegime,
    RegimeClassifier,
    RegimeParams,
    RegimeSnapshot,
)
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.vpin import BarVpin, VpinState


class RegimeRouter:
    """Classify the closed bar, then run the matching strategy. Flatten on regime change."""

    def __init__(
        self,
        *,
        instrument_id: str,
        params: RegimeParams,
        vpin: BarVpin | None = None,
    ) -> None:
        self._instrument_id = instrument_id
        self._classifier = RegimeClassifier(params)
        self._vpin = vpin
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

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        vpin_state = self._vpin.update(bar) if self._vpin is not None else None
        snapshot = self._classifier.update(bar.close)
        if snapshot is None:
            self._uptrend.on_bar(bar)
            self._downtrend.on_bar(bar)
            self._range.on_bar(bar)
            return None
        if self._last_regime is not None and snapshot.regime is not self._last_regime:
            self._last_regime = snapshot.regime
            self._uptrend.on_bar(bar)
            self._downtrend.on_bar(bar)
            self._range.on_bar(bar)
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.FLAT,
                bar_ts_utc=bar.ts_utc,
                reason=f"regime change to {snapshot.regime.value}",
                regime=snapshot.regime,
            )
        self._last_regime = snapshot.regime
        effective_regime = self._effective_regime(snapshot, vpin_state)
        if effective_regime is MarketRegime.UPTREND:
            return self._uptrend.on_bar(bar)
        if effective_regime is MarketRegime.DOWNTREND:
            return self._downtrend.on_bar(bar)
        return self._range.on_bar(bar)

    def _effective_regime(
        self, snapshot: RegimeSnapshot, vpin_state: VpinState | None
    ) -> MarketRegime:
        if vpin_state is None or not vpin_state.toxic:
            return snapshot.regime
        if snapshot.regime is MarketRegime.RANGE:
            if snapshot.slope > 0:
                return MarketRegime.UPTREND
            if snapshot.slope < 0:
                return MarketRegime.DOWNTREND
        return snapshot.regime
