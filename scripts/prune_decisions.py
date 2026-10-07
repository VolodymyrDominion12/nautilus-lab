"""Prune old or oversized decision logs from data/paper/decisions (or custom dir).

uv run python scripts/prune_decisions.py
uv run python scripts/prune_decisions.py --days 3 --max-mb 500
uv run python scripts/prune_decisions.py --dir data/vps/paper/decisions --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nautilus_lab.infrastructure.decision_log_writer import prune_decision_logs
from nautilus_lab.infrastructure.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clean up old or excess decision logs by age and total size quota.",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Directory to prune (default: settings.decision_log_dir)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Retention days cutoff (default: settings.decision_log_retention_days)",
    )
    parser.add_argument(
        "--max-mb",
        type=int,
        default=None,
        help="Max size in MB for decision logs (default: settings.decision_log_max_mb)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be pruned without deleting files",
    )
    args = parser.parse_args(argv)

    cfg = Settings()
    target_dir = args.dir or (ROOT / cfg.decision_log_dir)
    retention_days = args.days if args.days is not None else cfg.decision_log_retention_days
    max_mb = args.max_mb if args.max_mb is not None else cfg.decision_log_max_mb
    dry_run = bool(args.dry_run)

    if not target_dir.is_dir():
        print(f"Directory not found: {target_dir}")
        return 0

    count, bytes_freed = prune_decision_logs(
        target_dir,
        retention_days=retention_days,
        max_mb=max_mb,
        dry_run=dry_run,
    )
    mb_freed = bytes_freed / (1024 * 1024)
    action = "Would prune" if dry_run else "Pruned"
    print(f"{action} {count} files ({mb_freed:.2f} MB freed) in {target_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
