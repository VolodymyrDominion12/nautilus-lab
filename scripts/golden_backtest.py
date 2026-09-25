"""Golden backtests: fixed synthetic data + fixed settings -> numbers kept in git.

    uv run python scripts/golden_backtest.py            # compare with the snapshot
    uv run python scripts/golden_backtest.py --update   # rewrite it (review the diff!)

Why (docs/27 E-2.6): an upgrade of NautilusTrader, pandas or numpy can change fills,
fees or the equity curve without a single line changing in this repository. Every OOS
number in the research journal would then silently mean something else. These runs
use deterministic synthetic bars (seeded) and settings built from the code defaults
only — no `.env`, no shell variables (AGENTS.md: shell `TAKER_FEE` overrides `.env`) —
so the only thing that can move the numbers is code: ours or a dependency's.

The snapshot (`tests/golden/backtests.json`) records the engine version it was made
with. `tests/integration/test_golden_backtest.py` fails on any difference and prints
it metric by metric. When the difference is intended (a fix in our code, or an engine
upgrade whose effect was read and accepted), run `--update` and commit the new file in
the same PR, with the reason in the commit message.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from nautilus_lab.application.dtos import BacktestReport
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import (
    research_request,
    research_use_case,
    walk_forward_request,
    walk_forward_use_case,
)

SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "golden" / "backtests.json"
BARS = 3000
WALK_FORWARD_BARS = 2000
WALK_FORWARD_FOLDS = 2


def hermetic_settings(catalog_dir: Path) -> Settings:
    """Code defaults for every field: init values beat both `.env` and the environment."""
    values: dict[str, Any] = {
        name: info.get_default(call_default_factory=True)
        for name, info in Settings.model_fields.items()
    }
    # Synthetic runs never read a catalog; point any reader at an empty directory anyway.
    values["catalog_path"] = str(catalog_dir)
    values["catalog_paths"] = ""
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def backtest_numbers(report: BacktestReport) -> dict[str, Any]:
    metrics = report.metrics
    return {
        "fills": report.fills,
        "positions": report.positions,
        "ending_balance": _text(report.ending_balance),
        "realized_balance": _text(report.realized_balance),
        "unrealized_pnl": _text(report.unrealized_pnl),
        "fees_paid": _text(metrics.fees_paid if metrics else None),
        "max_drawdown": _text(metrics.max_drawdown if metrics else None),
        "turnover": _text(metrics.turnover if metrics else None),
        "traded_notional": _text(metrics.traded_notional if metrics else None),
        "sharpe_like": _text(metrics.sharpe_like if metrics else None),
        "risk_breaches": [[reason, count] for reason, count in report.risk_breaches],
    }


@dataclass(frozen=True, slots=True)
class GoldenCase:
    name: str
    run: Callable[[Settings], dict[str, Any]]


def _single(robot: RobotName) -> Callable[[Settings], dict[str, Any]]:
    def run(cfg: Settings) -> dict[str, Any]:
        request = research_request(cfg, bar_count=BARS, robot=robot, source=BarOrigin.SYNTHETIC)
        return backtest_numbers(research_use_case(cfg).execute(request))

    return run


def _walk_forward(robot: RobotName) -> Callable[[Settings], dict[str, Any]]:
    def run(cfg: Settings) -> dict[str, Any]:
        request = walk_forward_request(
            cfg,
            robot=robot,
            source=BarOrigin.SYNTHETIC,
            bar_count=WALK_FORWARD_BARS,
            folds=WALK_FORWARD_FOLDS,
        )
        report = walk_forward_use_case(cfg).execute_multi(request)
        return {
            "folds": len(report.folds),
            "oos_returns": [_text(value) for value in report.oos_returns],
            "profitable_folds": report.profitable_folds,
            "mean_oos_return": _text(report.mean_oos_return),
            "total_oos_fills": report.total_oos_fills,
            "mean_buy_and_hold_return": _text(report.mean_buy_and_hold_return),
        }

    return run


#: Robots that need no trained model and no catalog. `formulaic_lgbm`, `meta_label` and
#: `ml_obi` need model files, so they are covered by their own tests, not here.
CASES: tuple[GoldenCase, ...] = (
    GoldenCase("regime", _single(RobotName.REGIME)),
    GoldenCase("ema", _single(RobotName.EMA)),
    GoldenCase("adaptive_ema", _single(RobotName.ADAPTIVE_EMA)),
    GoldenCase("vpin_momentum", _single(RobotName.VPIN_MOMENTUM)),
    GoldenCase("walk_forward_regime", _walk_forward(RobotName.REGIME)),
)


def engine_version() -> str | None:
    try:
        return metadata.version("nautilus_trader")
    except metadata.PackageNotFoundError:
        return None


def run_all() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="golden-catalog-") as catalog:
        cfg = hermetic_settings(Path(catalog))
        results = {case.name: case.run(cfg) for case in CASES}
    return {
        "nautilus_trader": engine_version(),
        "bars": BARS,
        "cases": results,
    }


def differences(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """Human-readable lines, one per value that moved. Empty = identical."""
    lines: list[str] = []
    if expected.get("nautilus_trader") != actual.get("nautilus_trader"):
        lines.append(
            f"engine: nautilus_trader {expected.get('nautilus_trader')} -> "
            f"{actual.get('nautilus_trader')}"
        )
    old_cases: Mapping[str, Any] = expected.get("cases", {})
    new_cases: Mapping[str, Any] = actual.get("cases", {})
    for name in sorted(old_cases.keys() | new_cases.keys()):
        if name not in new_cases:
            lines.append(f"{name}: case removed")
            continue
        if name not in old_cases:
            lines.append(f"{name}: new case (not in the snapshot)")
            continue
        old, new = old_cases[name], new_cases[name]
        for key in sorted(old.keys() | new.keys()):
            if old.get(key) != new.get(key):
                lines.append(f"{name}.{key}: {old.get(key)!r} -> {new.get(key)!r}")
    return lines


def load_snapshot(path: Path = SNAPSHOT) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def write_snapshot(results: Mapping[str, Any], path: Path = SNAPSHOT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--update", action="store_true", help="rewrite the snapshot")
    args = parser.parse_args(argv)

    actual = run_all()
    if args.update:
        previous = load_snapshot()
        write_snapshot(actual)
        changed = differences(previous, actual) if previous else ["(new snapshot)"]
        print(f"wrote {SNAPSHOT}")
        print("\n".join(changed) or "no change")
        return 0

    expected = load_snapshot()
    if expected is None:
        print(f"no snapshot at {SNAPSHOT}; create it with --update", file=sys.stderr)
        return 2
    changed = differences(expected, actual)
    if changed:
        print("golden backtests changed:\n  " + "\n  ".join(changed), file=sys.stderr)
        return 1
    print(f"golden backtests identical ({len(CASES)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
