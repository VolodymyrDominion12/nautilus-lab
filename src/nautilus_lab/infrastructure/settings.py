from __future__ import annotations

from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.regime import RegimeParams, RobotName
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.trading_mode import TradingMode


class Settings(BaseSettings):
    """Process config. Injected at the composition root, never read in domain."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    trading_mode: TradingMode = TradingMode.RESEARCH
    live_enabled: bool = False
    starting_equity: Decimal = Decimal("100000")
    risk_per_trade: Decimal = Decimal("0.005")
    stop_pct: Decimal = Decimal("0.01")
    max_daily_loss: Decimal = Decimal("0.02")
    max_drawdown: Decimal = Decimal("0.06")
    max_open_positions: int = 1
    kelly_fraction: Decimal = Decimal("0.25")
    max_var_99: Decimal = Decimal("0.05")
    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")
    pairs_refit_every: int = 0
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
    formulaic_model_path: str | None = None
    formulaic_threshold: Decimal = Decimal("0.55")
    robot: RobotName = RobotName.REGIME
    fast_ema: int = 10
    slow_ema: int = 20
    er_period: int = 20
    trend_ema_period: int = 40
    slope_lookback: int = 10
    enter_trend_er: Decimal = Decimal("0.30")
    exit_trend_er: Decimal = Decimal("0.20")
    donchian_period: int = 20
    bb_period: int = 20
    bb_k: Decimal = Decimal("2")
    use_bar_vpin: bool = False
    vpin_bucket_volume: Decimal = Decimal("1000")
    vpin_toxic_threshold: Decimal = Decimal("0.7")
    embargo_bars: int = 10
    exchange_api_key: str | None = None
    exchange_api_secret: str | None = None
    instrument_id: str = "ETH/USDT.SIM"
    bar_type: str = "ETH/USDT.SIM-1-MINUTE-LAST-EXTERNAL"
    catalog_path: str = "catalog"
    bar_interval: str = "1h"
    binance_symbol: str = "ETHUSDT"
    binance_symbols: list[str] = Field(default_factory=lambda: ["ETHUSDT", "BTCUSDT"])
    maker_fee: Decimal = Decimal("0.001")
    taker_fee: Decimal = Decimal("0.001")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    alert_webhook_url: str | None = None
    # Offline research loop only (scripts/propose_alphas.py). Never read by a strategy:
    # an LLM call inside the backtest or execution path is a bug, see docs/14.
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 120
    llm_prompts_dir: str = "research/prompts"
    llm_hypotheses_dir: str = "research/hypotheses"

    def risk_limits(self) -> RiskLimits:
        return RiskLimits(
            risk_per_trade=self.risk_per_trade,
            stop_pct=self.stop_pct,
            max_daily_loss=self.max_daily_loss,
            max_drawdown=self.max_drawdown,
            max_open_positions=self.max_open_positions,
            kelly_fraction=self.kelly_fraction,
            max_var_99=self.max_var_99,
        )

    def fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(maker=self.maker_fee, taker=self.taker_fee)

    def regime_params(self) -> RegimeParams:
        return RegimeParams(
            er_period=self.er_period,
            trend_ema_period=self.trend_ema_period,
            slope_lookback=self.slope_lookback,
            enter_trend_er=self.enter_trend_er,
            exit_trend_er=self.exit_trend_er,
            donchian_period=self.donchian_period,
            bb_period=self.bb_period,
            bb_k=self.bb_k,
        )

    def risk_overlay(self) -> RiskOverlay:
        return RiskOverlay(
            use_vol_scaling=self.use_vol_scaling,
            vol_scaling_target=self.vol_scaling_target,
            use_fractional_kelly=self.use_fractional_kelly,
            kelly_min_trades=self.kelly_min_trades,
            use_cvar_breaker=self.use_cvar_breaker,
            max_cvar_99=self.max_cvar_99,
        )

    def pairs_params(self) -> PairsParams:
        return PairsParams(refit_every_bars=self.pairs_refit_every)
