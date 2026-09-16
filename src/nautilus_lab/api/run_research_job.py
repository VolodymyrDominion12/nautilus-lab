from __future__ import annotations

import json
from argparse import ArgumentParser
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from nautilus_lab.api.research_runner import (
    ResearchJobConfig,
    default_tearsheet_path,
    execute_research,
    write_job_artifacts,
)


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
    return ResearchJobConfig(
        robot=robot,
        source=source,
        bars=int(payload.get("bars", 3000)),
        folds=int(payload.get("folds", 2)),
        is_fraction=Decimal(str(payload.get("is_fraction", "0.7"))),
        embargo_bars=payload.get("embargo_bars"),
        use_optuna=bool(payload.get("use_optuna", False)),
        optuna_trials=int(payload.get("optuna_trials", 20)),
        pbo=bool(payload.get("pbo", False)),
        pbo_blocks=int(payload.get("pbo_blocks", 8)),
        bar_vpin=bool(payload.get("bar_vpin", False)),
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
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config_path = Path(args.config_json)
    reports_dir = Path(args.reports_dir)
    payload = cast(dict[str, Any], json.loads(config_path.read_text(encoding="utf-8")))
    job = _job_from_payload(payload, reports_dir)

    command_line = f"research_job {config_path.name}"
    result, log_text = execute_research(job)
    write_job_artifacts(
        result,
        log_text,
        reports_dir=reports_dir,
        command_line=command_line,
        job=job,
    )
    return 1 if result.get("is_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
