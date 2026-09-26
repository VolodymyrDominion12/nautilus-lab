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


def _optional_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _excess_return(robot: Decimal | None, baseline: Decimal | None) -> Decimal | None:
    """Robot minus buy&hold. None when either side is unmeasurable — never guess."""
    if robot is None or baseline is None:
        return None
    return robot - baseline


def serialize_costs(metrics: BacktestMetrics | None) -> dict[str, Any]:
    """Cost-quality block: what was paid against the cost that would zero the PnL.

    `breakeven_cost` is the largest constant fee per unit of traded notional that
    still leaves PnL at zero, in the same units as maker/taker. `cost_headroom` is
    `breakeven - paid`: positive means the result survives even more expensive
    execution, negative means it only worked because this run was cheap. None (not
    zero) whenever nothing was traded, because zero would claim a measurement that
    does not exist.
    """
    if metrics is None:
        return {
            "traded_notional": None,
            "breakeven_cost": None,
            "paid_cost_rate": None,
            "cost_headroom": None,
        }
    breakeven = metrics.breakeven_cost
    paid = metrics.paid_cost_rate
    return {
        "traded_notional": float(metrics.traded_notional),
        "breakeven_cost": _optional_float(breakeven),
        "paid_cost_rate": _optional_float(paid),
        "cost_headroom": _optional_float(
            None if breakeven is None or paid is None else breakeven - paid
        ),
    }


def serialize_metrics(metrics: BacktestMetrics | None) -> dict[str, Any] | None:
    if metrics is None:
        return None
    return {
        "fees_paid": float(metrics.fees_paid),
        "max_drawdown": float(metrics.max_drawdown),
        "max_dd_pct": f"{float(metrics.max_drawdown) * 100:.2f}%",
        "turnover": float(metrics.turnover),
        "sharpe_like": float(metrics.sharpe_like) if metrics.sharpe_like is not None else None,
        **serialize_costs(metrics),
    }


def serialize_backtest(report: BacktestReport) -> dict[str, Any]:
    metrics = serialize_metrics(report.metrics)
    costs = serialize_costs(report.metrics)
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
        "breakeven_cost": costs["breakeven_cost"],
        "paid_cost_rate": costs["paid_cost_rate"],
        "cost_headroom": costs["cost_headroom"],
        "traded_notional": costs["traded_notional"],
    }


def _serialize_window_return(
    report: BacktestReport, starting_equity: Decimal | None
) -> dict[str, Any]:
    """Return of one leg measured against the run's starting equity.

    Uses the engine's ending balance only: when the engine reports none, the return
    is `None` rather than a number reconstructed from something else.
    """
    if starting_equity is None or starting_equity == 0 or report.ending_balance is None:
        return {"return_pct": None, "return_raw": None}
    value = (report.ending_balance - starting_equity) / starting_equity
    return {"return_pct": pct(value), "return_raw": decimal_str(value)}


def serialize_walk_forward(
    report: WalkForwardReport, *, starting_equity: Decimal | None = None
) -> dict[str, Any]:
    in_sample = _serialize_window_return(report.in_sample, starting_equity)
    out_of_sample = _serialize_window_return(report.out_of_sample, starting_equity)
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
        "in_sample_return": in_sample["return_pct"],
        "in_sample_return_raw": in_sample["return_raw"],
        "out_of_sample_return": out_of_sample["return_pct"],
        "out_of_sample_return_raw": out_of_sample["return_raw"],
        "notes": report.notes,
    }


def serialize_fold(fold: WalkForwardFold) -> dict[str, Any]:
    window = fold.window
    excess = _excess_return(fold.oos_return, fold.buy_and_hold_return)
    return {
        "index": fold.index,
        "oos_return": pct(fold.oos_return),
        "oos_return_raw": decimal_str(fold.oos_return),
        "buy_and_hold_return": pct(fold.buy_and_hold_return),
        "buy_and_hold_return_raw": decimal_str(fold.buy_and_hold_return),
        "excess_return": pct(excess),
        "excess_return_raw": decimal_str(excess),
        "beats_buy_and_hold": None if excess is None else excess > 0,
        "selected": fold.selected.label(),
        "candidates_tried": fold.candidates_tried,
        "fills": fold.out_of_sample.fills,
        "in_sample_fills": fold.in_sample.fills,
        "oos_ending_balance": (
            float(fold.out_of_sample.ending_balance)
            if fold.out_of_sample.ending_balance is not None
            else None
        ),
        "oos_metrics": serialize_metrics(fold.out_of_sample.metrics),
        "window": {
            "out_of_sample_start": window.out_of_sample_start.isoformat(),
            "out_of_sample_end": window.out_of_sample_end.isoformat(),
        },
    }


