"""Refuse to backtest a bar series whose quality check failed (docs/34, P2).

The archive ingest stores one QC verdict per bar type in `<catalog>/quality.json`.
This gate reads it at load time:

* `fail` -> `DataQualityError`, unless the run explicitly allows it
  (`ALLOW_FAILED_DATA=true`, for looking *at* the defect);
* `warn`, `ok` -> allowed;
* no report (catalogs ingested over REST before QC existed) -> allowed and reported
  as `unknown`. Blocking those would stop every existing run on day one; the
  manifest records the status so an `unknown` result can be told apart later.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from nautilus_lab.domain.errors import DataQualityError

QUALITY_FILE = "quality.json"
_RANK = {"ok": 0, "unknown": 1, "warn": 2, "fail": 3}


def quality_reports(catalog_root: Path) -> dict[str, dict[str, object]]:
    target = catalog_root / QUALITY_FILE
    if not target.exists():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): value for key, value in loaded.items() if isinstance(value, dict)}


def quality_status(catalog_root: Path, bar_type: str) -> str:
    """`ok` | `warn` | `fail` | `unknown` for one bar type of one catalog."""
    report = quality_reports(catalog_root).get(bar_type)
    if report is None:
        return "unknown"
    status = report.get("status")
    return status if isinstance(status, str) and status in _RANK else "unknown"


def worst_status(statuses: Iterable[str]) -> str:
    """The worst of several statuses; `unknown` for none."""
    collected = list(statuses)
    if not collected:
        return "unknown"
    return max(collected, key=lambda item: _RANK.get(item, _RANK["unknown"]))


class QualityGate:
    """Callable checked before a catalog series is read into a backtest."""

    def __init__(self, catalog_root: Path, *, allow_failed: bool = False) -> None:
        self._root = catalog_root.expanduser().resolve()
        self._allow_failed = allow_failed

    def __call__(self, bar_type: str) -> str:
        status = quality_status(self._root, bar_type)
        if status == "fail" and not self._allow_failed:
            report = quality_reports(self._root).get(bar_type, {})
            suspects = report.get("relisting_suspects")
            raise DataQualityError(
                f"{bar_type} failed its data-quality check "
                f"(missing bars {report.get('missing_bars')}, "
                f"re-used ticker suspects {len(suspects) if isinstance(suspects, list) else 0}); "
                f"see {self._root / QUALITY_FILE}. Re-ingest, or set ALLOW_FAILED_DATA=true "
                "to run on it deliberately."
            )
        return status
