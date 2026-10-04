"""A batch backtest: a matrix of robots x instruments, each cell one walk-forward.

This is the planning half, with no I/O: which cells a request expands to, what each cell
needs (catalog, interval, model paths, the funding perp), and which cells cannot run and
why — said **before** the batch starts, instead of discovering it as a failed cell an
hour later (the 2026-09-29 sweep: `ml_obi` had no model, `glft` has no adapter).

The running half lives in `api/run_batch_job.py`; the result rows in `api/batch_store.py`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from nautilus_lab.domain.regime import RobotName

#: Robots the batch form offers by default: every one with a backtest adapter.
DEFAULT_ROBOTS: tuple[str, ...] = (
    "regime",
    "ema",
    "adaptive_ema",
    "vpin_momentum",
    "formulaic_lgbm",
    "meta_label",
    "pairs",
    "funding",
)
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")

#: Robots whose booster must exist (`models/clean/<kind>_<BASE>_preoos.txt` by default).
_MODEL_ENV: dict[str, tuple[str, str]] = {
    "formulaic_lgbm": ("FORMULAIC_MODEL_PATH", "formulaic"),
    "meta_label": ("META_LABEL_MODEL_PATH", "meta_label"),
    "ml_obi": ("ML_OBI_MODEL_PATH", "ml_obi"),
}

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}USDT$")
_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
#: A variant name becomes part of the cell id (`regime_BTC__H1`) and of `#/run/...` links.
_VARIANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
#: A settings name as `Settings` spells it (`DRAWDOWN_COOLDOWN_DAYS`), never lowercase.
_SETTINGS_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
#: Each variant multiplies robots x symbols, and one cell is minutes to hours of engine time.
MAX_VARIANTS = 8


@dataclass(frozen=True, slots=True)
class BatchVariant:
    """One named set of env overrides: a hypothesis to compare against the others.

    Why this exists (docs/32 §4, docs/35 §8): `env` used to apply to every cell of a batch,
    so comparing four entry-gate hypotheses meant running four batches of several hours and
    comparing them by eye. A variant makes the hypothesis a *dimension of the matrix*:
    every cell is run once per variant, side by side, in one artefact.

    `name` is part of the cell id (`regime_BTC__H1`), so it must be short and safe; it is
    also what the batch table groups and labels by.
    """

    name: str
    env: dict[str, str] = field(default_factory=dict)
    #: Cost scenario for this variant only; None = the batch's own (see `cost_overrides`).
    cost_profile: str | None = None

    def __post_init__(self) -> None:
        if not _VARIANT_RE.match(self.name):
            raise ValueError(
                f"variant name {self.name!r} must match {_VARIANT_RE.pattern} "
                "(it becomes part of the cell id)"
            )
        if not self.env and not self.cost_profile:
            raise ValueError(f"variant {self.name!r} overrides nothing")
        for key in self.env:
            if not _SETTINGS_NAME_RE.match(key):
                raise ValueError(
                    f"variant {self.name!r}: env override {key!r} is not a SETTINGS_NAME"
                )


@dataclass(frozen=True, slots=True)
class BatchRequest:
    """What the dashboard's batch form submits."""

    robots: tuple[str, ...] = DEFAULT_ROBOTS
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    interval: str = "1h"
    catalog: str = "catalog"
    #: `funding` needs perpetual bars, which the main 1h catalog does not hold.
    funding_catalog: str = "catalog_2019_4h"
    funding_interval: str = "4h"
    folds: int = 4
    is_fraction: Decimal = Decimal("0.7")
    parallel: int = 2
    label: str = ""
    days: int | None = None
    embargo_bars: int | None = None
    #: Extra settings for every cell (e.g. `DRAWDOWN_COOLDOWN_DAYS=3`), as env overrides.
    env: dict[str, str] = field(default_factory=dict)
    #: Cost scenario for the whole batch (`domain/fees.py::COST_PROFILES`). A variant may
    #: override it, which is how "the same hypothesis at base and stressed costs" becomes
    #: one batch instead of two (docs/33 §4).
    cost_profile: str | None = None
    #: Named override sets; empty = the plain robots x symbols matrix (the old behaviour).
    variants: tuple[BatchVariant, ...] = ()
    models_dir: str = "models/clean"

    def __post_init__(self) -> None:
        if not self.robots:
            raise ValueError("a batch needs at least one robot")
        if not self.symbols:
            raise ValueError("a batch needs at least one symbol")
        for symbol in self.symbols:
            if not _SYMBOL_RE.match(symbol):
                raise ValueError(f"symbol {symbol!r} is not a <BASE>USDT spot symbol")
        for robot in self.robots:
            RobotName(robot)  # raises on an unknown robot
        if self.folds < 2:
            raise ValueError("a batch runs a multi-window walk-forward: folds >= 2")
        if not (Decimal("0.1") <= self.is_fraction <= Decimal("0.9")):
            raise ValueError("is_fraction must be in [0.1, 0.9]")
        if self.embargo_bars is not None and self.embargo_bars < 0:
            raise ValueError("embargo_bars must be >= 0")
        if not (1 <= self.parallel <= 8):
            raise ValueError("parallel must be in [1, 8]")
        if self.days is not None and self.days <= 0:
            raise ValueError("days must be > 0")
        for key in self.env:
            if not _SETTINGS_NAME_RE.match(key):
                raise ValueError(f"env override {key!r} is not a SETTINGS_NAME")
        if len(self.variants) > MAX_VARIANTS:
            raise ValueError(
                f"{len(self.variants)} variants is too many: each one multiplies the whole "
                f"matrix (robots x symbols), and the cap is {MAX_VARIANTS}"
            )
        names = [variant.name for variant in self.variants]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"variant names must be unique; repeated: {', '.join(duplicates)}")


