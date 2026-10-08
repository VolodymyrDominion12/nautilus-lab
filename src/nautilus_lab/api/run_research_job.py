from __future__ import annotations

import time

#: Taken before the heavy imports below (Nautilus, pandas), so `timings.json` can say how
#: much of a cell's wall time is the interpreter starting rather than backtesting.
_IMPORTS_STARTED = time.perf_counter()

import contextlib  # noqa: E402
import cProfile  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pstats  # noqa: E402
from argparse import ArgumentParser  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, cast  # noqa: E402

from nautilus_lab.api.research_runner import (  # noqa: E402
    ResearchJobConfig,
    default_tearsheet_path,
    execute_research,
    write_job_artifacts,
)
from nautilus_lab.application.timing import TIMINGS, format_phase_table  # noqa: E402

_IMPORT_SECONDS = time.perf_counter() - _IMPORTS_STARTED

#: Set to 1/true to write `profile.pstats` + `profile.txt` next to `last_run.json`
#: (`run_batch_job --profile` sets it for every cell).
PROFILE_ENV = "RESEARCH_PROFILE"
#: Rows of the cumulative-time table in `profile.txt`.
PROFILE_ROWS = 60


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run one nautilus-lab research job for the API.")
    parser.add_argument("--config-json", required=True, help="Path to JSON job config")
    parser.add_argument("--reports-dir", required=True, help="Directory for last_run.* artifacts")
    return parser


def _job_from_payload(payload: dict[str, Any], reports_dir: Path) -> ResearchJobConfig:
    robot = str(payload["robot"])
    source = str(payload["source"])
    tearsheet_raw = payload.get("tearsheet_path")
    tearsheet_path = str(tearsheet_raw) if tearsheet_raw else None
    if payload.get("generate_tearsheet") and not payload.get("pbo") and not tearsheet_path:
        tearsheet_path = default_tearsheet_path(reports_dir, robot)
    overrides = payload.get("param_overrides")
    param_overrides = overrides if isinstance(overrides, dict) else {}
    days_val = payload.get("days")
    if days_val is None and param_overrides and "BACKTEST_DAYS" in param_overrides:
        with contextlib.suppress(ValueError):
            days_val = int(param_overrides["BACKTEST_DAYS"])
    days = int(days_val) if days_val is not None else None
    return ResearchJobConfig(
        robot=robot,
        source=source,
        bars=int(payload.get("bars", 3000)),
        folds=int(payload.get("folds", 2)),
        is_fraction=Decimal(str(payload.get("is_fraction", "0.7"))),
        days=days,
        embargo_bars=payload.get("embargo_bars"),
        use_optuna=bool(payload.get("use_optuna", False)),
        optuna_trials=int(payload.get("optuna_trials", 20)),
        pbo=bool(payload.get("pbo", False)),
        pbo_blocks=int(payload.get("pbo_blocks", 8)),
        bar_vpin=bool(payload.get("bar_vpin", False)),
        tick_vpin=bool(payload.get("tick_vpin", False)),
        hawkes=bool(payload.get("hawkes", False)),
        stress_slice=str(payload["stress_slice"]) if payload.get("stress_slice") else None,
        generate_tearsheet=bool(payload.get("generate_tearsheet", True)),
        journal=bool(payload.get("journal", False)),
        notify=bool(payload.get("notify", False)),
        full_sample=bool(payload.get("full_sample", False)),
        catalog_path=str(payload["catalog_path"]) if payload.get("catalog_path") else None,
        instrument_id=str(payload["instrument_id"]) if payload.get("instrument_id") else None,
        bar_interval=str(payload["bar_interval"]) if payload.get("bar_interval") else None,
        is_start=str(payload["is_start"]) if payload.get("is_start") else None,
        is_end=str(payload["is_end"]) if payload.get("is_end") else None,
        oos_start=str(payload["oos_start"]) if payload.get("oos_start") else None,
        oos_end=str(payload["oos_end"]) if payload.get("oos_end") else None,
        param_overrides={str(k): str(v) for k, v in param_overrides.items()},
        tearsheet_path=tearsheet_path,
        register=str(payload["preregister"]) if payload.get("preregister") else None,
        promote=bool(payload.get("promote", False)),
        cost_profile=str(payload["cost_profile"]) if payload.get("cost_profile") else None,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config_json)
    reports_dir = Path(args.reports_dir)
    payload = cast(dict[str, Any], json.loads(config_path.read_text(encoding="utf-8")))
    job = _job_from_payload(payload, reports_dir)

    command_line = f"research_job {config_path.name}"
    TIMINGS.reset()
    profiler = cProfile.Profile() if _env_flag(PROFILE_ENV) else None
    run_started = time.perf_counter()
    if profiler is not None:
        profiler.enable()
    try:
        result, log_text = execute_research(job)
    finally:
        if profiler is not None:
            profiler.disable()
    run_seconds = time.perf_counter() - run_started
    with TIMINGS.phase("write_artifacts"):
        write_job_artifacts(
            result,
            log_text,
            reports_dir=reports_dir,
            command_line=command_line,
            job=job,
        )
    write_timings(reports_dir, run_seconds=run_seconds)
    if profiler is not None:
        write_profile(profiler, reports_dir)
    return 1 if result.get("is_error") else 0


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def write_timings(reports_dir: Path, *, run_seconds: float) -> dict[str, Any]:
    """`timings.json`: where this job's wall time went (`application/timing.py`)."""
    phases = TIMINGS.snapshot()
    payload: dict[str, Any] = {
        "import_seconds": round(_IMPORT_SECONDS, 3),
        "run_seconds": round(run_seconds, 3),
        "total_seconds": round(_IMPORT_SECONDS + TIMINGS.elapsed(), 3),
        "is_workers": os.environ.get("BACKTEST_IS_WORKERS", "1"),
        "phases": phases,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "timings.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(format_phase_table(phases, total=run_seconds), flush=True)
    return payload


def write_profile(profiler: cProfile.Profile, reports_dir: Path) -> None:
    """The raw profile (for snakeviz / `python -m pstats`) and a readable top list.

    Only this process is profiled: with `BACKTEST_IS_WORKERS` > 1 the in-sample runs happen
    in workers and show up here as waiting. `run_batch_job --profile` therefore runs the
    grid serially.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    profiler.dump_stats(str(reports_dir / "profile.pstats"))
    for sort in ("cumulative", "tottime"):
        buffer = io.StringIO()
        stats = pstats.Stats(profiler, stream=buffer)
        stats.strip_dirs().sort_stats(sort).print_stats(PROFILE_ROWS)
        name = "profile.txt" if sort == "cumulative" else "profile_self.txt"
        (reports_dir / name).write_text(buffer.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
