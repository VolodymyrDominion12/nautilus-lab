from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from nautilus_lab.application.dtos import BacktestRequest
from nautilus_lab.domain.align import align_bars_inner_join
from nautilus_lab.domain.bars import BarOrigin, OhlcvBar, validate_bar
from nautilus_lab.domain.ports import BarCatalog, TakerFlowCatalog
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.stress_slices import resolve_stress_slice
from nautilus_lab.infrastructure.nautilus.instrument import binance_symbol_for_instrument
from nautilus_lab.infrastructure.nautilus.synthetic_bars import (
    synthetic_ohlcv,
    synthetic_regime_ohlcv,
)
from nautilus_lab.infrastructure.nautilus.synthetic_pairs import synthetic_cointegrated_pair
from nautilus_lab.infrastructure.timeframe import interval_from_bar_type, nautilus_bar_type


class ResearchBarFeed:
    """Catalog of real history, or deterministic synthetic bars for tests.

    The catalog itself stores only what Nautilus `Bar` can hold, so the taker split
    (kline field 9) is re-attached here from its own series before any consumer sees a
    bar. Without this join every order-flow feature would silently fall back to the
    tick-rule proxy — the defect this path exists to close.
    """

    def __init__(self, catalog: BarCatalog, *, taker_flow: TakerFlowCatalog | None = None) -> None:
        self._catalog = catalog
        self._taker_flow = taker_flow

    def load(self, request: BacktestRequest) -> list[OhlcvBar]:
        if request.robot is RobotName.PAIRS:
            multi = self.load_multi(request)
            leg_a = request.pairs.leg_a
            return list(multi[leg_a])
        if request.source is BarOrigin.SYNTHETIC:
            return _synthetic(request)
        start, end = _stress_window(request)
        bars = self._catalog.load(
            bar_type=request.bar_type,
            start=start,
            end=end,
        )
        return self._with_taker_flow(
            bars,
            instrument_id=request.instrument_id,
            interval=interval_from_bar_type(request.bar_type),
            start=start,
            end=end,
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
            bars = _synthetic(request)
            return {request.instrument_id: bars}
        start, end = _stress_window(request)
        interval = interval_from_bar_type(request.bar_type)
        ids = request.instrument_ids or (request.pairs.leg_a, request.pairs.leg_b)
        raw: dict[str, list[OhlcvBar]] = {}
        for instrument_id in ids:
            bar_type = nautilus_bar_type(instrument_id, interval)
            loaded = self._catalog.load(bar_type=bar_type, start=start, end=end)
            raw[instrument_id] = self._with_taker_flow(
                loaded, instrument_id=instrument_id, interval=interval, start=start, end=end
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
