from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, cast

from nautilus_lab.api.paper_runner import PaperRunConfig, execute_paper


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Run paper trading simulation for the API.")
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--reports-dir", required=True)
    args = parser.parse_args(argv)
    payload = cast(dict[str, Any], json.loads(Path(args.config_json).read_text(encoding="utf-8")))
    reports_dir = Path(args.reports_dir)
    job = PaperRunConfig(
        robot=str(payload.get("robot", "regime")),
        bars=int(payload.get("bars", 500)),
        source=str(payload.get("source", "synthetic")),
    )
    result, log_text = execute_paper(job)
    log_path = reports_dir / "paper.log"
    json_path = reports_dir / "paper.json"
    log_path.write_text(
        log_text + f"\nProcess finished with code {0 if not result.get('is_error') else 1}\n"
    )
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 1 if result.get("is_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
