"""Where batch backtests live on disk, and the rows the dashboard's tables are built from.

Layout (docs/30)::

    reports/batches/<batch_id>/
      batch.json                  request, per-cell status, pid, timestamps
      batch.log                   the batch process's own log
      cells/<cell_id>/
        last_run.json / .log      `run_research_job` output (the Research tab's format)
        decisions/<session>_*.jsonl   decision_trace records, one session per OOS fold
        summary.json              the cell's table row (numbers + digest + trades), cached

`batch.json` has one writer, the batch process (`api/run_batch_job.py`); the API reads it
and only ever writes it to create a batch. Writes go through a temp file and `replace`,
so a reader never sees half a file.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from nautilus_lab.application.batch_plan import BatchCell, BatchRequest, safe_id
from nautilus_lab.application.decision_digest import build_digest
from nautilus_lab.application.trade_history import reconstruct_trades_from_decisions
from nautilus_lab.infrastructure.decision_log_writer import JsonlDecisionLogWriter
from nautilus_lab.infrastructure.settings import Settings

#: Cell states, in the order a cell moves through them.
QUEUED, RUNNING, OK, FAILED, BLOCKED, CANCELLED = (
    "queued",
    "running",
    "ok",
    "failed",
    "blocked",
    "cancelled",
)
_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
#: Records read per fold for the summary and the trade list (one 1h fold is ~1.8k).
FOLD_READ_LIMIT = 200_000


def batches_dir(reports_dir: Path) -> Path:
    return reports_dir / "batches"


def batch_dir(reports_dir: Path, batch_id: str) -> Path:
    if not _ID_OK.match(batch_id):
        raise ValueError(f"invalid batch id {batch_id!r}")
    return batches_dir(reports_dir) / batch_id


def cell_dir(batch_path: Path, cell_id: str) -> Path:
    if not _ID_OK.match(cell_id):
        raise ValueError(f"invalid cell id {cell_id!r}")
    return batch_path / "cells" / cell_id


def decisions_dir(cell_path: Path) -> Path:
    return cell_path / "decisions"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def request_to_dict(request: BatchRequest) -> dict[str, Any]:
    payload = asdict(request)
    payload["is_fraction"] = str(request.is_fraction)
    payload["robots"] = list(request.robots)
    payload["symbols"] = list(request.symbols)
    return payload


def request_from_dict(payload: dict[str, Any]) -> BatchRequest:
    return BatchRequest(
        robots=tuple(payload.get("robots") or ()),
        symbols=tuple(payload.get("symbols") or ()),
        interval=str(payload.get("interval", "1h")),
        catalog=str(payload.get("catalog", "catalog")),
        funding_catalog=str(payload.get("funding_catalog", "catalog_2019_4h")),
        funding_interval=str(payload.get("funding_interval", "4h")),
        folds=int(payload.get("folds", 4)),
        is_fraction=Decimal(str(payload.get("is_fraction", "0.7"))),
        parallel=int(payload.get("parallel", 2)),
        label=str(payload.get("label", "")),
        days=int(payload["days"]) if payload.get("days") is not None else None,
        env={str(k): str(v) for k, v in (payload.get("env") or {}).items()},
        models_dir=str(payload.get("models_dir", "models/clean")),
    )


def create_batch(
    reports_dir: Path, request: BatchRequest, cells: Iterable[BatchCell]
) -> tuple[str, Path]:
    """Write a new batch directory with every cell queued (or blocked, with the reason)."""
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    label = safe_id(request.label)[:40] if request.label else "batch"
    batch_id = f"{stamp}_{label}"
    path = batch_dir(reports_dir, batch_id)
    suffix = 1
    while path.exists():
        suffix += 1
        path = batch_dir(reports_dir, f"{batch_id}_{suffix}")
    batch_id = path.name
    payload = {
        "id": batch_id,
        "label": request.label,
        "created_at": _now(),
        "status": QUEUED,
        "pid": None,
        "request": request_to_dict(request),
        "cells": [
            {
                **asdict(cell),
                "status": QUEUED if cell.runnable else BLOCKED,
                "started_at": None,
                "finished_at": None,
                "returncode": None,
                "error": cell.blocked,
            }
            for cell in cells
        ],
    }
    write_json(path / "batch.json", payload)
    return batch_id, path


def load_batch(reports_dir: Path, batch_id: str) -> dict[str, Any] | None:
    return read_json(batch_dir(reports_dir, batch_id) / "batch.json")


def list_batches(reports_dir: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    root = batches_dir(reports_dir)
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), reverse=True):
        batch = read_json(path / "batch.json")
        if batch is None:
            continue
        counts = Counter(str(cell.get("status")) for cell in batch.get("cells", []))
        rows.append(
            {
                "id": batch.get("id", path.name),
                "label": batch.get("label", ""),
                "created_at": batch.get("created_at"),
                "finished_at": batch.get("finished_at"),
                "status": effective_status(batch),
                "cells": len(batch.get("cells", [])),
                "counts": dict(counts),
                "robots": batch.get("request", {}).get("robots", []),
                "symbols": batch.get("request", {}).get("symbols", []),
                "imported_from": batch.get("imported_from"),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def effective_status(batch: dict[str, Any]) -> str:
    """The stored status, corrected when the batch process died without saying so."""
    status = str(batch.get("status", QUEUED))
    if status in (RUNNING, QUEUED) and batch.get("pid") and not pid_alive(batch.get("pid")):
        return "lost"
    return status


# --- decisions of one cell ------------------------------------------------------------


def decision_reader(cell_path: Path, cfg: Settings) -> JsonlDecisionLogWriter:
    """A reader over the cell's decision files (retention off: nothing is ever pruned)."""
    scoped = cfg.model_copy(
        update={
            "decision_log_enabled": True,
            "decision_log_dir": str(decisions_dir(cell_path)),
            "decision_log_retention_days": 0,
        }
    )
    return JsonlDecisionLogWriter(scoped)


