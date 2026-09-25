"""Request bodies of the dashboard API, one model per POST/PUT/PATCH route.

Kept apart from the routers so the frontend types (docs/27 E-2.3) have one place to be
generated from.
"""

from __future__ import annotations

from pydantic import BaseModel


class ResearchRunRequest(BaseModel):
    robot: str = "regime"
    source: str = "catalog"
    bars: int = 3000
    folds: int = 2
    is_fraction: float = 0.7
    embargo_bars: int | None = None
    use_optuna: bool = False
    optuna_trials: int = 20
    pbo: bool = False
    pbo_blocks: int = 8
    bar_vpin: bool = False
    tick_vpin: bool = False
    hawkes: bool = False
    stress_slice: str | None = None
    generate_tearsheet: bool = True
    journal: bool = False
    notify: bool = False
    full_sample: bool = False
    catalog_path: str | None = None
    instrument_id: str | None = None
    bar_interval: str | None = None
    is_start: str | None = None
    is_end: str | None = None
    oos_start: str | None = None
    oos_end: str | None = None
    param_overrides: dict[str, str] = {}


class IngestRunRequest(BaseModel):
    symbols: str = "ETHUSDT,BTCUSDT"
    start: str | None = None
    end: str | None = None
    catalog: str | None = None
    incremental: bool = False
    #: Series to ingest. `klines` is the default (bars for every robot); `trades` pulls
    #: aggregated trades for the tick-level filters; `funding` pulls settlements.
    series: str = "klines"


class SettingsUpdate(BaseModel):
    settings: dict[str, str]


class MLTrainRequest(BaseModel):
    model_type: str = "formulaic"
    catalog_path: str | None = None
    instrument_id: str | None = None
    bar_interval: str | None = None
    output_path: str | None = None
    folds: int = 5
    embargo: int = 10
    horizon: int = 5
    profit_multiple: str = "2"
    stop_multiple: str = "1"
    vol_window: int = 20
    start: str | None = None
    end: str | None = None
    threshold: str = "0.55"


class PaperRunRequest(BaseModel):
    robot: str = "regime"
    bars: int = 2000
    source: str = "catalog"


class PaperLiveStartRequest(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "1m"
    robot: str = "regime"
    starting_equity: str = "10000"
    risk_per_trade: str = "0.01"
    stop_pct: str = "0.015"
    take_profit_multiple: str = "2.0"
    mode: str = "paper"
    auto_trade: bool = True
    name: str = ""
    notes: str = ""


class PaperLiveStopsUpdateRequest(BaseModel):
    stop_loss: str | None = None
    take_profit: str | None = None


class JournalPatchRequest(BaseModel):
    decision: str


class ProposeRequest(BaseModel):
    count: int = 5
    dry_run: bool = True
    prompt: str = "01-generate-alphas.md"
    as_of: str | None = None
    model: str | None = None
    base_url: str | None = None
    output_dir: str | None = None
    slug: str | None = None
    journal: bool = False
