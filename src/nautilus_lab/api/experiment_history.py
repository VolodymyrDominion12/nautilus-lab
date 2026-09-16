from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast


def history_dir(reports_dir: Path) -> Path:
    path = reports_dir / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def archive_job_result(result: dict[str, Any], *, reports_dir: Path, robot: str) -> Path:
    """Persist one finished run for the experiment history panel."""
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = f"{stamp}_{robot}.json"
    target = history_dir(reports_dir) / filename
    payload = {
        **result,
        "archived_at": datetime.now(UTC).isoformat(),
        "history_id": filename.removesuffix(".json"),
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def list_history(reports_dir: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    directory = history_dir(reports_dir)
    files = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    rows: list[dict[str, Any]] = []
    for path in files[: max(limit, 0)]:
        with path.open(encoding="utf-8") as handle:
            row = cast(dict[str, Any], json.load(handle))
        row.setdefault("history_id", path.stem)
        rows.append(row)
    return rows


def load_history_entry(reports_dir: Path, history_id: str) -> dict[str, Any] | None:
    path = history_dir(reports_dir) / f"{history_id}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))
