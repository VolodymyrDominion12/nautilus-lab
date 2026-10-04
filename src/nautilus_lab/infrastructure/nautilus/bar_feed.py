from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.align import align_bars_inner_join
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar, validate_bar
from nautilus_lab.domain.errors import CatalogEmptyError
from nautilus_lab.domain.ports import BarCatalog, TakerFlowCatalog
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.stress_slices import resolve_stress_slice
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_for_instrument
from nautilus_lab.infrastructure.nautilus.synthetic_bars import (
    synthetic_ohlcv,
    synthetic_regime_ohlcv,
)
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import (
    synthetic_cointegrated_pair,
    synthetic_funding_pair,
)
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type


class ResearchBarFeed:
    """Catalog of real history, or deterministic synthetic bars for tests.

    The catalog itself stores only what Nautilus `Bar` can hold, so the taker split
    (kline field 9) is re-attached here from its own series before any consumer sees a
    bar. Without this join every order-flow feature would silently fall back to the
    tick-rule proxy — the defect this path exists to close.
    """

    def __init__(
        self,
        catalog: BarCatalog,
        *,
        taker_flow: TakerFlowCatalog | None = None,
        quality_gate: Callable[[str], str] | None = None,
    ) -> None:
        self._catalog = catalog
        self._taker_flow = taker_flow
        # Checked before a catalog series is read (infrastructure/quality_gate.py): a
        # series whose QC failed raises instead of being backtested. Synthetic bars
        # have no catalog and are never checked.
        self._quality_gate = quality_gate

    @staticmethod
    def _slice_days(bars: list[OhlcvBar], days: int | None) -> list[OhlcvBar]:
        if not days or days <= 0 or not bars:
            return bars
        cutoff = bars[-1].ts_utc - timedelta(days=days)
        sliced = [b for b in bars if b.ts_utc >= cutoff]
        if not sliced:
            raise CatalogEmptyError(f"no bars found in the last {days} days")
        return sliced

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        if request.robot is RobotName.PAIRS:
            multi = self.load_multi(request)
            leg_a = request.pairs.leg_a
            return list(multi[leg_a])
        if request.robot is RobotName.FUNDING:
            multi = self.load_multi(request)
            spot_id = request.funding_spot_id or "ETH/USDT.SIM"
            return list(multi[spot_id])
        if request.source is BarOrigin.SYNTHETIC:
            return _synthetic(request)
        start, end = _stress_window(request)
        if self._quality_gate is not None:
            self._quality_gate(request.bar_type)
        bars = self._catalog.load(
            bar_type=request.bar_type,
            start=start,
            end=end,
        )
        bars = self._slice_days(bars, request.days)
        flow_start = bars[0].ts_utc if bars else start
        flow_end = bars[-1].ts_utc + timedelta(microseconds=1) if bars else end
        return self._with_taker_flow(
            bars,
            instrument_id=request.instrument_id,
            interval=interval_from_bar_type(request.bar_type),
            start=flow_start,
            end=flow_end,
        )

    def load_multi(self, request: BacktestRequest) -> dict[str, list[OhlcvBar]]:
        if request.source is BarOrigin.SYNTHETIC:
            if request.robot is RobotName.PAIRS:
                return synthetic_cointegrated_pair(
                    leg_a=request.pairs.leg_a,
                    leg_b=request.pairs.leg_b,
                    count=request.bar_count,
                    seed=request.seed,
                )
            if request.robot is RobotName.FUNDING:
                spot_id = request.funding_spot_id or "ETH/USDT.SIM"
                perp_id = request.funding_perp_id or "ETHUSDT-PERP.SIM"
                funding_bars, _ = synthetic_funding_pair(
                    spot_id=spot_id,
                    perp_id=perp_id,
                    count=request.bar_count,
                    seed=request.seed,
                )
                return funding_bars
            synth_bars = _synthetic(request)
            return {request.instrument_id: synth_bars}
        start, end = _stress_window(request)
        interval = interval_from_bar_type(request.bar_type)
        ids = request.instrument_ids or (
            (
                request.funding_spot_id or "ETH/USDT.SIM",
                request.funding_perp_id or "ETHUSDT-PERP.SIM",
            )
            if request.robot is RobotName.FUNDING
            else (request.pairs.leg_a, request.pairs.leg_b)
        )
        raw: dict[str, list[OhlcvBar]] = {}
        for instrument_id in ids:
            bar_type = nautilus_bar_type(instrument_id, interval)
            if self._quality_gate is not None:
                self._quality_gate(bar_type)
            loaded = self._catalog.load(bar_type=bar_type, start=start, end=end)
            raw[instrument_id] = loaded
        if request.days and request.days > 0 and raw:
            non_empty = [series for series in raw.values() if series]
            if non_empty:
                max_last_ts = max(series[-1].ts_utc for series in non_empty)
                cutoff = max_last_ts - timedelta(days=request.days)
                raw = {
                    inst: [b for b in series if b.ts_utc >= cutoff] for inst, series in raw.items()
                }
        for instrument_id in ids:
            series = raw[instrument_id]
            flow_start = series[0].ts_utc if series else start
            flow_end = series[-1].ts_utc + timedelta(microseconds=1) if series else end
            raw[instrument_id] = self._with_taker_flow(
                series,
                instrument_id=instrument_id,
                interval=interval,
                start=flow_start,
                end=flow_end,
            )
        aligned = align_bars_inner_join(raw)
        return {key: list(value) for key, value in aligned.items()}

    def _with_taker_flow(
        self,
        bars: list[OhlcvBar],
        *,
        instrument_id: str,
        interval: str,
        start: datetime | None,
        end: datetime | None,
    ) -> list[OhlcvBar]:
        if self._taker_flow is None:
            return bars
        symbol = binance_symbol_for_instrument(instrument_id)
        if symbol is None:
            return bars
        series: Mapping[datetime, Decimal] = self._taker_flow.load(
            symbol=symbol, interval=interval, start=start, end=end
        )
        if not series:
            return bars
        enriched: list[OhlcvBar] = []
        previous_ts: datetime | None = None
        for bar in bars:
            value = series.get(bar.ts_utc)
            joined = bar if value is None else replace(bar, taker_buy_base_volume=value)
            # Re-validate the join instead of trusting it: a flow series from another
            # interval would hand a bar more taker volume than the bar traded, and that
            # must fail loudly rather than tilt the order-flow feature.
            validate_bar(joined, previous_ts=previous_ts, now=joined.ts_utc)
            enriched.append(joined)
            previous_ts = joined.ts_utc
        return enriched


def _synthetic(request: BacktestRequest) -> list[OhlcvBar]:
    if request.robot is RobotName.REGIME:
        return synthetic_regime_ohlcv(
            instrument_id=request.instrument_id,
            count=request.bar_count,
            seed=request.seed,
        )
    return synthetic_ohlcv(
        instrument_id=request.instrument_id,
        count=request.bar_count,
        seed=request.seed,
    )


def _stress_window(request: BacktestRequest) -> tuple[datetime | None, datetime | None]:
    if request.stress_slice:
        slice_ = resolve_stress_slice(request.stress_slice)
        return slice_.start, slice_.end
    return request.start, request.end
