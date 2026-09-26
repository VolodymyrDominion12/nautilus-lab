from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from nautilus_lab.infrastructure.settings import Settings

FieldType = Literal["string", "number", "boolean", "select", "secret"]

# Keys the API is allowed to write via PUT /api/settings.
ALLOWED_SETTING_KEYS: frozenset[str] = frozenset(Settings.model_fields.keys())


class SettingField(BaseModel):
    key: str
    label: str
    field_type: FieldType
    description: str = ""
    options: list[str] | None = None


class SettingGroup(BaseModel):
    id: str
    title: str
    description: str
    fields: list[SettingField]


SETTING_GROUPS: tuple[SettingGroup, ...] = (
    SettingGroup(
        id="mode",
        title="Trading Mode",
        description="Research is the default. Live execution is fail-closed in this lab.",
        fields=[
            SettingField(
                key="TRADING_MODE",
                label="Trading mode",
                field_type="select",
                options=["research", "paper", "live"],
                description="Only research and paper are supported; live always fails closed.",
            ),
            SettingField(
                key="LIVE_ENABLED",
                label="Live enabled flag",
                field_type="boolean",
                description="Does not enable live trading in this project.",
            ),
        ],
    ),
    SettingGroup(
        id="risk",
        title="Risk Limits",
        description="Fractions of equity used by application/risk.py during backtests.",
        fields=[
            SettingField(key="STARTING_EQUITY", label="Starting equity", field_type="number"),
            SettingField(key="RISK_PER_TRADE", label="Risk per trade", field_type="number"),
            SettingField(key="STOP_PCT", label="Stop loss %", field_type="number"),
            SettingField(key="MAX_DAILY_LOSS", label="Max daily loss", field_type="number"),
            SettingField(key="MAX_DRAWDOWN", label="Max drawdown", field_type="number"),
            SettingField(key="MAX_OPEN_POSITIONS", label="Max open positions", field_type="number"),
            SettingField(key="KELLY_FRACTION", label="Kelly fraction", field_type="number"),
            SettingField(key="MAX_VAR_99", label="Max VaR 99", field_type="number"),
        ],
    ),
    SettingGroup(
        id="robot",
        title="Robot Defaults",
        description="Default strategy and hyperparameters loaded before each run.",
        fields=[
            SettingField(
                key="ROBOT",
                label="Default robot",
                field_type="select",
                options=[
                    "regime",
                    "ema",
                    "pairs",
                    "vpin_momentum",
                    "formulaic_lgbm",
                    "meta_label",
                    "adaptive_ema",
                    "ml_obi",
                    "funding",
                ],
            ),
            SettingField(key="FAST_EMA", label="Fast EMA", field_type="number"),
            SettingField(key="SLOW_EMA", label="Slow EMA", field_type="number"),
            SettingField(key="ER_PERIOD", label="ER period", field_type="number"),
            SettingField(key="TREND_EMA_PERIOD", label="Trend EMA period", field_type="number"),
            SettingField(key="SLOPE_LOOKBACK", label="Slope lookback", field_type="number"),
            SettingField(key="ENTER_TREND_ER", label="Enter trend ER", field_type="number"),
            SettingField(key="EXIT_TREND_ER", label="Exit trend ER", field_type="number"),
            SettingField(key="DONCHIAN_PERIOD", label="Donchian period", field_type="number"),
            SettingField(key="BB_PERIOD", label="Bollinger period", field_type="number"),
            SettingField(key="BB_K", label="Bollinger k", field_type="number"),
            SettingField(key="USE_BAR_VPIN", label="Bar VPIN filter", field_type="boolean"),
            SettingField(key="VPIN_BUCKET_VOLUME", label="VPIN bucket volume", field_type="number"),
            SettingField(
                key="VPIN_TOXIC_THRESHOLD", label="VPIN toxic threshold", field_type="number"
            ),
            SettingField(
                key="FORMULAIC_MODEL_PATH",
                label="Formulaic model path",
                field_type="string",
            ),
            SettingField(
                key="FORMULAIC_THRESHOLD", label="Formulaic threshold", field_type="number"
            ),
            SettingField(
                key="META_LABEL_MODEL_PATH",
                label="Meta-label model path",
                field_type="string",
            ),
            SettingField(
                key="META_LABEL_THRESHOLD", label="Meta-label threshold", field_type="number"
            ),
        ],
    ),
    SettingGroup(
        id="catalog",
        title="Data Catalog",
        description="Parquet catalog location and Binance ingest defaults.",
        fields=[
            SettingField(key="CATALOG_PATH", label="Catalog path", field_type="string"),
            SettingField(
                key="CATALOG_PATHS",
                label="Extra catalog paths",
                field_type="string",
                description="Comma-separated list of additional Parquet catalog directories.",
            ),
            SettingField(
                key="BAR_INTERVAL",
                label="Bar interval",
                field_type="select",
                options=["1m", "5m", "15m", "1h", "4h", "1d"],
            ),
            SettingField(key="BINANCE_SYMBOL", label="Default symbol", field_type="string"),
            SettingField(
                key="BINANCE_SYMBOLS", label="Ingest symbols (JSON list)", field_type="string"
            ),
            SettingField(key="EMBARGO_BARS", label="Embargo bars", field_type="number"),
            SettingField(key="MAKER_FEE", label="Maker fee", field_type="number"),
            SettingField(key="TAKER_FEE", label="Taker fee", field_type="number"),
        ],
    ),
    SettingGroup(
        id="overlays",
        title="Risk Overlays",
        description="Optional overlays applied inside SignalRobot during backtests.",
        fields=[
            SettingField(key="USE_VOL_SCALING", label="Vol scaling", field_type="boolean"),
            SettingField(key="VOL_SCALING_TARGET", label="Vol scaling target", field_type="number"),
            SettingField(
                key="USE_FRACTIONAL_KELLY", label="Fractional Kelly", field_type="boolean"
            ),
            SettingField(key="KELLY_MIN_TRADES", label="Kelly min trades", field_type="number"),
            SettingField(key="USE_CVAR_BREAKER", label="CVaR breaker", field_type="boolean"),
            SettingField(key="MAX_CVAR_99", label="Max CVaR 99", field_type="number"),
            SettingField(key="USE_RATCHET", label="Profit ratchet", field_type="boolean"),
            SettingField(key="RATCHET_ARM_PCT", label="Ratchet arm %", field_type="number"),
            SettingField(
                key="USE_PROTECTIVE_STOP", label="Protective stop order", field_type="boolean"
            ),
            SettingField(
                key="SELECTION_METRIC",
                label="In-sample selection metric",
                field_type="select",
                options=["pnl", "sharpe", "calmar"],
                description="What the parameter search maximises; pnl favours the riskiest.",
            ),
            SettingField(
                key="DRAWDOWN_COOLDOWN_DAYS",
                label="Drawdown breaker cool-down (days)",
                field_type="number",
                description="0 = a tripped drawdown breaker blocks entries for the whole run.",
            ),
            SettingField(
                key="PAIRS_REFIT_EVERY", label="Pairs refit every N bars", field_type="number"
            ),
        ],
    ),
    SettingGroup(
        id="alerts",
        title="Alerts",
        description="Optional Telegram or webhook notifications after CLI/API runs.",
        fields=[
            SettingField(key="TELEGRAM_BOT_TOKEN", label="Telegram bot token", field_type="secret"),
            SettingField(key="TELEGRAM_CHAT_ID", label="Telegram chat id", field_type="string"),
            SettingField(key="ALERT_WEBHOOK_URL", label="Alert webhook URL", field_type="secret"),
        ],
    ),
    SettingGroup(
        id="journal",
        title="Research Journal",
        description="Append-only experiment log paths.",
        fields=[
            SettingField(key="JOURNAL_ENABLED", label="Journal enabled", field_type="boolean"),
            SettingField(key="JOURNAL_PATH", label="Journal markdown path", field_type="string"),
            SettingField(key="JOURNAL_JSONL_PATH", label="Journal JSONL path", field_type="string"),
            SettingField(
                key="TRIALS_LEDGER_PATH",
                label="Trial ledger path (DSR counts every configuration tried)",
                field_type="string",
            ),
        ],
    ),
    SettingGroup(
        id="llm",
        title="Alpha Ideas / LLM",
        description="Offline hypothesis generation (lab propose). Never used in backtests.",
        fields=[
            SettingField(key="LLM_API_KEY", label="LLM API key", field_type="secret"),
            SettingField(key="LLM_BASE_URL", label="LLM base URL", field_type="string"),
            SettingField(key="LLM_MODEL", label="LLM model", field_type="string"),
            SettingField(key="LLM_TEMPERATURE", label="LLM temperature", field_type="number"),
            SettingField(
                key="LLM_TIMEOUT_SECONDS", label="LLM timeout (seconds)", field_type="number"
            ),
            SettingField(key="LLM_PROMPTS_DIR", label="Prompts directory", field_type="string"),
            SettingField(
                key="LLM_HYPOTHESES_DIR", label="Hypotheses directory", field_type="string"
            ),
        ],
    ),
    SettingGroup(
        id="funding",
        title="Funding Cash-and-Carry",
        description="Parameters for the delta-neutral funding rate cash-and-carry strategy.",
        fields=[
            SettingField(
                key="FUNDING_MIN_NET_APY",
                label="Min Net APY",
                field_type="number",
                description="Minimum net annual funding yield threshold after fee amortization.",
            ),
            SettingField(
                key="FUNDING_HOLDING_PERIODS",
                label="Holding periods (8h intervals)",
                field_type="number",
                description="Number of 8h intervals over which round-trip fee is amortized.",
            ),
            SettingField(
                key="FUNDING_BASIS_MAX",
                label="Max basis divergence",
                field_type="number",
                description="Maximum allowable abs(mark - index)/index basis spread.",
            ),
            SettingField(
                key="FUNDING_CLOSE_ON_NEGATIVE",
                label="Close on negative funding",
                field_type="boolean",
                description="Whether to exit position if next funding payment turns negative.",
            ),
            SettingField(
                key="FUNDING_SPOT_ID",
                label="Funding spot instrument ID",
                field_type="string",
            ),
            SettingField(
                key="FUNDING_PERP_ID",
                label="Funding perp instrument ID",
                field_type="string",
            ),
        ],
    ),
)


def settings_schema_payload() -> dict[str, Any]:
    return {
        "groups": [group.model_dump() for group in SETTING_GROUPS],
        "allowed_keys": sorted(ALLOWED_SETTING_KEYS),
    }


def normalize_env_key(key: str) -> str:
    return key.upper()


def validate_settings_update(raw: dict[str, str]) -> dict[str, str]:
    """Reject unknown keys and normalize to uppercase .env names."""
    normalized: dict[str, str] = {}
    allowed_upper = {name.upper() for name in Settings.model_fields}
    for key, value in raw.items():
        upper = normalize_env_key(key)
        if upper not in allowed_upper:
            msg = f"Unknown setting key: {key}"
            raise ValueError(msg)
        normalized[upper] = str(value)
    return normalized


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}****{value[-2:]}"
