from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from math import sqrt

from nautilus_lab.domain.bars import OhlcvBar


class SelectionMetric(StrEnum):
    """What the in-sample parameter search maximises (application/score.py)."""

    PNL = "pnl"
    SHARPE = "sharpe"
    CALMAR = "calmar"


#: Bars per year for each supported interval (crypto trades 24/7).
PERIODS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    fees_paid: Decimal
    max_drawdown: Decimal
    turnover: Decimal
    sharpe_like: Decimal | None
    # Two-sided traded notional (entries AND exits, from the engine's fills report).
    # `turnover` above counts entry notional only, so it cannot be used as the base
    # of a per-unit cost: doing that would inflate breakeven roughly twofold.
    traded_notional: Decimal = Decimal("0")
    breakeven_cost: Decimal | None = None
    # `sharpe_like` scaled by sqrt(bars per year). The per-bar number cannot be compared
    # across timeframes (a 1m and a 1h run differ by sqrt(60) for the same edge); this
    # one can. None when the bar interval is unknown or the curve is not bar-sampled.
    sharpe_annualized: Decimal | None = None
    # Sample standard deviation of the per-bar equity returns: the strategy's realized
    # risk, which the volatility-matched buy & hold is scaled to (docs/27 R-4). None when
    # the curve is too short to measure.
    return_volatility: Decimal | None = None

    @property
    def paid_cost_rate(self) -> Decimal | None:
        """Cost actually paid per unit of traded notional — the number to compare c* with.

        Same units as maker/taker (fraction of notional), so "we paid 5.0 bps and
        breakeven is 7.3 bps" is a direct reading. None when nothing was traded.
        """
        if self.traded_notional <= 0:
            return None
        return self.fees_paid / self.traded_notional


def buy_and_hold_return(bars: Sequence[OhlcvBar]) -> Decimal | None:
    """Close-to-close return of simply holding the instrument across the window.

    Every walk-forward fold needs this baseline: a long-only robot that returns 4%
    while the instrument returned 12% has not added value, it has just taken
    directional risk. Returns None when the window is too short to measure.
    """
    if len(bars) < 2:
        return None
    first = bars[0].close
    if first == 0:
        return None
    return (bars[-1].close - first) / first


def compute_metrics(
    *,
    starting_equity: Decimal,
    equity_curve: tuple[Decimal, ...],
    fees_paid: Decimal,
    turnover: Decimal,
    traded_notional: Decimal = Decimal("0"),
    ending_equity: Decimal | None = None,
    periods_per_year: int | None = None,
) -> BacktestMetrics:
    max_dd = _max_drawdown(equity_curve, starting_equity)
    sharpe = _sharpe_like(equity_curve)
    annualized = (
        None
        if sharpe is None or periods_per_year is None or periods_per_year <= 0
        else sharpe * Decimal(str(sqrt(periods_per_year)))
    )
    net_pnl = _net_pnl(starting_equity, equity_curve, ending_equity)
    return BacktestMetrics(
        fees_paid=fees_paid,
        max_drawdown=max_dd,
        turnover=turnover,
        sharpe_like=sharpe,
        traded_notional=traded_notional,
        breakeven_cost=breakeven_cost(
            net_pnl=net_pnl,
            fees_paid=fees_paid,
            traded_notional=traded_notional,
        ),
        sharpe_annualized=annualized,
        return_volatility=sample_volatility(return_series_from_equity(equity_curve)),
    )


def breakeven_cost(
    *,
    net_pnl: Decimal | None,
    fees_paid: Decimal,
    traded_notional: Decimal,
) -> Decimal | None:
    """Largest constant cost per unit of traded notional that leaves PnL at zero.

    `net_pnl` is measured after fees, so the gross result is `net_pnl + fees_paid`,
    and the answer is `gross / traded_notional` — a cost rate in the same units as
    maker/taker (fraction of notional). A strategy that loses money even before
    costs gets a negative number, which is the honest reading: free execution would
    not have saved it.

    None (not zero) when there is nothing to divide by: no fills means no
    measurement, and "0" would claim the strategy breaks even at zero cost.
    """
    if net_pnl is None or traded_notional <= 0:
        return None
    return (net_pnl + fees_paid) / traded_notional


