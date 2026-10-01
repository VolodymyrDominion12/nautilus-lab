from __future__ import annotations

from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    TraceValue,
    Verdict,
    margin_pct,
    step,
    warmup_step,
)
from nautilus_lab.domain.regime import MarketRegime
from nautilus_lab.domain.signals import Signal, SignalSide
from nautilus_lab.domain.windows import RollingWindow


class RangeMeanReversion:
    """Bollinger mean reversion for ranging markets. Closed bars only."""

    def __init__(
        self,
        *,
        instrument_id: str,
        period: int,
        band_k: Decimal,
        allow_short: bool = True,
        exit_at_mean: bool = False,
        min_band_width_pct: Decimal = Decimal("0"),
    ) -> None:
        self._instrument_id = instrument_id
        self._closes = RollingWindow(period)
        self._band_k = band_k
        self._period = period
        self._allow_short = allow_short
        self._exit_at_mean = exit_at_mean
        self._min_band_width_pct = min_band_width_pct
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        return self._trace

    def on_bar(self, bar: OhlcvBar) -> Signal | None:
        self._seen += 1
        self._closes.push(bar.close)
        if not self._closes.full:
            self._trace = (
                warmup_step("RangeMeanReversion", seen=self._seen, required=self._period),
            )
            return None
        mean, stdev = _mean_stdev(self._closes.values())
        thresholds: dict[str, TraceValue] = {"bb_period": self._period, "bb_k": self._band_k}
        if stdev == 0:
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "RangeMeanReversion",
                    Verdict.EMIT,
                    result="flat",
                    values={"close": bar.close, "mean": mean, "stdev": stdev},
                    thresholds=thresholds,
                    note="zero volatility: bands undefined",
                ),
            )
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.FLAT,
                bar_ts_utc=bar.ts_utc,
                reason="range stdev is 0",
                regime=MarketRegime.RANGE,
            )
        upper = mean + self._band_k * stdev
        lower = mean - self._band_k * stdev
        exit_factor = Decimal("0.2") if self._exit_at_mean else Decimal("0.5")
        inner = exit_factor * self._band_k * stdev
        width_pct = (Decimal("2") * self._band_k * stdev) / mean if mean > 0 else Decimal("0")
        values: dict[str, TraceValue] = {
            "close": bar.close,
            "mean": mean,
            "upper": upper,
            "lower": lower,
            "stdev": stdev,
            "z": (bar.close - mean) / stdev,
            # |z| against the band width: 0 = on the band, -20% = 20% inside it.
            "margin_pct": margin_pct(abs((bar.close - mean) / stdev), self._band_k),
            "width_pct": width_pct,
        }
        thresholds["exit_band_z"] = exit_factor * self._band_k
        if self._min_band_width_pct > 0:
            thresholds["min_band_width_pct"] = self._min_band_width_pct
        if bar.close <= lower:
            if self._min_band_width_pct > 0 and width_pct < self._min_band_width_pct:
                self._trace = (
                    step(
                        Stage.STRATEGY,
                        "RangeMeanReversion",
                        Verdict.INFO,
                        values=values,
                        thresholds=thresholds,
                        note="close at lower band but band width below minimum: hold",
                    ),
                )
                return None
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "RangeMeanReversion",
                    Verdict.EMIT,
                    result="buy",
                    values=values,
                    thresholds=thresholds,
                    note="close at or below the lower band",
                ),
            )
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.BUY,
                bar_ts_utc=bar.ts_utc,
                reason="range lower band",
                regime=MarketRegime.RANGE,
            )
        if bar.close >= upper:
            if not self._allow_short:
                self._trace = (
                    step(
                        Stage.STRATEGY,
                        "RangeMeanReversion",
                        Verdict.EMIT,
                        result="flat",
                        values=values,
                        thresholds=thresholds,
                        note="close at upper band (short disabled): take profit",
                    ),
                )
                return Signal(
                    instrument_id=self._instrument_id,
                    side=SignalSide.FLAT,
                    bar_ts_utc=bar.ts_utc,
                    reason="range upper band take profit",
                    regime=MarketRegime.RANGE,
                )
            if self._min_band_width_pct > 0 and width_pct < self._min_band_width_pct:
                self._trace = (
                    step(
                        Stage.STRATEGY,
                        "RangeMeanReversion",
                        Verdict.INFO,
                        values=values,
                        thresholds=thresholds,
                        note="close at upper band but band width below minimum: hold",
                    ),
                )
                return None
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "RangeMeanReversion",
                    Verdict.EMIT,
                    result="sell",
                    values=values,
                    thresholds=thresholds,
                    note="close at or above the upper band",
                ),
            )
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.SELL,
                bar_ts_utc=bar.ts_utc,
                reason="range upper band",
                regime=MarketRegime.RANGE,
            )
        if abs(bar.close - mean) <= inner:
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "RangeMeanReversion",
                    Verdict.EMIT,
                    result="flat",
                    values=values,
                    thresholds=thresholds,
                    note="close back near the mean: reversion complete",
                ),
            )
            return Signal(
                instrument_id=self._instrument_id,
                side=SignalSide.FLAT,
                bar_ts_utc=bar.ts_utc,
                reason="range mean revert complete",
                regime=MarketRegime.RANGE,
            )
        self._trace = (
            step(
                Stage.STRATEGY,
                "RangeMeanReversion",
                Verdict.INFO,
                values=values,
                thresholds=thresholds,
                note="close between the bands and away from the mean: hold",
            ),
        )
        return None


def _mean_stdev(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    count = Decimal(len(values))
    mean = sum(values, Decimal("0")) / count
    if len(values) < 2:
        return mean, Decimal("0")
    variance = sum(((item - mean) ** 2 for item in values), Decimal("0")) / (count - 1)
    return mean, variance.sqrt()
