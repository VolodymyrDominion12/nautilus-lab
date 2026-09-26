from __future__ import annotations

from dataclasses import dataclass, field
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


def size_spread(
    *,
    equity: Decimal,
    price_a: Decimal,
    price_b: Decimal,
    stop_distance_a: Decimal,
    risk_fraction: Decimal,
    hedge_ratio: Decimal,
    qty_step_a: Decimal,
    qty_step_b: Decimal,
) -> tuple[Decimal, Decimal]:
    """Quantities for a hedged spread: leg A is risk-sized, leg B = |hedge_ratio| x qty_A.

    Audit B1: the hedge ratio is a *quantity* ratio (spread = A - beta*B), but it used to
    be applied as a risk multiplier, and each leg was then divided by its own stop
    distance. The realised hedge became beta*stop_A/stop_B -- about 1/17 of beta on
    ETH/BTC -- so "pairs" was ~90% a directional ETH position. Each leg stays under 1x
    notional; if leg B would breach it both legs shrink together, keeping the ratio.
    """
    hedge = abs(hedge_ratio)
    if hedge <= 0:
        raise InvalidRiskError("hedge_ratio must be non-zero")
    if price_b <= 0:
        raise InvalidRiskError("price must be > 0")
    if qty_step_b <= 0:
        raise InvalidRiskError("qty_step must be > 0")
    qty_a = size_position(
        equity=equity,
        price=price_a,
        stop_distance=stop_distance_a,
        risk_fraction=risk_fraction,
        qty_step=qty_step_a,
    )
    notional_b = qty_a * hedge * price_b
    if notional_b > equity:
        scaled = qty_a * equity / notional_b
        qty_a = (scaled / qty_step_a).to_integral_value(rounding=ROUND_DOWN) * qty_step_a
    qty_b = (qty_a * hedge / qty_step_b).to_integral_value(rounding=ROUND_DOWN) * qty_step_b
    if qty_a <= 0 or qty_b <= 0:
        return Decimal("0"), Decimal("0")
    return qty_a, qty_b


@dataclass
class RiskBreachTally:
    """How often each circuit breaker refused an entry, in first-trip order.

    Before this existed, a blocked entry was a `log.warning` and nothing else: a
    finished run could show `max_dd` sitting exactly on `MAX_DRAWDOWN` and still
    give no way to tell *which* breaker had fired, or whether it fired once or
    three hundred times. `RiskDecision.reason` already carries the answer, so this
    only stops throwing it away.

    First-trip order is kept (not alphabetical) so the report reads as the story of
    the run, and so "which breaker fired first" is answerable.
    """

    counts: dict[str, int] = field(default_factory=dict)

    def record(self, reason: str) -> int:
        """Count one refusal and return its new total."""
        self.counts[reason] = self.counts.get(reason, 0) + 1
        return self.counts[reason]

    def summary(self) -> tuple[tuple[str, int], ...]:
        return tuple(self.counts.items())

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def tripped(self) -> bool:
        return bool(self.counts)


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
        return RiskDecision(False, "non-positive equity", "equity", snapshot.equity, Decimal("0"))
    if snapshot.day_start_equity <= 0:
        return RiskDecision(
            False, "non-positive day-start equity", "day_start_equity", snapshot.day_start_equity
        )
    if snapshot.peak_equity <= 0:
        return RiskDecision(False, "non-positive peak equity", "peak_equity", snapshot.peak_equity)

    daily_loss = (snapshot.day_start_equity - snapshot.equity) / snapshot.day_start_equity
    if daily_loss >= limits.max_daily_loss:
        return RiskDecision(
            False, "daily loss circuit breaker", "max_daily_loss", daily_loss, limits.max_daily_loss
        )

    drawdown = (snapshot.peak_equity - snapshot.equity) / snapshot.peak_equity
    if drawdown >= limits.max_drawdown:
        return RiskDecision(
            False, "max drawdown circuit breaker", "max_drawdown", drawdown, limits.max_drawdown
        )

    if snapshot.open_positions > limits.max_open_positions:
        return RiskDecision(
            False,
            "max open positions exceeded",
            "max_open_positions",
            Decimal(snapshot.open_positions),
            Decimal(limits.max_open_positions),
        )

    if snapshot.recent_returns:
        var_99 = historical_var(snapshot.recent_returns, confidence=Decimal("0.99"))
        if var_99 is not None and var_99 >= limits.max_var_99:
            return RiskDecision(
                False, "portfolio VaR 99% circuit breaker", "max_var_99", var_99, limits.max_var_99
            )
        if resolved_overlay.use_cvar_breaker:
            cvar_99 = historical_cvar(snapshot.recent_returns, confidence=Decimal("0.99"))
            if cvar_99 is not None and cvar_99 >= resolved_overlay.max_cvar_99:
                return RiskDecision(
                    False,
                    "portfolio CVaR 99% circuit breaker",
                    "max_cvar_99",
                    cvar_99,
                    resolved_overlay.max_cvar_99,
                )

    return RiskDecision(True, "ok", "ok")


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
