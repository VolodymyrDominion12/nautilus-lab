from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, cast

from nautilus_lab.api.ml_runner import MLTrainConfig, execute_ml_train


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Run ML training job for the API.")
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--reports-dir", required=True)
    args = parser.parse_args(argv)
    payload = cast(dict[str, Any], json.loads(Path(args.config_json).read_text(encoding="utf-8")))
    reports_dir = Path(args.reports_dir)
    job = MLTrainConfig(
        model_type=str(payload.get("model_type", "formulaic")),
        catalog_path=payload.get("catalog_path"),
        instrument_id=payload.get("instrument_id"),
        bar_interval=payload.get("bar_interval"),
        output_path=payload.get("output_path"),
        folds=int(payload.get("folds", 5)),
        embargo=int(payload.get("embargo", 10)),
        horizon=int(payload.get("horizon", 5)),
        profit_multiple=str(payload.get("profit_multiple", "2")),
        stop_multiple=str(payload.get("stop_multiple", "1")),
        vol_window=int(payload.get("vol_window", 20)),
    )
    result, log_text = execute_ml_train(job)
    log_path = reports_dir / "ml_train.log"
    json_path = reports_dir / "ml_train.json"
    log_path.write_text(
        log_text + f"\nProcess finished with code {0 if not result.get('is_error') else 1}\n"
    )
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 1 if result.get("is_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
