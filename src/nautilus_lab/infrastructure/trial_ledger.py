"""`research/trials.jsonl`: the append-only trial ledger behind DSR (docs/27 R-3).

One line per search: when, which dataset, which configurations. Lines are only
appended, and the count is recomputed from the whole file each time. A line lost to a
crash therefore under-counts one search and never corrupts the rest. The file is meant
to be committed next to `research/journal.md`: it is evidence about the research, not a
cache.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path


class JsonlTrialLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, dataset: str, trial_ids: Iterable[str]) -> int:
        trials = sorted(set(trial_ids))
        if trials:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = {
                "recorded_at": datetime.now(UTC).isoformat(),
                "dataset": dataset,
                "trials": trials,
            }
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, sort_keys=True) + "\n")
        return len(self.distinct(dataset))

    def distinct(self, dataset: str) -> set[str]:
        """Every trial ever recorded for `dataset`. Unreadable lines are skipped."""
        seen: set[str] = set()
        if not self.path.is_file():
            return seen
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and entry.get("dataset") == dataset:
                seen.update(str(item) for item in entry.get("trials") or [])
        return seen