def serialize_multi_window(report: MultiWindowReport) -> dict[str, Any]:
    fold_count = len(report.folds)
    beats = report.beats_buy_and_hold()
    mean_excess = _excess_return(report.mean_oos_return, report.mean_buy_and_hold_return)
    spread = (
        None
        if report.best_oos_return is None or report.worst_oos_return is None
        else report.best_oos_return - report.worst_oos_return
    )
    paid_rates = tuple(
        rate
        for fold in report.folds
        if fold.out_of_sample.metrics is not None
        and (rate := fold.out_of_sample.metrics.paid_cost_rate) is not None
    )
    mean_paid = sum(paid_rates, Decimal("0")) / Decimal(len(paid_rates)) if paid_rates else None
    breakevens = report.breakeven_costs
    mean_breakeven = report.mean_breakeven_cost
    return {
        "profitable": f"{report.profitable_folds}/{fold_count}",
        "fold_count": fold_count,
        "mean_oos": pct(report.mean_oos_return),
        "mean_oos_raw": decimal_str(report.mean_oos_return),
        "median_oos": pct(report.median_oos_return),
        "worst_oos": pct(report.worst_oos_return),
        "best_oos": pct(report.best_oos_return),
        "spread": pct(spread),
        "spread_raw": decimal_str(spread),
        "buy_and_hold_mean": pct(report.mean_buy_and_hold_return),
        "buy_and_hold_mean_raw": decimal_str(report.mean_buy_and_hold_return),
        "mean_excess_return": pct(mean_excess),
        "mean_excess_return_raw": decimal_str(mean_excess),
        "total_oos_fills": report.total_oos_fills,
        "beats_buy_and_hold": beats,
        "mean_breakeven_cost": _optional_float(mean_breakeven),
        "breakeven_costs": [_optional_float(value) for value in breakevens],
        "mean_paid_cost_rate": _optional_float(mean_paid),
        "cost_headroom": _optional_float(
            None if mean_breakeven is None or mean_paid is None else mean_breakeven - mean_paid
        ),
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
        "trials_total": result.n_trials_total,
        "note": result.note,
    }


def serialize_pbo(report: OverfitAuditReport) -> dict[str, Any]:
    """PBO plus the raw `blocks x configurations` matrix it was computed from.

    The matrix is what makes the verdict inspectable: a single PBO number cannot show
    whether one configuration dominated every block or whether the blocks disagree.
    A `None` cell is the engine reporting no balance for that run — it is kept as
    `None` instead of being flattened to zero, because zero would look like a real
    measured loss.
    """
    best_index = report.best_configuration_index() if report.is_meaningful else None
    return {
        "pbo": decimal_str(report.pbo),
        "blocks": report.blocks,
        "configuration_count": report.configuration_count,
        "split_count": report.split_count,
        "is_meaningful": report.is_meaningful,
        "summary_line": report.summary_line(),
        "deflated_sharpe": serialize_deflated_sharpe(report.deflated_sharpe),
        "labels": list(report.labels),
        "block_returns": [
            [_optional_float(value) for value in row] for row in report.block_returns
        ],
        "best_configuration_index": best_index,
        "best_configuration_label": (
            report.labels[best_index]
            if best_index is not None and best_index < len(report.labels)
            else None
        ),
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
    starting_equity: Decimal | None = None,
) -> dict[str, Any]:
    ts_url = tearsheet_url(tearsheet_path)
    summary: dict[str, Any] = {
        "is_finished": True,
        "is_error": is_error,
        "run_type": run_type,
        "robot": robot,
        "source": source,
        "report_label": report_label,
        "finished_at": (finished_at or datetime.now().astimezone()).isoformat(),
        "tearsheet_url": ts_url,
        "error_message": error_message,
        "starting_equity": _optional_float(starting_equity),
        "multi_window": serialize_multi_window(multi_window) if multi_window else None,
        "walk_forward": (
            serialize_walk_forward(walk_forward, starting_equity=starting_equity)
            if walk_forward
            else None
        ),
        "single_backtest": serialize_backtest(single_backtest) if single_backtest else None,
        "pbo": serialize_pbo(pbo) if pbo else None,
    }
    return summary
