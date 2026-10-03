from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from nautilus_lab.domain.decision_trace import (
    Stage,
    TraceStep,
    TraceValue,
    Verdict,
    margin_pct,
    step,
)
from nautilus_lab.domain.signals import LegIntent, SignalSide, SpreadSignal


@dataclass(frozen=True, slots=True)
class FundingSnapshot:
    """One funding settlement.

    `index_price` is optional on purpose. Binance's `fapi/v1/fundingRate` response
    carries `markPrice` but **no** `indexPrice` (verified against the live endpoint),
    so an adapter that defaults index to mark silently makes the basis
    `(mark - index) / index` identically zero — a gate that can never fire and never
    complains. `None` here means "index unknown", which callers must treat as
    *no information*, never as "no divergence".

    `mark_price` is optional for the same reason. Binance's funding history returns an
    empty `markPrice` for settlements older than late 2023 (measured: every ingested
    series began on 2023-10-31 while 2020 was requested). Requiring a mark made the
    adapter drop those rows without a word, so the whole 2020-2023 funding history —
    the 2021 high-funding regime included — silently vanished. The settlement itself
    (time + rate) is the event; the mark is context and may be unknown.
    """

    instrument: str
    funding_rate: Decimal
    mark_price: Decimal | None
    index_price: Decimal | None
    ts_utc: datetime

    def basis(self) -> Decimal | None:
        """`(mark - index) / index`, or None when it cannot be computed honestly."""
        if self.mark_price is None or self.index_price is None or self.index_price <= 0:
            return None
        return (self.mark_price - self.index_price) / self.index_price


@dataclass(frozen=True, slots=True)
class FundingParams:
    min_net_apy: Decimal = Decimal("0.10")
    taker_fee: Decimal = Decimal("0.0005")
    # Funding intervals the position is expected to be held for (8h each on Binance
    # USD-M). The round trip costs two taker fees exactly once, so amortising them
    # over the holding period is what makes the APY gate comparable with the funding
    # rate. Charging the full round trip against *every* interval instead needs a
    # funding rate above 0.1% per 8h (~109% APY) to clear a 10% gate, which no
    # ordinary market ever pays — the robot could never open a position.
    holding_periods: int = 60
    basis_max: Decimal = Decimal("0.005")
    close_on_negative: bool = False
    min_exit_apy: Decimal | None = None
    min_holding_periods: int = 15
    max_holding_periods: int | None = None

    def __post_init__(self) -> None:
        if self.taker_fee < 0:
            raise ValueError("taker_fee must be >= 0")
        if self.holding_periods < 1:
            raise ValueError("holding_periods must be >= 1")
        if self.min_holding_periods < 0:
            raise ValueError("min_holding_periods must be >= 0")
        if self.max_holding_periods is not None and self.max_holding_periods < 1:
            raise ValueError("max_holding_periods must be >= 1")
        if self.basis_max < 0:
            raise ValueError("basis_max must be >= 0")


