from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.pairs.cointegration import CointegrationResult, fit_cointegration
from nautilus_lab.domain.pairs.ou import OuFit, fit_ou_half_life, z_score
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.signals import LegIntent, SignalSide, SpreadSignal
from nautilus_lab.domain.windows import RollingWindow


@dataclass
class _PairState:
    coint: CointegrationResult
    ou: OuFit
    open_bars: int = 0
    in_position: bool = False
    direction: int = 0


class PairsTrading:
    """Cointegrated pairs mean reversion on aligned closed bars."""

    def __init__(self, *, leg_a: str, leg_b: str, params: PairsParams) -> None:
        self._leg_a = leg_a
        self._leg_b = leg_b
        self._params = params
        self._closes_a = RollingWindow(params.lookback)
        self._closes_b = RollingWindow(params.lookback)
        self._state: _PairState | None = None
        self._bars_since_refit = 0

    def on_bars(self, bar_a: OhlcvBar, bar_b: OhlcvBar) -> SpreadSignal | None:
        self._closes_a.push(bar_a.close)
        self._closes_b.push(bar_b.close)
        if not self._closes_a.full:
            return None
        if self._state is None:
            self._state = self._fit_state()
            if self._state is None:
                return None
            self._bars_since_refit = 0

        refit_signal = self._maybe_refit(bar_a.ts_utc)
        if refit_signal is not None:
            return refit_signal

        spread = self._current_spread(bar_a.close, bar_b.close)
        z = z_score(spread, self._state.ou.mean, self._state.ou.sigma)
        ts = bar_a.ts_utc

        if self._state.in_position:
            self._state.open_bars += 1
            time_stop = int(self._state.ou.half_life_bars * 2)
            if self._state.open_bars >= time_stop:
                self._state.in_position = False
                self._state.open_bars = 0
                return self._flat_signal(ts, "pairs time stop")
            if abs(z) <= self._params.z_exit:
                self._state.in_position = False
                self._state.open_bars = 0
                return self._flat_signal(ts, "pairs z exit")
            return None

        if z >= self._params.z_entry:
            self._state.in_position = True
            self._state.direction = -1
            self._state.open_bars = 0
            return self._entry_signal(ts, z, short_a=True, reason="pairs z high short spread")
        if z <= -self._params.z_entry:
            self._state.in_position = True
            self._state.direction = 1
            self._state.open_bars = 0
            return self._entry_signal(ts, z, short_a=False, reason="pairs z low long spread")
        return None

    def _maybe_refit(self, ts: datetime) -> SpreadSignal | None:
        refit_every = self._params.refit_every_bars
        if refit_every <= 0:
            return None
        self._bars_since_refit += 1
        if self._bars_since_refit < refit_every:
            return None
        self._bars_since_refit = 0
        was_in_position = self._state is not None and self._state.in_position
        new_state = self._fit_state()
        if new_state is None:
            if was_in_position and self._state is not None:
                hedge = self._state.coint.hedge_ratio
                half_life = self._state.ou.half_life_bars
                self._state = None
                return self._flat_signal(ts, "pairs cointegration break", hedge, half_life)
            self._state = None
            return None
        if was_in_position:
            hedge = (
                self._state.coint.hedge_ratio
                if self._state is not None
                else new_state.coint.hedge_ratio
            )
            half_life = (
                self._state.ou.half_life_bars
                if self._state is not None
                else new_state.ou.half_life_bars
            )
            self._state = new_state
            return self._flat_signal(ts, "pairs refit flatten", hedge, half_life)
        self._state = new_state
        return None

    def _fit_state(self) -> _PairState | None:
        y = self._closes_a.values()
        x = self._closes_b.values()
        coint = fit_cointegration(y, x)
        if coint.adf_pvalue > self._params.adf_pvalue_max:
            return None
        spread = tuple(
            item_y - coint.intercept - coint.hedge_ratio * item_x
            for item_y, item_x in zip(y, x, strict=True)
        )
        ou = fit_ou_half_life(spread)
        if ou.half_life_bars > Decimal(self._params.max_half_life_bars):
            return None
        return _PairState(coint=coint, ou=ou)

    def _current_spread(self, price_a: Decimal, price_b: Decimal) -> Decimal:
        assert self._state is not None
        return price_a - self._state.coint.intercept - self._state.coint.hedge_ratio * price_b

    def _entry_signal(
        self,
        ts: datetime,
        z: Decimal,
        *,
        short_a: bool,
        reason: str,
    ) -> SpreadSignal:
        assert self._state is not None
        hedge = self._state.coint.hedge_ratio
        if short_a:
            leg_a = LegIntent(self._leg_a, SignalSide.SELL, Decimal("1"))
            leg_b = LegIntent(self._leg_b, SignalSide.BUY, abs(hedge))
        else:
            leg_a = LegIntent(self._leg_a, SignalSide.BUY, Decimal("1"))
            leg_b = LegIntent(self._leg_b, SignalSide.SELL, abs(hedge))
        return SpreadSignal(
            leg_a=leg_a,
            leg_b=leg_b,
            bar_ts_utc=ts,
            reason=reason,
            hedge_ratio=hedge,
            z_score=z,
            half_life_bars=self._state.ou.half_life_bars,
        )

    def _flat_signal(
        self,
        ts: datetime,
        reason: str,
        hedge_ratio: Decimal | None = None,
        half_life_bars: Decimal | None = None,
    ) -> SpreadSignal:
        assert self._state is not None or hedge_ratio is not None
        hedge = hedge_ratio if hedge_ratio is not None else self._state.coint.hedge_ratio  # type: ignore[union-attr]
        half_life = (
            half_life_bars if half_life_bars is not None else self._state.ou.half_life_bars  # type: ignore[union-attr]
        )
        return SpreadSignal(
            leg_a=LegIntent(self._leg_a, SignalSide.FLAT),
            leg_b=LegIntent(self._leg_b, SignalSide.FLAT),
            bar_ts_utc=ts,
            reason=reason,
            hedge_ratio=hedge,
            z_score=None,
            half_life_bars=half_life,
        )