def _net_pnl(
    starting_equity: Decimal,
    equity_curve: tuple[Decimal, ...],
    ending_equity: Decimal | None,
) -> Decimal | None:
    """P&L after fees. Prefers the engine's ending balance over the strategy's curve."""
    if ending_equity is not None:
        return ending_equity - starting_equity
    if not equity_curve:
        return None
    return equity_curve[-1] - starting_equity


def _max_drawdown(equity_curve: tuple[Decimal, ...], starting: Decimal) -> Decimal:
    if not equity_curve:
        return Decimal("0")
    peak = starting
    worst = Decimal("0")
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > worst:
                worst = dd
    return worst


def _sharpe_like(equity_curve: tuple[Decimal, ...]) -> Decimal | None:
    if len(equity_curve) < 3:
        return None
    returns = return_series_from_equity(equity_curve)
    if len(returns) < 2:
        return None
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    std = sample_volatility(returns)
    if std is None or std == 0:
        return None
    return mean / std


def return_series_from_bars(bars: Sequence[OhlcvBar]) -> list[Decimal]:
    """Close-to-close percentage returns of a bar sequence: (C_t - C_{t-1}) / C_{t-1}."""
    if len(bars) < 2:
        return []
    returns: list[Decimal] = []
    prev = bars[0].close
    for bar in bars[1:]:
        if prev > 0:
            returns.append((bar.close - prev) / prev)
        prev = bar.close
    return returns


def return_series_from_equity(equity_curve: tuple[Decimal, ...]) -> list[Decimal]:
    """Period-to-period returns of an equity curve: (E_t - E_{t-1}) / E_{t-1}."""
    if len(equity_curve) < 2:
        return []
    returns: list[Decimal] = []
    prev = equity_curve[0]
    for equity in equity_curve[1:]:
        if prev > 0:
            returns.append((equity - prev) / prev)
        prev = equity
    return returns


def sample_volatility(returns: Sequence[Decimal]) -> Decimal | None:
    """Sample standard deviation (ddof=1) of a return sequence. None if fewer than 2 points."""
    if len(returns) < 2:
        return None
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((r - mean) ** 2 for r in returns) / Decimal(len(returns) - 1)
    if variance <= 0:
        return Decimal("0")
    return Decimal(str(sqrt(float(variance))))


def vol_matched_buy_and_hold_return(
    *,
    bars: Sequence[OhlcvBar],
    equity_curve: tuple[Decimal, ...],
    max_leverage: Decimal = Decimal("2.0"),
) -> Decimal | None:
    """Volatility-matched Buy & Hold benchmark return (docs/roadmap R-4).

    Raw Buy & Hold represents 100% long delta exposure with full asset volatility
    (often 60-90% annualized in crypto). A strategy taking conservative, selective
    exposure (e.g. 15% realized vol) is unfairly penalised in a bull run and unfairly
    flattered in a bear market if compared directly against unscaled B&H.

    This benchmark scales the underlying asset's buy-and-hold return by the ratio of
    realized strategy volatility to realized asset volatility:
        k = min(sigma_strat / sigma_asset, max_leverage)
        return_vol_matched = k * return_bnh

    If strategy took 0 risk (constant equity), k = 0, returning 0.0 (cash return).
    Returns None when the window is too short or asset volatility is non-positive.
    """
    strat_vol = sample_volatility(return_series_from_equity(equity_curve))
    return vol_matched_from_volatility(
        bars=bars, strategy_volatility=strat_vol, max_leverage=max_leverage
    )


def vol_matched_from_volatility(
    *,
    bars: Sequence[OhlcvBar],
    strategy_volatility: Decimal | None,
    max_leverage: Decimal = Decimal("2.0"),
) -> Decimal | None:
    """`vol_matched_buy_and_hold_return` for a caller that kept only the strategy's
    realized volatility (`BacktestMetrics.return_volatility`), not its whole curve.

    Both volatilities must be per bar of the same interval: the equity curve is sampled
    on every bar, and so are the closes.
    """
    bnh_return = buy_and_hold_return(bars)
    if bnh_return is None:
        return None

    asset_vol = sample_volatility(return_series_from_bars(bars))
    if asset_vol is None or asset_vol <= 0:
        return None
    if strategy_volatility is None:
        return None
    if strategy_volatility <= 0:
        return Decimal("0")

    scaling = strategy_volatility / asset_vol
    if max_leverage > 0 and scaling > max_leverage:
        scaling = max_leverage

    return scaling * bnh_return
