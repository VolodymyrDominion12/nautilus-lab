from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from nautilus_lab.domain.errors import (
    InvalidRiskError,
    LiveTradingDisabledError,
)
from nautilus_lab.domain.portfolio_risk import fractional_kelly_cap, historical_var
from nautilus_lab.domain.risk import AccountSnapshot, RiskDecision, RiskLimits
from nautilus_lab.domain.trading_mode import TradingMode


def size_position(
    *,
    equity: Decimal,
    price: Decimal,
    stop_distance: Decimal,
    risk_fraction: Decimal,
    qty_step: Decimal,
) -> Decimal:
    """Risk a fraction of equity across `stop_distance`, capped at 1x notional."""
    if equity <= 0:
        raise InvalidRiskError("equity must be > 0")
    if price <= 0:
        raise InvalidRiskError("price must be > 0")
    if stop_distance <= 0:
        raise InvalidRiskError("stop_distance must be > 0")
    if risk_fraction <= 0 or risk_fraction > 1:
        raise InvalidRiskError("risk_fraction must be in (0, 1]")
    if qty_step <= 0:
        raise InvalidRiskError("qty_step must be > 0")

    risk_cash = equity * risk_fraction
    raw_qty = risk_cash / stop_distance
    max_qty = equity / price
    qty = min(raw_qty, max_qty)
    steps = (qty / qty_step).to_integral_value(rounding=ROUND_DOWN)
    return steps * qty_step


def effective_risk_fraction(
    limits: RiskLimits,
    *,
    win_rate: Decimal | None = None,
    reward_risk: Decimal | None = None,
) -> Decimal:
    """Cap configured risk with fractional Kelly when stats are available."""
    if win_rate is None or reward_risk is None:
        return limits.risk_per_trade
    kelly_cap = fractional_kelly_cap(
        win_rate=win_rate,
        reward_risk=reward_risk,
        fraction=limits.kelly_fraction,
    )
    if kelly_cap <= 0:
        return limits.risk_per_trade
    return min(limits.risk_per_trade, kelly_cap)


def stop_distance(
    price: Decimal,
    limits: RiskLimits,
    *,
    atr: Decimal | None = None,
) -> Decimal:
    """ATR-scaled stop when ATR is available; otherwise percent stop."""
    if atr is not None and atr > 0:
        return atr * limits.atr_stop_multiplier
    return price * limits.stop_pct


def evaluate_entry(snapshot: AccountSnapshot, limits: RiskLimits) -> RiskDecision:
    """Circuit breaker before a new entry. Flattening is the caller's job."""
    if snapshot.equity <= 0:
        return RiskDecision(False, "non-positive equity")
    if snapshot.day_start_equity <= 0:
        return RiskDecision(False, "non-positive day-start equity")
    if snapshot.peak_equity <= 0:
        return RiskDecision(False, "non-positive peak equity")

    daily_loss = (snapshot.day_start_equity - snapshot.equity) / snapshot.day_start_equity
    if daily_loss >= limits.max_daily_loss:
        return RiskDecision(False, "daily loss circuit breaker")

    drawdown = (snapshot.peak_equity - snapshot.equity) / snapshot.peak_equity
    if drawdown >= limits.max_drawdown:
        return RiskDecision(False, "max drawdown circuit breaker")

    if snapshot.open_positions > limits.max_open_positions:
        return RiskDecision(False, "max open positions exceeded")

    if snapshot.recent_returns:
        var_99 = historical_var(snapshot.recent_returns, confidence=Decimal("0.99"))
        if var_99 is not None and var_99 >= limits.max_var_99:
            return RiskDecision(False, "portfolio VaR 99% circuit breaker")

    return RiskDecision(True, "ok")


def require_simulated_mode(mode: TradingMode) -> None:
    """Live is never allowed from this lab until an execution adapter is added on request."""

    if mode is TradingMode.LIVE:
        raise LiveTradingDisabledError(
            "Live trading is disabled. This lab only runs research backtests."
        )
    if mode is TradingMode.PAPER:
        return
    if mode is not TradingMode.RESEARCH:
        raise LiveTradingDisabledError(f"unsupported trading mode: {mode}")
