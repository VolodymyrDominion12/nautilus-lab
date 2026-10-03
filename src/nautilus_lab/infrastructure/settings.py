from __future__ import annotations

from decimal import Decimal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from nautilus_lab.domain.adaptive_ema import AdaptiveEmaParams
from nautilus_lab.domain.entry_filters import EntryFilterParams
from nautilus_lab.domain.fees import FeeSchedule
from nautilus_lab.domain.funding import FundingParams
from nautilus_lab.domain.metrics import SelectionMetric
from nautilus_lab.domain.pairs.params import PairsParams
from nautilus_lab.domain.regime import RegimeParams, RobotName
from nautilus_lab.domain.regime_router import parse_legs
from nautilus_lab.domain.risk import RiskLimits
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.domain.volatility import VolModel


class Settings(BaseSettings):
    """Process config. Injected at the composition root, never read in domain."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    trading_mode: TradingMode = TradingMode.RESEARCH
    # Dashboard API gate (api/security.py). Empty token = origin check only.
    api_token: str = ""
    # Empty = the defaults in api/security.py (Vite dev/preview and the API's own port).
    api_allowed_origins: str = ""
    # What this API process is allowed to do. "full" = the research workstation;
    # "paper" = a server that only runs the live paper terminal: research, ingest, ML,
    # alpha proposals and PUT /api/settings are refused (api/security.py).
    lab_role: str = "full"
    # Live paper terminal persistence (infrastructure/live_paper_journal.py). Empty =
    # in-memory only, as before. When set, every fill and closed bar is appended there
    # and an unfinished session is resumed when the API starts.
    live_paper_journal: str = ""
    # Start a live paper session on API start when there is nothing to resume. The
    # robot's parameters, fees, risk and breakers come from the settings above, like
    # every research run; these only pick what to trade.
    live_paper_autostart: bool = False
    live_paper_symbol: str = "ETHUSDT"
    live_paper_interval: str = "1h"
    live_paper_robot: str = "regime"
    live_paper_starting_equity: Decimal = Decimal("10000")
    live_paper_take_profit_multiple: Decimal = Decimal("2")
    # Several sessions: one journal per session in this folder. Empty = next to
    # LIVE_PAPER_JOURNAL as `sessions/` (or in-memory only when that is empty too).
    live_paper_sessions_dir: str = ""
    # YAML list of the sessions this server should run (deploy/paper_portfolio.yaml).
    # When set it replaces LIVE_PAPER_AUTOSTART; empty = autostart as before.
    live_paper_portfolio: str = ""
    live_paper_max_sessions: int = 8
    # Distinct symbol+interval sockets to Binance at once (sessions share them).
    live_paper_max_feeds: int = 5
    # Liveness of the paper server (api/health.py, docs/27 E-1.5/E-1.6). A feed that
    # sends nothing for FEED_TIMEOUT, or no closed bar for interval + CLOSED_BAR_SLACK,
    # makes /readyz 503 and the watchdog alert (Telegram/webhook settings below).
    live_paper_feed_timeout_seconds: float = 90.0
    live_paper_closed_bar_slack_seconds: float = 180.0
    live_paper_feed_grace_seconds: float = 120.0
    # How often the watchdog re-checks; 0 turns it off (e.g. on a workstation).
    live_paper_watchdog_seconds: float = 30.0
    # Dead-man's switch (docs/27 E-1.7): the watchdog GETs this URL at most every
    # HEARTBEAT_SECONDS while the server is ready (healthchecks.io / Uptime Kuma push).
    # The outside service alarms when the pings stop. FAIL_URL (optional) is pinged
    # instead while not ready. Needs the watchdog on. Masked in the settings API (_URL).
    live_paper_heartbeat_url: str = ""
    live_paper_heartbeat_fail_url: str = ""
    live_paper_heartbeat_seconds: float = 300.0
    live_enabled: bool = False
    starting_equity: Decimal = Decimal("100000")
    risk_per_trade: Decimal = Decimal("0.005")
    stop_pct: Decimal = Decimal("0.03")
    atr_stop_multiplier: Decimal = Decimal("2")
    max_daily_loss: Decimal = Decimal("0.04")
    max_drawdown: Decimal = Decimal("0.12")
    max_open_positions: int = 1
    kelly_fraction: Decimal = Decimal("0.25")
    max_var_99: Decimal = Decimal("0.05")
    use_vol_scaling: bool = False
    vol_scaling_target: Decimal = Decimal("0.02")
    vol_model: VolModel = VolModel.HAR
    vol_refit_every: int = 24
    use_fractional_kelly: bool = False
    kelly_min_trades: int = 30
    use_cvar_breaker: bool = False
    max_cvar_99: Decimal = Decimal("0.05")
    use_ratchet: bool = False
    ratchet_arm_pct: Decimal = Decimal("0.0125")
    use_protective_stop: bool = True
    selection_metric: SelectionMetric = SelectionMetric.PNL
    drawdown_cooldown_days: int = 0
    research_drawdown_cooldown_days: int = 7
    pairs_refit_every: int = 48
    # The two legs of `pairs` (A is traded in the spread's direction, B hedges it).
    pairs_leg_a: str = "ETH/USDT.SIM"
    pairs_leg_b: str = "BTC/USDT.SIM"
    # 0 disables the quantile gate and leaves the fixed `PairsParams.z_entry` in
    # charge, which is how every documented `pairs` run was measured. A plain
    # Decimal with a sentinel is used instead of `Decimal | None` so that an unset
    # or empty env var cannot fail pydantic validation on the way in.
    pairs_z_entry_quantile: Decimal = Decimal("0")
    vpin_momentum_ema_period: int = 50
    vpin_momentum_atr_multiple: Decimal = Decimal("2")
    formulaic_model_path: str | None = None
    formulaic_threshold: Decimal = Decimal("0.55")
    meta_label_model_path: str | None = None
    meta_label_threshold: Decimal = Decimal("0.55")
    ml_obi_model_path: str | None = None
    ml_obi_threshold: Decimal = Decimal("0.55")
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
    regime_confirmation_bars: int = 1
    # regime's range leg: false = the upper Bollinger band takes profit, never shorts.
    regime_range_allow_short: bool = True
    # regime: bars a position is held before the router may exit/flip it (0 = off).
    regime_min_hold_bars: int = 0
    # Entry gates on new exposure (domain/entry_filters.py). Off by default: they come
    # from one batch's OOS trades and must be tested as a pre-registered hypothesis.
    entry_filter_htf_trend: bool = False
    entry_filter_htf_ema_period: int = 200
    entry_filter_htf_slope_lookback: int = 24
    entry_filter_vol_expansion: bool = False
    entry_filter_vol_fast_period: int = 24
    entry_filter_vol_slow_period: int = 300
    entry_filter_min_vol_ratio: Decimal = Decimal("1")
    # An opposite signal only closes the position; the reverse entry is not sent.
    no_instant_reverse: bool = False
    # Backtest venue latency (ms). 0 = fill at the decision bar's close; >0 = the old
    # one-bar-late fill at the next close (see BacktestRequest.fill_latency_ms).
    backtest_fill_latency_ms: int = 0
    # adaptive_ema: the filter regime leg gets a step that depends on the efficiency
    # ratio (selectivity). 0 reproduces the fixed-alpha EMA exactly - the null
    # hypothesis lives inside the grid, see specs/strategies/adaptive_ema.yaml.
    adaptive_period: int = 40
    adaptive_er_period: int = 20
    adaptive_selectivity: Decimal = Decimal("0.5")
    adaptive_slope_lookback: int = 10
    adaptive_range_allow_short: bool = False
    adaptive_range_exit_at_mean: bool = False
    adaptive_min_bb_width_pct: Decimal = Decimal("0")
    adaptive_hold_trend_in_range: bool = True
    use_bar_vpin: bool = False
    use_tick_vpin: bool = False
    use_hawkes: bool = False
    hawkes_baseline: Decimal = Decimal("0.1")
    hawkes_alpha: Decimal = Decimal("0.5")
    hawkes_beta: Decimal = Decimal("1.0")
    hawkes_toxic_threshold: Decimal = Decimal("2.0")
    vpin_bucket_volume: Decimal = Decimal("1000")
    vpin_toxic_threshold: Decimal = Decimal("0.7")
    # IS-гіпотеза «перцентильний поріг»: замість фіксованого 0.7 — rolling-квантиль.
    # Вмикається лише для robot=vpin_momentum при USE_QUANTILE_VPIN=true.
    use_quantile_vpin: bool = False
    vpin_quantile: Decimal = Decimal("0.90")
    # REGIME_LEGS: enabled legs of regime / adaptive_ema, e.g. "uptrend,range" (docs/31).
    regime_legs: str = ""
    embargo_bars: int = 10
    exchange_api_key: str | None = None
    exchange_api_secret: str | None = None
    instrument_id: str = "ETH/USDT.SIM"
    bar_type: str = "ETH/USDT.SIM-1-MINUTE-LAST-EXTERNAL"
    catalog_path: str = "catalog"
    catalog_paths: str = ""
    bar_interval: str = "1h"
    binance_symbol: str = "ETHUSDT"
    binance_symbols: list[str] = Field(default_factory=lambda: ["ETHUSDT", "BTCUSDT"])
    spot_maker_fee: Decimal = Decimal("0.00075")
    spot_taker_fee: Decimal = Decimal("0.00075")
    usdm_maker_fee: Decimal = Decimal("0.0002")
    usdm_taker_fee: Decimal = Decimal("0.0005")
    funding_min_net_apy: Decimal = Decimal("0.10")
    funding_holding_periods: int = 60
    funding_basis_max: Decimal = Decimal("0.005")
    funding_close_on_negative: bool = False
    funding_min_exit_apy: Decimal | None = None
    funding_min_holding_periods: int = 15
    funding_max_holding_periods: int | None = None
    funding_spot_id: str = "ETH/USDT.SIM"
    funding_perp_id: str = "ETHUSDT-PERP.SIM"
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
    # Append-only research journal (application/journal.py). Off by default: writing to a
    # tracked file on every run is a decision, not a side effect. `--journal` forces it.
    journal_enabled: bool = False
    journal_path: str = "research/journal.md"
    journal_jsonl_path: str = "research/journal.jsonl"
    # Every configuration ever tried per dataset; DSR is deflated by that total (docs/27
    # R-3). Always written for catalog searches: it is evidence, like the journal, and a
    # switch to turn it off would be a switch to launder a search.
    trials_ledger_path: str = "research/trials.jsonl"
    # Registered test terms, one JSON file each (docs/27 R-2): `lab research --register`.
    preregistrations_dir: str = "research/preregistrations"

    # Decision Log for Live Paper API (infrastructure/decision_log_writer.py)
    decision_log_enabled: bool = False
    decision_log_dir: str = "data/paper/decisions"
    decision_log_retention_days: int = 7
    # Which walk-forward runs write decisions: "all" (every grid candidate on in-sample
    # too — ~100k records per regime run) or "oos" (only the selected configuration's
    # out-of-sample run of each fold, one session `<id>-f<fold>` per fold). Batch
    # backtests use "oos": the in-sample grid is search, not the result being explained.
    decision_log_scope: str = "all"

    @field_validator("regime_legs")
    @classmethod
    def _known_regime_legs(cls, value: str) -> str:
        parse_legs(value)  # fail at startup, not in the middle of a batch cell
        return value

    def all_catalog_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for raw in [self.catalog_path, *self.catalog_paths.split(",")]:
            item = raw.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            paths.append(item)
        return paths

    def risk_limits(self) -> RiskLimits:
        return RiskLimits(
            risk_per_trade=self.risk_per_trade,
            stop_pct=self.stop_pct,
            max_daily_loss=self.max_daily_loss,
            max_drawdown=self.max_drawdown,
            max_open_positions=self.max_open_positions,
            kelly_fraction=self.kelly_fraction,
            max_var_99=self.max_var_99,
            atr_stop_multiplier=self.atr_stop_multiplier,
        )

    def spot_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(maker=self.spot_maker_fee, taker=self.spot_taker_fee)

    def usdm_fee_schedule(self) -> FeeSchedule:
        return FeeSchedule(maker=self.usdm_maker_fee, taker=self.usdm_taker_fee)

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
            confirmation_bars=self.regime_confirmation_bars,
            range_allow_short=self.regime_range_allow_short,
            min_hold_bars=self.regime_min_hold_bars,
        )

    def entry_filter_params(self) -> EntryFilterParams:
        return EntryFilterParams(
            htf_trend=self.entry_filter_htf_trend,
            htf_ema_period=self.entry_filter_htf_ema_period,
            htf_slope_lookback=self.entry_filter_htf_slope_lookback,
            vol_expansion=self.entry_filter_vol_expansion,
            vol_fast_period=self.entry_filter_vol_fast_period,
            vol_slow_period=self.entry_filter_vol_slow_period,
            min_vol_ratio=self.entry_filter_min_vol_ratio,
            no_instant_reverse=self.no_instant_reverse,
        )

    def adaptive_ema_params(self) -> AdaptiveEmaParams:
        """Filter parameters for `adaptive_ema`. The ER hysteresis gates are shared
        with `regime`, so the adaptive step is the only difference between them."""
        return AdaptiveEmaParams(
            base_period=self.adaptive_period,
            er_period=self.adaptive_er_period,
            selectivity=self.adaptive_selectivity,
            slope_lookback=self.adaptive_slope_lookback,
            enter_trend_er=self.enter_trend_er,
            exit_trend_er=self.exit_trend_er,
            donchian_period=self.donchian_period,
            bb_period=self.bb_period,
            bb_k=self.bb_k,
            range_allow_short=self.adaptive_range_allow_short,
            range_exit_at_mean=self.adaptive_range_exit_at_mean,
            min_bb_width_pct=self.adaptive_min_bb_width_pct,
            hold_trend_in_range=self.adaptive_hold_trend_in_range,
        )

    def risk_overlay(self) -> RiskOverlay:
        cooldown = (
            self.research_drawdown_cooldown_days
            if self.trading_mode is TradingMode.RESEARCH
            else self.drawdown_cooldown_days
        )
        return RiskOverlay(
            use_vol_scaling=self.use_vol_scaling,
            vol_scaling_target=self.vol_scaling_target,
            vol_model=self.vol_model,
            vol_refit_every=self.vol_refit_every,
            use_fractional_kelly=self.use_fractional_kelly,
            kelly_min_trades=self.kelly_min_trades,
            use_cvar_breaker=self.use_cvar_breaker,
            max_cvar_99=self.max_cvar_99,
            use_ratchet=self.use_ratchet,
            ratchet_arm_pct=self.ratchet_arm_pct,
            use_protective_stop=self.use_protective_stop,
            drawdown_cooldown_days=cooldown,
        )

    def pairs_params(self) -> PairsParams:
        quantile = self.pairs_z_entry_quantile
        return PairsParams(
            leg_a=self.pairs_leg_a,
            leg_b=self.pairs_leg_b,
            refit_every_bars=self.pairs_refit_every,
            z_entry_quantile=quantile if quantile > 0 else None,
        )

    def funding_params(self) -> FundingParams:
        return FundingParams(
            min_net_apy=self.funding_min_net_apy,
            holding_periods=self.funding_holding_periods,
            basis_max=self.funding_basis_max,
            close_on_negative=self.funding_close_on_negative,
            taker_fee=self.spot_taker_fee + self.usdm_taker_fee,
            min_exit_apy=self.funding_min_exit_apy,
            min_holding_periods=self.funding_min_holding_periods,
            max_holding_periods=self.funding_max_holding_periods,
        )
