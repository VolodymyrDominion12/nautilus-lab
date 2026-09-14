from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from nautilus_lab.domain.errors import (
    InvalidRiskError,
    LiveTradingDisabledError,
)
from nautilus_lab.domain.portfolio_risk import (
    fractional_kelly_cap,
    historical_cvar,
    historical_var,
)
from nautilus_lab.domain.risk import AccountSnapshot, RiskDecision, RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.volatility import vol_scaled_risk_fraction


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


@dataclass
class TradeStats:
    wins: int = 0
    losses: int = 0
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    def win_rate(self) -> Decimal | None:
        if self.total_trades == 0:
            return None
        return Decimal(self.wins) / Decimal(self.total_trades)

    def reward_risk(self) -> Decimal | None:
        if self.gross_loss <= 0:
            return Decimal("3") if self.gross_profit > 0 else None
        return self.gross_profit / self.gross_loss

    def record(self, pnl: Decimal) -> None:
        if pnl > 0:
            self.wins += 1
            self.gross_profit += pnl
        elif pnl < 0:
            self.losses += 1
            self.gross_loss += abs(pnl)


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


def resolve_risk_fraction(
    limits: RiskLimits,
    overlay: RiskOverlay,
    *,
    stats: TradeStats | None = None,
    forecast_vol: Decimal | None = None,
) -> Decimal:
    """Apply optional Kelly cap and vol-scaling on top of base risk_per_trade."""
    fraction = limits.risk_per_trade
    if (
        overlay.use_fractional_kelly
        and stats is not None
        and stats.total_trades >= overlay.kelly_min_trades
    ):
        fraction = effective_risk_fraction(
            limits,
            win_rate=stats.win_rate(),
            reward_risk=stats.reward_risk(),
        )
    if overlay.use_vol_scaling and forecast_vol is not None:
        fraction = vol_scaled_risk_fraction(
            fraction,
            forecast_vol,
            overlay.vol_scaling_target,
        )
    return fraction


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


def evaluate_entry(
    snapshot: AccountSnapshot,
    limits: RiskLimits,
    overlay: RiskOverlay | None = None,
) -> RiskDecision:
    """Circuit breaker before a new entry. Flattening is the caller's job."""
    resolved_overlay = overlay or RiskOverlay()
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
        if resolved_overlay.use_cvar_breaker:
            cvar_99 = historical_cvar(snapshot.recent_returns, confidence=Decimal("0.99"))
            if cvar_99 is not None and cvar_99 >= resolved_overlay.max_cvar_99:
                return RiskDecision(False, "portfolio CVaR 99% circuit breaker")

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