@dataclass(frozen=True, slots=True)
class BatchCell:
    """One walk-forward of the matrix: a robot on an instrument (pairs: on both)."""

    cell_id: str
    robot: str
    symbol: str
    instrument_id: str
    catalog: str
    interval: str
    env: dict[str, str]
    #: Why this cell cannot run; None = runnable. Shown in the plan and kept in the table.
    blocked: str | None = None
    #: Cost scenario this cell will pay (`domain/fees.py`), None = whatever the machine's
    #: settings say. Kept beside `env` so the table can name it without decoding env.
    cost_profile: str | None = None

    @property
    def runnable(self) -> bool:
        return self.blocked is None


def base_asset(symbol: str) -> str:
    return symbol.removesuffix("USDT")


def spot_instrument(symbol: str) -> str:
    return f"{base_asset(symbol)}/USDT.SIM"


def perp_instrument(symbol: str) -> str:
    return f"{symbol}-PERP.SIM"


def safe_id(raw: str) -> str:
    return _ID_RE.sub("_", raw).strip("_") or "batch"


def plan_cells(
    request: BatchRequest,
    *,
    exists: Callable[[str], bool],
    series: Callable[[str, str, str], bool] | None = None,
    wired: Sequence[str] | None = None,
) -> list[BatchCell]:
    """Expand the request into cells, marking the ones that cannot run and why.

    `exists` answers "is there a file at this repo-relative path" (models, catalogs), so
    this function stays pure and testable. `wired` is the set of robots with a backtest
    adapter (`domain/regime.py::require_backtest_support`); None = do not check.

    `series(catalog, instrument_id, interval)` answers "is that bar series on disk".
    Without it the plan only knew that a catalog *directory* exists, so a cell whose
    instrument was never ingested was planned as runnable and died an hour later (see
    `_missing_series`); None keeps the old behaviour for callers that cannot look.

    With `request.variants` the matrix gains a dimension: every robot x symbol runs once per
    variant, grouped variant-first (`regime_BTC__H0`, `regime_ETH__H0`, …, `regime_BTC__H1`),
    so one artefact holds the comparison that used to be several batches read side by side.
    """
    cells: list[BatchCell] = []
    for variant in request.variants or (None,):
        for robot in request.robots:
            if robot == "pairs":
                cells.append(_pairs_cell(request, variant=variant, exists=exists, series=series))
                continue
            cells.extend(
                _single_cell(
                    request,
                    robot,
                    symbol,
                    variant=variant,
                    exists=exists,
                    series=series,
                    wired=wired,
                )
                for symbol in request.symbols
            )
    return cells


def _variant_suffix(variant: BatchVariant | None) -> str:
    """`__H1` when the matrix has variants, empty otherwise.

    Empty for a plain batch on purpose: cell ids are the artefact's primary keys (file
    names, `#/run/<batch>/<cell>` links), so a batch without variants keeps the ids it
    always had — old links, `trials/<cell>.jsonl` names and tables stay valid.
    """
    return f"__{variant.name}" if variant is not None else ""


def _cell_env(request: BatchRequest, variant: BatchVariant | None) -> dict[str, str]:
    """Global overrides first, then the variant's: a variant wins on a shared key."""
    env = {**request.env, **(variant.env if variant is not None else {})}
    profile = cell_cost_profile(request, variant)
    if profile:
        # The child process reads it as a setting, like every other per-cell value: one
        # transport for settings, and the name is what lands in that run's manifest.
        env["COST_PROFILE"] = profile
    return env


def cell_cost_profile(request: BatchRequest, variant: BatchVariant | None) -> str | None:
    """The cost scenario of one cell: the variant's if it names one, else the batch's."""
    if variant is not None and variant.cost_profile:
        return variant.cost_profile
    return request.cost_profile


