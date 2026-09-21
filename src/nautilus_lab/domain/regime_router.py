from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
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

    def on_trade_tick(self, *, is_buy: bool, volume: Decimal, dt_seconds: Decimal) -> None:
        if self._vpin is not None and hasattr(self._vpin, "update_from_trade"):
            self._vpin.update_from_trade(is_buy=is_buy, volume=volume)
        if self._hawkes is not None:
            self._hawkes.on_trade(
                side="buy" if is_buy else "sell", volume=volume, dt_seconds=dt_seconds
            )

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        vpin_state = self._vpin.update(bar) if self._vpin is not None else None
        hawkes_state = self._hawkes.last if self._hawkes is not None else None
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
        effective_regime = self._effective_regime(snapshot, vpin_state, hawkes_state)
        if effective_regime is MarketRegime.UPTREND:
            return self._uptrend.on_bar(bar)
        if effective_regime is MarketRegime.DOWNTREND:
            return self._downtrend.on_bar(bar)
        return self._range.on_bar(bar)

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