class FundingCashAndCarry:
    """Delta-neutral spot long + perp short when funding exceeds costs."""

    def __init__(
        self,
        *,
        spot_id: str,
        perp_id: str,
        params: FundingParams,
    ) -> None:
        self._spot_id = spot_id
        self._perp_id = perp_id
        self._params = params
        self._open = False
        self._periods_held: int = 0
        self._trace: tuple[TraceStep, ...] = ()

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def periods_held(self) -> int:
        return self._periods_held

    @property
    def last_trace(self) -> tuple[TraceStep, ...]:
        """Why the last settlement did (not) open or close the carry: APY and basis gates."""
        return self._trace

    def abort_entry(self) -> None:
        """Cancel an unfulfilled entry signal (e.g. blocked by risk, sizing, or warm-up)."""
        self._open = False
        self._periods_held = 0

    def on_funding(
        self,
        snapshot: FundingSnapshot,
        *,
        is_open: bool | None = None,
    ) -> SpreadSignal | None:
        if is_open is not None:
            if not is_open:
                self._open = False
                self._periods_held = 0
            else:
                self._open = True

        ts = snapshot.ts_utc
        basis = snapshot.basis()
        fee = self._round_trip_fee_per_interval()
        net = snapshot.funding_rate - fee
        annualized = net * Decimal("3") * Decimal("365")
        values: dict[str, TraceValue] = {
            "funding_rate": snapshot.funding_rate,
            "fee_per_interval": fee,
            "net_per_interval": net,
            "net_apy": annualized,
            "apy_margin_pct": margin_pct(annualized, self._params.min_net_apy),
            "basis": basis,
            "mark_price": snapshot.mark_price,
            "index_price": snapshot.index_price,
            "holding": "open" if self._open else "flat",
            "periods_held": self._periods_held,
        }
        thresholds: dict[str, TraceValue] = {
            "min_net_apy": self._params.min_net_apy,
            "min_exit_apy": self._params.min_exit_apy,
            "min_holding_periods": self._params.min_holding_periods,
            "max_holding_periods": self._params.max_holding_periods,
            "basis_max": self._params.basis_max,
            "holding_periods": self._params.holding_periods,
        }

        def explain(verdict: Verdict, result: str | None, note: str) -> None:
            self._trace = (
                step(
                    Stage.STRATEGY,
                    "FundingCarry",
                    verdict,
                    result=result,
                    values=values,
                    thresholds=thresholds,
                    note=note,
                ),
            )

        if basis is None:
            # An unusable snapshot must not crash the run, and must not be read as a
            # flat basis (0/0 is not "no divergence", it is "we do not know").
            missing = "mark price" if snapshot.mark_price is None else "index price"
            if self._open:
                self._open = False
                self._periods_held = 0
                explain(Verdict.EMIT, "flat", f"{missing} unknown: close the carry")
                return self._flat(ts, f"missing {missing}")
            explain(Verdict.SKIP, None, f"{missing} unknown: basis cannot be judged")
            return None

        if self._open:
            self._periods_held += 1
            values["periods_held"] = self._periods_held
            if self._params.close_on_negative and snapshot.funding_rate < 0:
                self._open = False
                self._periods_held = 0
                explain(Verdict.EMIT, "flat", "funding turned negative")
                return self._flat(ts, "negative funding")
            if abs(basis) > self._params.basis_max:
                self._open = False
                self._periods_held = 0
                explain(Verdict.EMIT, "flat", "|basis| above basis_max")
                return self._flat(ts, "basis divergence")
            if (
                self._params.min_exit_apy is not None
                and self._periods_held >= self._params.min_holding_periods
                and annualized < self._params.min_exit_apy
            ):
                self._open = False
                self._periods_held = 0
                explain(Verdict.EMIT, "flat", "funding decayed below min_exit_apy")
                return self._flat(ts, "funding decayed below min_exit_apy")
            if (
                self._params.max_holding_periods is not None
                and self._periods_held >= self._params.max_holding_periods
            ):
                self._open = False
                self._periods_held = 0
                explain(Verdict.EMIT, "flat", "maximum holding periods reached")
                return self._flat(ts, "max holding periods reached")
            explain(Verdict.INFO, None, "carry still valid: hold")
            return None

        if annualized < self._params.min_net_apy:
            explain(Verdict.INFO, None, "net APY after fees below min_net_apy")
            return None
        if abs(basis) > self._params.basis_max:
            explain(Verdict.INFO, None, "APY passes but |basis| above basis_max")
            return None
        self._open = True
        self._periods_held = 0
        explain(Verdict.EMIT, "buy", "net APY passes and basis is tight: open the carry")
        return SpreadSignal(
            leg_a=LegIntent(self._spot_id, SignalSide.BUY),
            leg_b=LegIntent(self._perp_id, SignalSide.SELL),
            bar_ts_utc=ts,
            reason="funding cash-and-carry",
            hedge_ratio=Decimal("1"),
            z_score=None,
            half_life_bars=None,
        )

    def _round_trip_fee_per_interval(self) -> Decimal:
        return self._params.taker_fee * Decimal("2") / Decimal(self._params.holding_periods)

    def _flat(self, ts: datetime, reason: str) -> SpreadSignal:
        return SpreadSignal(
            leg_a=LegIntent(self._spot_id, SignalSide.FLAT),
            leg_b=LegIntent(self._perp_id, SignalSide.FLAT),
            bar_ts_utc=ts,
            reason=reason,
            hedge_ratio=Decimal("1"),
        )
