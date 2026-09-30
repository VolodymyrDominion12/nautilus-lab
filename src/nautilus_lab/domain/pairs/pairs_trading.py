from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
from nautilus_lab.domain.pairs.cointegration import CointegrationResult, fit_cointegration
from nautilus_lab.domain.pairs.ou import OuFit, fit_ou_half_life, z_score
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.quantiles import empirical_quantile
from nautilus_lab.domain.signals import LegIntent, SignalSide, SpreadSignal
from nautilus_lab.domain.windows import RollingWindow


@dataclass
class _PairState:
    coint: CointegrationResult
    ou: OuFit
    spreads: tuple[Decimal, ...] = ()
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
        self._bars_until_retry = 0
        self._seen = 0
        self._trace: tuple[TraceStep, ...] = ()
        #: Diagnostics of the last cointegration fit, kept even when the fit failed the
        #: gate: "not cointegrated, p=0.31 > 0.05" is the answer to "why no trades".
        self._last_fit: dict[str, Decimal] = {}

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        """Why the last `on_bars` call did (not) trade: the fit gate, then the z-score leg."""
        return self._trace

    def on_bars(self, bar_a: OhlcvBar, bar_b: OhlcvBar) -> SpreadSignal | None:
        self._seen += 1
        self._trace = ()
        signal = self._decide(bar_a, bar_b)
        if not self._trace:
            self._trace = (self._fit_step(),)
        return signal

    def _decide(self, bar_a: OhlcvBar, bar_b: OhlcvBar) -> SpreadSignal | None:
        self._closes_a.push(bar_a.close)
        self._closes_b.push(bar_b.close)
        if not self._closes_a.full:
            self._trace = (
                warmup_step("PairsTrading", seen=self._seen, required=self._params.lookback),
            )
            return None
        if self._state is None:
            # `refit_every_bars` governs how often cointegration is re-evaluated, in both
            # directions: while the robot is waiting to enter a pair for the first time,
            # and after a periodic refit has closed the gate on a pair it already holds.
            # Probing every bar in the second case ran a fit on ~75% of bars instead of
            # the ~4% that `refit_every_bars=24` implies, which turned a rolling refit
            # into an hour-long walk-forward. `0` disables the cadence entirely, keeping
            # the legacy per-bar probe.
            if self._bars_until_retry > 0:
                self._bars_until_retry -= 1
                self._trace = (
                    self._fit_step(
                        note=f"not cointegrated at the last fit; next fit in "
                        f"{self._bars_until_retry + 1} bars"
                    ),
                )
                return None
            self._state = self._fit_state()
            if self._state is None:
                self._bars_until_retry = max(self._params.refit_every_bars - 1, 0)
                return None
            self._bars_since_refit = 0
            self._bars_until_retry = 0

        refit_signal = self._maybe_refit(bar_a.ts_utc)
        if refit_signal is not None:
            self._trace = (
                self._fit_step(),
                step(
                    Stage.STRATEGY,
                    "PairsTrading",
                    Verdict.EMIT,
                    result="flat",
                    note=refit_signal.reason,
                ),
            )
            return refit_signal
        if self._state is None:
            # A periodic refit that fails the gate clears the state and asks the robot to
            # stand aside; the next bar re-attempts the fit through the branch above.
            # Without this guard the flow fell through to `_current_spread()`, whose
            # `assert self._state is not None` raised and killed the whole `pairs` run as
            # soon as `refit_every_bars > 0`.
            return None

        spread = self._current_spread(bar_a.close, bar_b.close)
        z = z_score(spread, self._state.ou.mean, self._state.ou.sigma)
        ts = bar_a.ts_utc

        if self._state.in_position:
            self._state.open_bars += 1
            time_stop = int(self._state.ou.half_life_bars * 2)
            held: dict[str, TraceValue] = {
                "spread": spread,
                "z": z,
                "open_bars": self._state.open_bars,
                "time_stop_bars": time_stop,
                "direction": "long_spread" if self._state.direction > 0 else "short_spread",
                "z_exit_margin_pct": margin_pct(self._params.z_exit, abs(z)),
            }
            limits: dict[str, TraceValue] = {"z_exit": self._params.z_exit}
            if self._state.open_bars >= time_stop:
                self._state.in_position = False
                self._state.open_bars = 0
                self._trace = (
                    self._fit_step(),
                    self._z_step(Verdict.EMIT, "flat", held, limits, "time stop: 2x half-life"),
                )
                return self._flat_signal(ts, "pairs time stop")
            if abs(z) <= self._params.z_exit:
                self._state.in_position = False
                self._state.open_bars = 0
                self._trace = (
                    self._fit_step(),
                    self._z_step(Verdict.EMIT, "flat", held, limits, "|z| back inside z_exit"),
                )
                return self._flat_signal(ts, "pairs z exit")
            self._trace = (
                self._fit_step(),
                self._z_step(Verdict.INFO, None, held, limits, "spread not reverted yet: hold"),
            )
            return None

        # Only the entry path needs the thresholds, so they are resolved there
        # rather than on every bar: a position already open exits on `z_exit` or
        # the time stop, never on the entry gate.
        z_low, z_high = self._entry_thresholds()
        # How far the nearer entry threshold is: -20% = |z| is 20% short of the trigger.
        nearest = z_high if z >= 0 else z_low
        entry_values: dict[str, TraceValue] = {
            "spread": spread,
            "z": z,
            "z_margin_pct": margin_pct(abs(z), abs(nearest)),
        }
        entry_limits: dict[str, TraceValue] = {
            "z_low": z_low,
            "z_high": z_high,
            "z_exit": self._params.z_exit,
        }

        if z >= z_high:
            self._state.in_position = True
            self._state.direction = -1
            self._state.open_bars = 0
            self._trace = (
                self._fit_step(),
                self._z_step(Verdict.EMIT, "sell", entry_values, entry_limits, "z above z_high"),
            )
            return self._entry_signal(ts, z, short_a=True, reason="pairs z high short spread")
        if z <= z_low:
            self._state.in_position = True
            self._state.direction = 1
            self._state.open_bars = 0
            self._trace = (
                self._fit_step(),
                self._z_step(Verdict.EMIT, "buy", entry_values, entry_limits, "z below z_low"),
            )
            return self._entry_signal(ts, z, short_a=False, reason="pairs z low long spread")
        self._trace = (
            self._fit_step(),
            self._z_step(Verdict.INFO, None, entry_values, entry_limits, "z inside the band"),
        )
        return None

    def _z_step(
        self,
        verdict: Verdict,
        result: str | None,
        values: dict[str, TraceValue],
        thresholds: dict[str, TraceValue],
        note: str,
    ) -> TraceStep:
        return step(
            Stage.STRATEGY,
            "PairsTrading",
            verdict,
            result=result,
            values=values,
            thresholds=thresholds,
            note=note,
        )

    def _fit_step(self, note: str | None = None) -> TraceStep:
        """The cointegration gate: PASS while a fit is held, INFO (no trading) otherwise."""
        fit = self._last_fit
        thresholds: dict[str, TraceValue] = {
            "adf_pvalue_max": self._params.adf_pvalue_max,
            "max_half_life_bars": self._params.max_half_life_bars,
            "lookback": self._params.lookback,
        }
        if self._state is not None:
            return step(
                Stage.FILTER,
                "cointegration",
                Verdict.PASS,
                result="cointegrated",
                values={
                    "hedge_ratio": self._state.coint.hedge_ratio,
                    "adf_pvalue": self._state.coint.adf_pvalue,
                    "half_life_bars": self._state.ou.half_life_bars,
                    "spread_mean": self._state.ou.mean,
                    "spread_sigma": self._state.ou.sigma,
                },
                thresholds=thresholds,
                note=note,
            )
        return step(
            Stage.FILTER,
            "cointegration",
            Verdict.INFO,
            result="not_cointegrated" if fit else "no_fit",
            values={
                "adf_pvalue": fit.get("adf_pvalue"),
                "hedge_ratio": fit.get("hedge_ratio"),
                "half_life_bars": fit.get("half_life_bars"),
                "adf_margin_pct": margin_pct(self._params.adf_pvalue_max, fit.get("adf_pvalue")),
            },
            thresholds=thresholds,
            note=note or "the pair fails the cointegration gate: no entries",
        )

    def _entry_thresholds(self) -> tuple[Decimal, Decimal]:
        """(long, short) entry thresholds in z units for the current fit.

        With `z_entry_quantile` unset this is the fixed ``(-z_entry, +z_entry)``.
        With it set, the thresholds are the empirical ``p`` and ``1 - p``
        quantiles of the *same* spread window the fit came from, mapped into z
        with the same ``(mean, sigma)`` the live reading uses — so the comparison
        stays in one unit system.

        Using the fitted window rather than an expanding one is what keeps this
        free of lookahead: at ``refit_every_bars = 0`` the window is frozen for
        the life of the position, exactly like mu and sigma, so a threshold can
        never be revised by bars the robot had not yet seen.
        """
        state = self._fitted()
        probability = self._params.z_entry_quantile
        if probability is None:
            return -self._params.z_entry, self._params.z_entry
        ou = state.ou
        low = empirical_quantile(state.spreads, probability)
        high = empirical_quantile(state.spreads, Decimal("1") - probability)
        return (
            z_score(low, ou.mean, ou.sigma),
            z_score(high, ou.mean, ou.sigma),
        )

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
            # The pair is not cointegrated on this window: stand aside and re-test on the
            # next refit interval, not on every bar. `refit_every - 1` because the check
            # above decrements before it tests, so the next attempt lands exactly
            # `refit_every` bars after this failure. At `refit_every == 1` the robot still
            # probes every bar, which is what that setting asks for.
            self._bars_until_retry = max(refit_every - 1, 0)
            if was_in_position and self._state is not None:
                hedge = self._state.coint.hedge_ratio
                half_life = self._state.ou.half_life_bars
                self._state = None
                return self._flat_signal(ts, "pairs cointegration break", hedge, half_life)
            self._state = None
            return None
        self._bars_until_retry = 0
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
        self._last_fit = {"adf_pvalue": coint.adf_pvalue, "hedge_ratio": coint.hedge_ratio}
        if coint.adf_pvalue > self._params.adf_pvalue_max:
            return None
        spread = tuple(
            item_y - coint.intercept - coint.hedge_ratio * item_x
            for item_y, item_x in zip(y, x, strict=True)
        )
        ou = fit_ou_half_life(spread)
        self._last_fit["half_life_bars"] = ou.half_life_bars
        if ou.half_life_bars > Decimal(self._params.max_half_life_bars):
            return None
        return _PairState(coint=coint, ou=ou, spreads=spread)

    def _fitted(self) -> _PairState:
        """The current fit. Only called after `_fit_state` succeeded; says so if not.

        An explicit raise rather than `assert`: `python -O` strips asserts, and this
        invariant guards which hedge ratio an order is sized with.
        """
        if self._state is None:
            raise RuntimeError("pairs robot used before a cointegration fit")
        return self._state

    def _current_spread(self, price_a: Decimal, price_b: Decimal) -> Decimal:
        state = self._fitted()
        return price_a - state.coint.intercept - state.coint.hedge_ratio * price_b

    def _entry_signal(
        self,
        ts: datetime,
        z: Decimal,
        *,
        short_a: bool,
        reason: str,
    ) -> SpreadSignal:
        state = self._fitted()
        hedge = state.coint.hedge_ratio
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
            half_life_bars=state.ou.half_life_bars,
        )

    def _flat_signal(
        self,
        ts: datetime,
        reason: str,
        hedge_ratio: Decimal | None = None,
        half_life_bars: Decimal | None = None,
    ) -> SpreadSignal:
        hedge = hedge_ratio if hedge_ratio is not None else self._fitted().coint.hedge_ratio
        half_life = (
            half_life_bars if half_life_bars is not None else self._fitted().ou.half_life_bars
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