def _single_cell(
    request: BatchRequest,
    robot: str,
    symbol: str,
    *,
    variant: BatchVariant | None,
    exists: Callable[[str], bool],
    series: Callable[[str, str, str], bool] | None,
    wired: Sequence[str] | None,
) -> BatchCell:
    base = base_asset(symbol)
    env = _cell_env(request, variant)
    blocked: str | None = None
    catalog, interval = request.catalog, request.interval
    if wired is not None and robot not in wired:
        blocked = f"robot {robot!r} has no backtest adapter"
    if robot == "funding":
        catalog, interval = request.funding_catalog, request.funding_interval
        env["FUNDING_SPOT_ID"] = spot_instrument(symbol)
        env["FUNDING_PERP_ID"] = perp_instrument(symbol)
    if robot in _MODEL_ENV:
        variable, kind = _MODEL_ENV[robot]
        path = env.get(variable) or f"{request.models_dir}/{kind}_{base}_preoos.txt"
        env[variable] = path
        if blocked is None and not exists(path):
            blocked = f"model {path} not found (train it with an end before the first OOS bar)"
    if blocked is None and not exists(catalog):
        blocked = f"catalog {catalog} not found"
    if blocked is None and series is not None:
        blocked = _missing_series(robot, symbol, catalog, interval, exists=exists, series=series)
    return BatchCell(
        cell_id=f"{robot}_{base}{_variant_suffix(variant)}",
        robot=robot,
        symbol=symbol,
        instrument_id=spot_instrument(symbol),
        catalog=catalog,
        interval=interval,
        env=env,
        blocked=blocked,
        cost_profile=cell_cost_profile(request, variant),
    )


def _missing_series(
    robot: str,
    symbol: str,
    catalog: str,
    interval: str,
    *,
    exists: Callable[[str], bool],
    series: Callable[[str, str, str], bool],
) -> str | None:
    """The first data series this cell needs and does not have, named before it starts.

    Why this exists: the 2026-10-03 sweep planned `funding_{SOL,BNB,XRP,DOGE,ADA}` against
    `catalog_2019_4h` — a catalog that exists and holds bars for BTC/ETH only. Five cells
    were launched, five died on `no bars in catalog`, and the batch had already been
    running for eight hours. Checking the catalog directory is not checking the data.

    `funding` needs three series, not one: both legs must live in the *same* catalog
    (`bar_feed.load_multi` reads them through one catalog) and the settlements must be
    there too. A missing settlement series is the quiet case — the run would finish `ok`
    with zero fills, which is the most expensive kind of empty result.
    """
    instrument = spot_instrument(symbol)
    if not series(catalog, instrument, interval):
        return f"no {instrument} {interval} bars in {catalog} (ingest them first)"
    if robot != "funding":
        return None
    perp = perp_instrument(symbol)
    if not series(catalog, perp, interval):
        return f"no {perp} {interval} bars in {catalog}: both funding legs must be in one catalog"
    settlements = f"{catalog}/data/funding/{symbol}/funding.parquet"
    if not exists(settlements):
        return f"no funding settlements at {settlements} (ingest --market um --dataset funding)"
    return None


def _pairs_cell(
    request: BatchRequest,
    *,
    variant: BatchVariant | None,
    exists: Callable[[str], bool],
    series: Callable[[str, str, str], bool] | None,
) -> BatchCell:
    """Pairs trades two legs at once: one cell for the first two symbols, not one per symbol."""
    symbols = list(request.symbols)
    blocked = None if len(symbols) >= 2 else "pairs needs two symbols"
    leg_a = symbols[1] if len(symbols) >= 2 else symbols[0]
    leg_b = symbols[0]
    # PairsParams defaults are ETH (A) / BTC (B); keep that orientation when both exist.
    if {"ETHUSDT", "BTCUSDT"} <= set(symbols):
        leg_a, leg_b = "ETHUSDT", "BTCUSDT"
    env = {
        **_cell_env(request, variant),
        "PAIRS_LEG_A": spot_instrument(leg_a),
        "PAIRS_LEG_B": spot_instrument(leg_b),
    }
    if blocked is None and not exists(request.catalog):
        blocked = f"catalog {request.catalog} not found"
    if blocked is None and series is not None:
        for leg in (leg_a, leg_b):
            instrument = spot_instrument(leg)
            if not series(request.catalog, instrument, request.interval):
                blocked = (
                    f"no {instrument} {request.interval} bars in "
                    f"{request.catalog} (ingest them first)"
                )
                break
    return BatchCell(
        cell_id=f"pairs_{base_asset(leg_a)}{base_asset(leg_b)}{_variant_suffix(variant)}",
        robot="pairs",
        symbol=leg_a,
        instrument_id=spot_instrument(leg_a),
        catalog=request.catalog,
        interval=request.interval,
        env=env,
        blocked=blocked,
        cost_profile=cell_cost_profile(request, variant),
    )


def research_job_config(request: BatchRequest, cell: BatchCell) -> dict[str, object]:
    """The `run_research_job` payload for one cell (same shape the Research tab sends)."""
    payload: dict[str, object] = {
        "robot": cell.robot,
        "source": "catalog",
        "folds": request.folds,
        "is_fraction": str(request.is_fraction),
        "generate_tearsheet": False,
        "journal": False,
        "catalog_path": cell.catalog,
        "instrument_id": cell.instrument_id,
        "bar_interval": cell.interval,
    }
    if request.days is not None:
        payload["days"] = request.days
    if request.embargo_bars is not None:
        payload["embargo_bars"] = request.embargo_bars
    return payload
