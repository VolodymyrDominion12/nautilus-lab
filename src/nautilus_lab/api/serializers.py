from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from nautilus_lab.application.dtos import (
    BacktestReport,
    MultiWindowReport,
    OverfitAuditReport,
    WalkForwardFold,
    WalkForwardReport,
)
from nautilus_lab.domain.deflated_sharpe import DeflatedSharpeResult
from nautilus_lab.domain.metrics import BacktestMetrics


def pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


def decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def serialize_metrics(metrics: BacktestMetrics | None) -> dict[str, Any] | None:
    if metrics is None:
        return None
    return {
        "fees_paid": float(metrics.fees_paid),
        "max_drawdown": float(metrics.max_drawdown),
        "max_dd_pct": f"{float(metrics.max_drawdown) * 100:.2f}%",
        "turnover": float(metrics.turnover),
        "sharpe_like": float(metrics.sharpe_like) if metrics.sharpe_like is not None else None,
    }


def serialize_backtest(report: BacktestReport) -> dict[str, Any]:
    metrics = serialize_metrics(report.metrics)
    return {
        "fills": report.fills,
        "positions": report.positions,
        "ending_balance": float(report.ending_balance)
        if report.ending_balance is not None
        else None,
        "notes": report.notes,
        "tearsheet_path": report.tearsheet_path,
        "metrics": metrics,
        "fees_paid": metrics["fees_paid"] if metrics else 0.0,
        "max_dd_pct": metrics["max_dd_pct"] if metrics else "0%",
        "turnover": metrics["turnover"] if metrics else 0.0,
        "sharpe": metrics["sharpe_like"] if metrics else 0.0,
    }


def serialize_walk_forward(report: WalkForwardReport) -> dict[str, Any]:
    return {
        "selected": report.selected.label(),
        "candidates_tried": report.candidates_tried,
        "window": {
            "in_sample_start": report.window.in_sample_start.isoformat(),
            "in_sample_end": report.window.in_sample_end.isoformat(),
            "out_of_sample_start": report.window.out_of_sample_start.isoformat(),
            "out_of_sample_end": report.window.out_of_sample_end.isoformat(),
        },
        "in_sample": serialize_backtest(report.in_sample),
        "out_of_sample": serialize_backtest(report.out_of_sample),
        "notes": report.notes,
    }


def serialize_fold(fold: WalkForwardFold) -> dict[str, Any]:
    window = fold.window
    return {
        "index": fold.index,
        "oos_return": pct(fold.oos_return),
        "oos_return_raw": decimal_str(fold.oos_return),
        "buy_and_hold_return": pct(fold.buy_and_hold_return),
        "buy_and_hold_return_raw": decimal_str(fold.buy_and_hold_return),
        "selected": fold.selected.label(),
        "fills": fold.out_of_sample.fills,
        "window": {
            "out_of_sample_start": window.out_of_sample_start.isoformat(),
            "out_of_sample_end": window.out_of_sample_end.isoformat(),
        },
    }


def serialize_multi_window(report: MultiWindowReport) -> dict[str, Any]:
    fold_count = len(report.folds)
    beats = report.beats_buy_and_hold()
    return {
        "profitable": f"{report.profitable_folds}/{fold_count}",
        "mean_oos": pct(report.mean_oos_return),
        "mean_oos_raw": decimal_str(report.mean_oos_return),
        "median_oos": pct(report.median_oos_return),
        "worst_oos": pct(report.worst_oos_return),
        "best_oos": pct(report.best_oos_return),
        "buy_and_hold_mean": pct(report.mean_buy_and_hold_return),
        "buy_and_hold_mean_raw": decimal_str(report.mean_buy_and_hold_return),
        "total_oos_fills": report.total_oos_fills,
        "beats_buy_and_hold": beats,
        "folds": [serialize_fold(fold) for fold in report.folds],
        "notes": report.notes,
        "summary_line": report.summary_line(),
    }


def serialize_deflated_sharpe(result: DeflatedSharpeResult) -> dict[str, Any]:
    return {
        "summary_line": result.summary_line(),
        "probability": decimal_str(result.probability),
        "sharpe": decimal_str(result.sharpe),
        "threshold_sharpe": decimal_str(result.threshold_sharpe),
        "observations": result.observations,
        "trials": result.trials,
        "note": result.note,
    }


def serialize_pbo(report: OverfitAuditReport) -> dict[str, Any]:
    return {
        "pbo": decimal_str(report.pbo),
        "blocks": report.blocks,
        "configuration_count": report.configuration_count,
        "split_count": report.split_count,
        "is_meaningful": report.is_meaningful,
        "summary_line": report.summary_line(),
        "deflated_sharpe": serialize_deflated_sharpe(report.deflated_sharpe),
        "notes": report.notes,
    }


def tearsheet_url(saved_path: str | None) -> str | None:
    if not saved_path:
        return None
    from pathlib import Path

    return f"/static_reports/{Path(saved_path).name}"


def build_job_result(
    *,
    run_type: str,
    robot: str,
    source: str,
    is_error: bool = False,
    error_message: str | None = None,
    tearsheet_path: str | None = None,
    multi_window: MultiWindowReport | None = None,
    walk_forward: WalkForwardReport | None = None,
    single_backtest: BacktestReport | None = None,
    pbo: OverfitAuditReport | None = None,
    report_label: str | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    ts_url = tearsheet_url(tearsheet_path)
    summary: dict[str, Any] = {
        "is_finished": True,
        "is_error": is_error,
        "run_type": run_type,
        "robot": robot,
        "source": source,
        "report_label": report_label,
        "finished_at": (finished_at or datetime.now()).isoformat(),
        "tearsheet_url": ts_url,
        "error_message": error_message,
        "multi_window": serialize_multi_window(multi_window) if multi_window else None,
        "walk_forward": serialize_walk_forward(walk_forward) if walk_forward else None,
        "single_backtest": serialize_backtest(single_backtest) if single_backtest else None,
        "pbo": serialize_pbo(pbo) if pbo else None,
    }
    return summary
