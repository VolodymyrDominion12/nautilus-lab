"""A batch backtest: a matrix of robots x instruments, each cell one walk-forward.

This is the planning half, with no I/O: which cells a request expands to, what each cell
needs (catalog, interval, model paths, the funding perp), and which cells cannot run and
why — said **before** the batch starts, instead of discovering it as a failed cell an
hour later (the 2026-09-29 sweep: `ml_obi` had no model, `glft` has no adapter).

The running half lives in `api/batch_runner.py`; the result rows in `api/batch_store.py`.
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
    #: Extra settings for every cell (e.g. `DRAWDOWN_COOLDOWN_DAYS=3`), as env overrides.
    env: dict[str, str] = field(default_factory=dict)
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
        if not (1 <= self.parallel <= 8):
            raise ValueError("parallel must be in [1, 8]")
        for key in self.env:
            if not re.match(r"^[A-Z][A-Z0-9_]*$", key):
                raise ValueError(f"env override {key!r} is not a SETTINGS_NAME")


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
    wired: Sequence[str] | None = None,
) -> list[BatchCell]:
    """Expand the request into cells, marking the ones that cannot run and why.

    `exists` answers "is there a file at this repo-relative path" (models, catalogs), so
    this function stays pure and testable. `wired` is the set of robots with a backtest
    adapter (`domain/regime.py::require_backtest_support`); None = do not check.
    """
    cells: list[BatchCell] = []
    for robot in request.robots:
        if robot == "pairs":
            cells.append(_pairs_cell(request, exists=exists))
            continue
        cells.extend(
            _single_cell(request, robot, symbol, exists=exists, wired=wired)
            for symbol in request.symbols
        )
    return cells


def _single_cell(
    request: BatchRequest,
    robot: str,
    symbol: str,
    *,
    exists: Callable[[str], bool],
    wired: Sequence[str] | None,
) -> BatchCell:
    base = base_asset(symbol)
    env = {**request.env}
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
    return BatchCell(
        cell_id=f"{robot}_{base}",
        robot=robot,
        symbol=symbol,
        instrument_id=spot_instrument(symbol),
        catalog=catalog,
        interval=interval,
        env=env,
        blocked=blocked,
    )


def _pairs_cell(request: BatchRequest, *, exists: Callable[[str], bool]) -> BatchCell:
    """Pairs trades two legs at once: one cell for the first two symbols, not one per symbol."""
    symbols = list(request.symbols)
    blocked = None if len(symbols) >= 2 else "pairs needs two symbols"
    leg_a = symbols[1] if len(symbols) >= 2 else symbols[0]
    leg_b = symbols[0]
    # PairsParams defaults are ETH (A) / BTC (B); keep that orientation when both exist.
    if {"ETHUSDT", "BTCUSDT"} <= set(symbols):
        leg_a, leg_b = "ETHUSDT", "BTCUSDT"
    env = {
        **request.env,
        "PAIRS_LEG_A": spot_instrument(leg_a),
        "PAIRS_LEG_B": spot_instrument(leg_b),
    }
    if blocked is None and not exists(request.catalog):
        blocked = f"catalog {request.catalog} not found"
    return BatchCell(
        cell_id=f"pairs_{base_asset(leg_a)}{base_asset(leg_b)}",
        robot="pairs",
        symbol=leg_a,
        instrument_id=spot_instrument(leg_a),
        catalog=request.catalog,
        interval=request.interval,
        env=env,
        blocked=blocked,
    )


def research_job_config(request: BatchRequest, cell: BatchCell) -> dict[str, object]:
    """The `run_research_job` payload for one cell (same shape the Research tab sends)."""
    return {
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
