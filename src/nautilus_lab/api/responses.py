"""Response bodies of the dashboard API (docs/27 E-2.3).

These are the source of `frontend/src/services/api.gen.ts`
(`uv run python scripts/gen_api_types.py`); a test fails when the committed file no
longer matches them, so the dashboard's types cannot drift from what the API sends.

Every model allows extra fields: a route that returns a key the model does not declare
yet keeps sending it (FastAPI would otherwise drop it silently and break a screen). The
declared fields are the contract; the extras are the migration still to do.

Covered so far: status, health, job start/cancel results, ingest log, catalog list,
reports, trained models.
The rest of `frontend/src/services/api.ts` moves here route by route.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        # Every field is in what the API sends, `null` included: required in TypeScript.
        json_schema_serialization_defaults_required=True,
        # A string under a field becomes its JSDoc in api.gen.ts.
        use_attribute_docstrings=True,
    )


JobKey = Literal["research", "ingest", "ml_train", "paper"]


class LastRun(ApiModel):
    """How the previous run of a job ended, kept across API restarts (api/job_store.py)."""

    status: Literal["running", "finished", "lost"]
    returncode: int | None = None
    finished_at: str | None = None


class JobState(ApiModel):
    running: bool
    label: str
    started_at: str | None = None
    elapsed_seconds: float | None = None
    adopted: bool = False
    """Started by an earlier API process and taken back after a restart."""
    last_run: LastRun | None = None


class StressSliceInfo(ApiModel):
    name: str
    description: str
    start: str
    """ISO-8601 UTC window the slice replaces the load window with."""
    end: str


class StatusResponse(ApiModel):
    active_bots: int
    research_running: bool
    ingest_running: bool
    ml_running: bool
    paper_running: bool
    jobs: dict[JobKey, JobState]
    strategies_available: list[str]
    wired_robots: list[str]
    tick_vpin_robots: list[str]
    hawkes_robots: list[str]
    stress_slices: list[StressSliceInfo]
    catalog_exists: bool
    catalog_instruments: int
    catalog_path: str
    bar_interval: str
    trading_mode: str
    paper_robots: list[str]
    """Robots `lab paper` can actually build. Others are refused, never substituted."""
    is_live: bool
    live_safe_mode: str
    lab_role: Literal["full", "paper"]
    """`paper` = a server that only runs the live paper terminal (LAB_ROLE)."""
    live_paper_robots: list[str]
    live_paper_persisted: bool
    """True when the live paper ledger is journalled and survives restarts."""


class HealthResponse(ApiModel):
    status: Literal["ok"]


class ActionResult(ApiModel):
    """What a start/stop/cancel button gets back. `status` names the outcome.

    Every job-launching `POST` answers HTTP 200 with `status: "error"` when another job
    of the same kind is already running. Callers must check this: ignoring it left the UI
    spinning while showing the previous run's numbers as if they were new.

    Sent without the fields a route did not fill (`response_model_exclude_none`), as
    before the model existed, so they are optional here.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=False)

    status: str
    message: str | None = None
    command: str | None = None
    disclaimer: str | None = None


class JobLogResponse(ApiModel):
    is_running: bool
    log: str


class CatalogSummary(ApiModel):
    path: str
    exists: bool
    total_instruments: int
    error: str | None = None


class CatalogsResponse(ApiModel):
    default: str
    catalogs: list[CatalogSummary]


class ReportItem(ApiModel):
    filename: str
    path: str
    url: str
    modified: str
    """Local time of the file, `YYYY-MM-DD HH:MM:SS`."""
    size_kb: float


class ReportsResponse(ApiModel):
    reports: list[ReportItem]


class MlModelInfo(ApiModel):
    filename: str
    path: str
    size_kb: float
    modified: float
    """File modification time, seconds since the epoch."""


class MlModelsResponse(ApiModel):
    models: list[MlModelInfo]


#: Every model the generator writes to TypeScript, in output order.
RESPONSE_MODELS: tuple[type[BaseModel], ...] = (
    LastRun,
    JobState,
    StressSliceInfo,
    StatusResponse,
    HealthResponse,
    ActionResult,
    JobLogResponse,
    CatalogSummary,
    CatalogsResponse,
    ReportItem,
    ReportsResponse,
    MlModelInfo,
    MlModelsResponse,
)