def fold_sessions(result: dict[str, Any] | None, cell_path: Path) -> list[dict[str, Any]]:
    """One entry per OOS fold: its session key (the decision file key) and window."""
    folds = ((result or {}).get("multi_window") or {}).get("folds") or []
    sessions: list[dict[str, Any]] = []
    for fold in folds:
        session = fold.get("session_id")
        if session:
            sessions.append(
                {
                    "index": fold.get("index"),
                    "session_id": session,
                    "window": fold.get("window") or {},
                    "oos_return_raw": fold.get("oos_return_raw"),
                    "buy_and_hold_return_raw": fold.get("buy_and_hold_return_raw"),
                    "fills": fold.get("fills"),
                    "selected": fold.get("selected"),
                }
            )
    if sessions:
        return sessions
    # Imported sweeps and older runs: whatever sessions the decision files hold.
    keys = sorted(
        {
            match.group("key")
            for match in (
                re.match(r"^(?P<key>.+)_\d{4}-\d{2}-\d{2}\.jsonl$", path.name)
                for path in decisions_dir(cell_path).glob("*.jsonl")
            )
            if match
        }
    )
    return [{"index": i, "session_id": key, "window": {}} for i, key in enumerate(keys)]


def find_session_cell(reports_dir: Path, session_key: str) -> Path | None:
    """The batch cell whose decision files hold `session_key`, if any (newest batch first)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", session_key).strip("._-")
    if not safe:
        return None
    root = batches_dir(reports_dir)
    if not root.exists():
        return None
    for path in sorted(root.glob(f"*/cells/*/decisions/{safe}_*.jsonl"), reverse=True):
        return path.parent.parent
    return None


# --- the table row of one cell --------------------------------------------------------


def _num(value: object) -> float | None:
    try:
        return None if value is None else float(str(value))
    except ValueError:
        return None


def _trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    wins = [t for t in closed if (_num(t.get("realized_pnl")) or 0) > 0]
    r_values = [r for r in (_num(t.get("r_multiple")) for t in closed) if r is not None]
    slippage = [s for s in (_num(t.get("entry_slippage_bps")) for t in trades) if s is not None]
    exits = Counter(str(t.get("exit_outcome")) for t in closed)
    return {
        "trades": len(trades),
        "closed": len(closed),
        "win_rate": round(len(wins) / len(closed), 4) if closed else None,
        "avg_r": round(sum(r_values) / len(r_values), 3) if r_values else None,
        "avg_slippage_bps": round(sum(slippage) / len(slippage), 2) if slippage else None,
        "exits": dict(exits.most_common()),
    }


def build_cell_summary(cell_path: Path, cell: dict[str, Any], cfg: Settings) -> dict[str, Any]:
    """Numbers (walk-forward), decisions (digest) and trades of one cell, for the table.

    Cached in `summary.json` once the cell finished: reading ~7k records per cell on every
    poll of the batch table would make the page slow for no new information.
    """
    result = read_json(cell_path / "last_run.json")
    multi = (result or {}).get("multi_window") or {}
    reader = decision_reader(cell_path, cfg)
    folds = fold_sessions(result, cell_path)
    all_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for fold in folds:
        rows = reader.get_recent_logs(str(fold["session_id"]), lines=FOLD_READ_LIMIT)
        all_rows.extend(rows)
        trades.extend(reconstruct_trades_from_decisions(rows))
    digest = build_digest(all_rows, max_narratives=0, no_signal_samples=0) if all_rows else None
    bars = [r for r in all_rows if r.get("kind", "bar_decision") == "bar_decision"]
    untraced = sum(
        1 for r in bars if not r.get("steps") and r.get("outcome") not in ("WARMUP", None)
    )
    in_position = sum(
        1 for r in bars if (r.get("account") or {}).get("position") in ("LONG", "SHORT")
    )
    return {
        "cell_id": cell.get("cell_id"),
        "robot": cell.get("robot"),
        "symbol": cell.get("symbol"),
        "instrument_id": cell.get("instrument_id"),
        "interval": cell.get("interval"),
        "catalog": cell.get("catalog"),
        "status": cell.get("status"),
        "error": cell.get("error") or (result or {}).get("error_message"),
        "numbers": {
            "profitable": multi.get("profitable"),
            "fold_count": multi.get("fold_count"),
            "mean_oos": _num(multi.get("mean_oos_raw")),
            "worst_oos": _worst(multi),
            "buy_and_hold_mean": _num(multi.get("buy_and_hold_mean_raw")),
            "mean_excess": _num(multi.get("mean_excess_return_raw")),
            "beats_buy_and_hold": multi.get("beats_buy_and_hold"),
            "total_oos_fills": multi.get("total_oos_fills"),
            "mean_paid_cost_rate": multi.get("mean_paid_cost_rate"),
            "mean_breakeven_cost": multi.get("mean_breakeven_cost"),
        },
        "folds": folds,
        "decisions": {
            "records": len(all_rows),
            "bars": len(bars),
            "untraced_bars": untraced,
            "in_position_pct": round(in_position / len(bars) * 100, 1) if bars else None,
            "outcomes": digest.outcomes if digest else {},
            "blocked_by": digest.blocked_by if digest else {},
            "regime_share_pct": digest.regime_share_pct if digest else {},
            "near_misses": digest.near_misses if digest else 0,
            "bar_seq_gaps": digest.bar_seq_gaps if digest else 0,
        },
        "trades": _trade_stats(trades),
        "summarized_at": _now(),
    }


def _worst(multi: dict[str, Any]) -> float | None:
    values = [
        _num(fold.get("oos_return_raw"))
        for fold in multi.get("folds") or []
        if fold.get("oos_return_raw") is not None
    ]
    numbers = [v for v in values if v is not None]
    return min(numbers) if numbers else None


def cell_summary(batch_path: Path, cell: dict[str, Any], cfg: Settings) -> dict[str, Any]:
    """The cached summary of a finished cell, or a fresh one for a cell still moving."""
    path = cell_dir(batch_path, str(cell["cell_id"]))
    cached = read_json(path / "summary.json")
    finished = cell.get("status") in (OK, FAILED)
    if cached is not None and finished and cached.get("status") == cell.get("status"):
        return cached
    summary = build_cell_summary(path, cell, cfg)
    if finished:
        write_json(path / "summary.json", summary)
    return summary


def batch_payload(reports_dir: Path, batch_id: str, cfg: Settings) -> dict[str, Any] | None:
    batch = load_batch(reports_dir, batch_id)
    if batch is None:
        return None
    path = batch_dir(reports_dir, batch_id)
    rows = []
    for cell in batch.get("cells", []):
        if cell.get("status") in (OK, FAILED):
            rows.append(cell_summary(path, cell, cfg))
        else:
            rows.append(
                {
                    key: cell.get(key)
                    for key in (
                        "cell_id",
                        "robot",
                        "symbol",
                        "instrument_id",
                        "interval",
                        "catalog",
                        "status",
                        "error",
                        "started_at",
                    )
                }
            )
    return {**batch, "status": effective_status(batch), "rows": rows}


def run_payload(
    reports_dir: Path, batch_id: str, cell_id: str, cfg: Settings
) -> dict[str, Any] | None:
    """Everything the run page shows above its tabs: the cell, its result and its folds."""
    batch = load_batch(reports_dir, batch_id)
    if batch is None:
        return None
    cell = next((c for c in batch.get("cells", []) if c.get("cell_id") == cell_id), None)
    if cell is None:
        return None
    path = cell_dir(batch_dir(reports_dir, batch_id), cell_id)
    result = read_json(path / "last_run.json")
    summary = (
        cell_summary(batch_dir(reports_dir, batch_id), cell, cfg)
        if cell.get("status") in (OK, FAILED)
        else None
    )
    log_path = path / "last_run.log"
    if not log_path.exists() or not log_path.stat().st_size:
        log_path = path / "stdout.log"
    return {
        "batch_id": batch_id,
        "batch_label": batch.get("label"),
        "cell": cell,
        "result": result,
        "summary": summary,
        "folds": fold_sessions(result, path),
        "log_tail": _tail(log_path, 60),
    }


def _tail(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


# --- importing the 2026-09-29 sweep ---------------------------------------------------


def import_sweep(reports_dir: Path, sweep_dir: Path) -> str:
    """Turn `reports/decision-sweep/` into a batch, so the dashboard shows it today.

    The sweep's decision files hold the OOS window of the **last** fold only, and its
    numbers were parsed from stdout; both are kept as they are and the batch says so
    (`imported_from`). Re-run the batch to get all four folds with the current log.
    """
    status = json.loads((sweep_dir / "status.json").read_text(encoding="utf-8"))
    entries = cast(list[dict[str, Any]], status if isinstance(status, list) else [])
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    batch_id = f"{stamp}_import_decision_sweep"
    path = batch_dir(reports_dir, batch_id)
    cells: list[dict[str, Any]] = []
    for entry in entries:
        key = str(entry.get("key", ""))
        if not _ID_OK.match(key):
            continue
        source = sweep_dir / "decisions" / f"{key}.jsonl"
        target = cell_dir(path, key)
        decisions_dir(target).mkdir(parents=True, exist_ok=True)
        records = 0
        if source.exists() and source.stat().st_size > 0:
            by_session: dict[str, list[str]] = {}
            for line in source.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                session = str(row.get("session_id") or key)
                by_session.setdefault(session, []).append(line)
                records += 1
            for session, lines in by_session.items():
                safe = re.sub(r"[^A-Za-z0-9._-]+", "_", session).strip("._-") or key
                (decisions_dir(target) / f"{safe}_2000-01-01.jsonl").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8"
                )
        write_json(target / "last_run.json", _sweep_result(entry))
        cells.append(
            {
                "cell_id": key,
                "robot": entry.get("robot"),
                "symbol": entry.get("symbol"),
                "instrument_id": f"{str(entry.get('symbol', '')).removesuffix('USDT')}/USDT.SIM",
                "catalog": entry.get("catalog"),
                "interval": entry.get("interval"),
                "env": {},
                "blocked": None,
                "status": OK if entry.get("status") == "ok" else FAILED,
                "started_at": None,
                "finished_at": None,
                "returncode": 0 if entry.get("status") == "ok" else 1,
                "error": entry.get("error") or None,
                "imported_records": records,
            }
        )
    write_json(
        path / "batch.json",
        {
            "id": batch_id,
            "label": "decision-sweep 2026-09-29 (import)",
            "created_at": _now(),
            "finished_at": _now(),
            "status": OK,
            "pid": None,
            "imported_from": str(sweep_dir),
            "note": (
                "Imported: decisions cover the last fold's OOS window only, numbers were "
                "parsed from stdout. Re-run as a batch for all folds and the current log."
            ),
            "request": {"robots": sorted({c["robot"] for c in cells}), "symbols": []},
            "cells": cells,
        },
    )
    return batch_id


def _pct_raw(text: object) -> str | None:
    if not isinstance(text, str) or not text.endswith("%"):
        return None
    try:
        return str(Decimal(text[:-1]) / Decimal("100"))
    except ArithmeticError:
        return None


def _sweep_result(entry: dict[str, Any]) -> dict[str, Any]:
    numbers = entry.get("numbers") or {}
    folds = [
        {
            "index": int(fold.get("index", 0)),
            "oos_return_raw": _pct_raw(fold.get("return")),
            "buy_and_hold_return_raw": _pct_raw(fold.get("buy_hold")),
            "fills": int(fold.get("fills", 0) or 0),
            "selected": fold.get("selected"),
            "window": {
                "out_of_sample_start": fold.get("oos_start"),
                "out_of_sample_end": fold.get("oos_end"),
            },
        }
        for fold in numbers.get("folds") or []
    ]
    agg = numbers.get("aggregate") or {}
    return {
        "is_finished": True,
        "is_error": entry.get("status") != "ok",
        "run_type": "multi_window",
        "robot": entry.get("robot"),
        "error_message": entry.get("error") or None,
        "multi_window": {
            "profitable": (
                f"{agg.get('profitable')}/{agg.get('folds')}" if agg.get("folds") else None
            ),
            "fold_count": len(folds),
            "mean_oos_raw": _pct_raw(agg.get("mean")),
            "buy_and_hold_mean_raw": _pct_raw((numbers.get("baseline") or {}).get("buy_hold")),
            "total_oos_fills": sum(f["fills"] for f in folds),
            "folds": folds,
        },
    }
