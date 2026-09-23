"""Cross-sectional momentum: hold the recent winners of a basket, rebalance on a schedule.

Mechanism (why this might pay, not just that it did): crypto majors trend together,
but capital rotates between them — the coins that led over the last few weeks tend to
keep leading for a while (time-series and cross-sectional momentum are among the few
effects documented across asset classes and decades). The strategy ranks the basket by
past return, holds the top `top_n`, and re-ranks every `rebalance_every` bars.

Two safety rails come with the textbook version:

* `skip_bars` — the most recent bar is left out of the score; the last day's move
  tends to reverse (short-term reversal) and would otherwise dominate the ranking.
* `require_positive` ("dual momentum") — a coin is held only if its own momentum is
  positive. In a market-wide crash every coin ranks, so a pure ranking would stay fully
  invested all the way down; the absolute filter moves the book to cash instead.

Long-only, spot, no leverage: weights sum to at most 1 and never go negative. This is
the domain rule only — execution, costs and the equity ledger live in
`application/xsmom_backtest.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from math import sqrt


class Weighting(StrEnum):
    EQUAL = "equal"
    INVERSE_VOL = "inverse_vol"


@dataclass(frozen=True, slots=True)
class XsMomParams:
    lookback_bars: int = 30
    skip_bars: int = 1
    top_n: int = 3
    rebalance_every: int = 7
    require_positive: bool = True
    weighting: Weighting = Weighting.EQUAL
    vol_window: int = 30

    def __post_init__(self) -> None:
        if self.lookback_bars < 1:
            raise ValueError("lookback_bars must be >= 1")
        if self.skip_bars < 0:
            raise ValueError("skip_bars must be >= 0")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.rebalance_every < 1:
            raise ValueError("rebalance_every must be >= 1")
        if self.vol_window < 2:
            raise ValueError("vol_window must be >= 2")

    @property
    def warmup_bars(self) -> int:
        """Closes needed before the first ranking is possible."""
        needed = self.lookback_bars + self.skip_bars + 1
        if self.weighting is Weighting.INVERSE_VOL:
            needed = max(needed, self.vol_window + 1)
        return needed

    def label(self) -> str:
        return (
            f"lookback={self.lookback_bars} skip={self.skip_bars} top_n={self.top_n} "
            f"rebalance={self.rebalance_every} positive_only={self.require_positive} "
            f"weighting={self.weighting.value}"
        )


def momentum_score(closes: Sequence[Decimal], *, lookback: int, skip: int) -> Decimal | None:
    """Return from `lookback + skip` bars ago to `skip` bars ago; None if too short."""
    if len(closes) < lookback + skip + 1:
        return None
    end = closes[-1 - skip]
    start = closes[-1 - skip - lookback]
    if start <= 0:
        return None
    return end / start - 1


def realized_vol(closes: Sequence[Decimal], window: int) -> Decimal | None:
    """Sample std of simple returns over the last `window` returns."""
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1) :]
    returns = [float(tail[i] / tail[i - 1] - 1) for i in range(1, len(tail)) if tail[i - 1] > 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0:
        return None
    return Decimal(str(sqrt(variance)))


def target_weights(
    closes_by_symbol: Mapping[str, Sequence[Decimal]], params: XsMomParams
) -> dict[str, Decimal]:
    """Target portfolio weights from closes known at the decision bar (inclusive).

    Symbols whose history is too short are skipped rather than scored as zero. Ties
    are broken by symbol name so the result never depends on dict ordering.
    """
    scored: list[tuple[Decimal, str]] = []
    for symbol, closes in closes_by_symbol.items():
        score = momentum_score(closes, lookback=params.lookback_bars, skip=params.skip_bars)
        if score is None:
            continue
        if params.require_positive and score <= 0:
            continue
        scored.append((score, symbol))
    scored.sort(key=lambda item: (-item[0], item[1]))
    chosen = [symbol for _, symbol in scored[: params.top_n]]
    if not chosen:
        return {}

    if params.weighting is Weighting.INVERSE_VOL:
        inverse: dict[str, Decimal] = {}
        for symbol in chosen:
            vol = realized_vol(closes_by_symbol[symbol], params.vol_window)
            if vol is not None and vol > 0:
                inverse[symbol] = Decimal("1") / vol
        if inverse:
            total = sum(inverse.values(), Decimal("0"))
            weights = {symbol: value / total for symbol, value in inverse.items()}
            return _cap_to_top_n(weights, params.top_n)

    # Equal weight across `top_n` slots, not across the survivors: when the absolute
    # filter leaves only one coin, it gets 1/top_n and the rest stays in cash.
    slot = Decimal("1") / Decimal(params.top_n)
    return dict.fromkeys(chosen, slot)


def _cap_to_top_n(weights: dict[str, Decimal], top_n: int) -> dict[str, Decimal]:
    """Inverse-vol weights, scaled so partial selections keep the missing slots in cash."""
    filled = Decimal(len(weights)) / Decimal(top_n)
    return {symbol: weight * filled for symbol, weight in weights.items()}
