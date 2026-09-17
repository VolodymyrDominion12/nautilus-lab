from __future__ import annotations

import io
import json
import sys
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO, cast

from nautilus_lab.api.experiment_history import archive_job_result
from nautilus_lab.api.serializers import build_job_result, pct, serialize_backtest
from nautilus_lab.api.settings_coerce import apply_setting_overrides
from nautilus_lab.application.dtos import BacktestReport, MultiWindowReport, WalkForwardReport
from nautilus_lab.application.journal import JournalEntry, record_run
from nautilus_lab.application.run_walk_forward import window_return
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.errors import JournalFormatError
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.walk_forward import WalkForwardWindow
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import (
    journal_paths,
    notifier,
    overfit_audit_request,
    overfit_audit_use_case,
    research_request,
    research_use_case,
    settings,
    walk_forward_request,
    walk_forward_use_case,
)


@dataclass(frozen=True, slots=True)
class ResearchJobConfig:
    robot: str = "regime"
    source: str = "catalog"
    bars: int = 3000
    folds: int = 2
    is_fraction: Decimal = Decimal("0.7")
    embargo_bars: int | None = None
    use_optuna: bool = False
    optuna_trials: int = 20
    pbo: bool = False
    pbo_blocks: int = 8
    bar_vpin: bool = False
    stress_slice: str | None = None
    generate_tearsheet: bool = True
    journal: bool = False
    notify: bool = False
    full_sample: bool = False
    catalog_path: str | None = None
    instrument_id: str | None = None
    bar_interval: str | None = None
    is_start: str | None = None
    is_end: str | None = None
    oos_start: str | None = None
    oos_end: str | None = None
    param_overrides: dict[str, str] | None = None
    tearsheet_path: str | None = None


class _Tee(io.TextIOBase):
    """Capture stdout into a buffer while still printing to the original stream."""

    def __init__(self, original: TextIO, buffer: io.StringIO) -> None:
        self._original = original
        self._buffer = buffer

    def write(self, text: str) -> int:
        self._original.write(text)
        self._buffer.write(text)
        return len(text)

    def flush(self) -> None:
        self._original.flush()


def _journal_entry(
    *,
    subject: str,
    gates: str,
    oos_return: Decimal | None = None,
    buy_and_hold: Decimal | None = None,
    fills: int | None = None,
    reason: str = "",
    artifact: str | None = None,
) -> JournalEntry:
    """One journal row, in the same shape the CLI writes.

    Same conventions as `interfaces/cli.py`: `gates` records what was enforced, and the
    OOS column is only ever filled from a real out-of-sample measurement.
    """
    return JournalEntry(
        created_at=datetime.now(UTC),
        source="lab api research",
        subject=subject,
        gates=gates,
        oos_return=oos_return,
        buy_and_hold_return=buy_and_hold,
        fills=fills,
        reason=reason,
        artifact=artifact,
    )


def _record_journal(cfg: Settings, entry: JournalEntry) -> None:
    """Append a finished run to the research journal.

    Bookkeeping must never turn a successful backtest into a failed job: a journal that
    cannot be written (bad marker pair, unwritable path) is reported in the run log and
    the run still reports its numbers.
    """
    try:
        markdown_path, jsonl_path = journal_paths(cfg)
        record_run(markdown_path=markdown_path, jsonl_path=jsonl_path, entry=entry)
    except (OSError, JournalFormatError) as exc:
        print(f"journal_row_failed={exc}")
        return
    print(f"journal_row_appended={markdown_path}")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_window(job: ResearchJobConfig) -> WalkForwardWindow | None:
    dates = (job.is_start, job.is_end, job.oos_start, job.oos_end)
    if not any(dates):
        return None
    if not all(dates):
        msg = "walk-forward dates require is_start, is_end, oos_start, oos_end together"
        raise ValueError(msg)
    return WalkForwardWindow(
        in_sample_start=_parse_utc(job.is_start or ""),
        in_sample_end=_parse_utc(job.is_end or ""),
        out_of_sample_start=_parse_utc(job.oos_start or ""),
        out_of_sample_end=_parse_utc(job.oos_end or ""),
    )


def _apply_config(cfg: Settings, job: ResearchJobConfig) -> Settings:
    updates: dict[str, Any] = {}
    if job.embargo_bars is not None:
        updates["embargo_bars"] = job.embargo_bars
    if job.bar_vpin:
        updates["use_bar_vpin"] = True
    if job.catalog_path:
        updates["catalog_path"] = job.catalog_path
    if job.instrument_id:
        updates["instrument_id"] = job.instrument_id
    if job.bar_interval:
        updates["bar_interval"] = job.bar_interval
    patched = cfg.model_copy(update=updates) if updates else cfg
    return apply_setting_overrides(patched, job.param_overrides or {})


def _print_backtest(report: BacktestReport) -> None:
    print(f"fills={report.fills} positions={report.positions} ending={report.ending_balance}")
    if report.metrics is not None:
        print(
            f"fees_paid={report.metrics.fees_paid} max_dd={report.metrics.max_drawdown} "
            f"turnover={report.metrics.turnover} sharpe_like={report.metrics.sharpe_like}"
        )
    if report.tearsheet_path:
        print(f"tearsheet_saved={report.tearsheet_path}")
    print(report.notes)


def _print_walk_forward(report: WalkForwardReport) -> None:
    print(report.notes)
    print(
        "in-sample (selection only) "
        f"fills={report.in_sample.fills} ending={report.in_sample.ending_balance}"
    )
    print(
        "out-of-sample (report this) "
        f"fills={report.out_of_sample.fills} ending={report.out_of_sample.ending_balance}"
    )
    if report.out_of_sample.tearsheet_path:
        print(f"tearsheet_saved={report.out_of_sample.tearsheet_path}")


def _print_multi_window(report: MultiWindowReport) -> None:
    print(report.notes)
    for fold in report.folds:
        window = fold.window
        print(
            f"fold {fold.index} "
            f"OOS=[{window.out_of_sample_start.isoformat()}, "
            f"{window.out_of_sample_end.isoformat()}) "
            f"fills={fold.out_of_sample.fills} "
            f"return={pct(fold.oos_return)} buy_hold={pct(fold.buy_and_hold_return)} "
            f"selected={fold.selected.label()}"
        )
    print(
        f"out-of-sample aggregate profitable={report.profitable_folds}/{len(report.folds)} "
        f"mean={pct(report.mean_oos_return)} median={pct(report.median_oos_return)} "
        f"worst={pct(report.worst_oos_return)} best={pct(report.best_oos_return)}"
    )
    print(
        f"baseline buy&hold mean={pct(report.mean_buy_and_hold_return)} "
        f"oos_fills={report.total_oos_fills}"
    )
    print(report.summary_line())


def execute_research(
    job: ResearchJobConfig, *, root_dir: Path | None = None
) -> tuple[dict[str, Any], str]:
    """Run a research job and return structured result plus captured log text."""
    buffer = io.StringIO()
    original_stdout = cast(TextIO, sys.stdout)
    sys.stdout = _Tee(original_stdout, buffer)
    result: dict[str, Any]
    robot = RobotName(job.robot)
    finished_at = datetime.now(UTC)
    try:
        cfg = _apply_config(settings(), job)
        if job.folds < 1:
            raise ValueError(f"folds must be >= 1, got {job.folds}")
        # `--journal` forces the write; JOURNAL_ENABLED makes it the default for every run.
        journal_enabled = job.journal or cfg.journal_enabled
        subject = f"{robot.value} {cfg.instrument_id}"
        if job.full_sample and job.use_optuna and job.source == "catalog":
            # The CLI lets --full-sample win and ignores --optuna; doing the opposite
            # silently would make the same two flags mean different things per interface.
            raise ValueError(
                "full_sample and use_optuna are mutually exclusive: full-sample is one "
                "in-sample run, Optuna needs a walk-forward split to select on. Drop one."
            )

        if job.pbo:
            if job.tearsheet_path and job.generate_tearsheet:
                raise ValueError(
                    "--pbo simulates many runs (blocks x configurations), so tearsheet "
                    "has nothing single to draw; use one or the other"
                )
            if job.pbo_blocks < 2:
                raise ValueError(f"pbo_blocks must be >= 2, got {job.pbo_blocks}")
            bar_origin = BarOrigin.SYNTHETIC if job.source == "synthetic" else BarOrigin.CATALOG
            request = overfit_audit_request(
                cfg,
                bar_count=job.bars,
                robot=robot,
                source=bar_origin,
                blocks=job.pbo_blocks,
                stress_slice=job.stress_slice,
            )
            pbo_report = overfit_audit_use_case(cfg).execute(request)
            print(pbo_report.notes)
            print(f"blocks={pbo_report.blocks} configurations={pbo_report.configuration_count}")
            for index, label in enumerate(pbo_report.labels):
                cells = " ".join(pct(row[index]) for row in pbo_report.block_returns)
                print(f"  [{index}] {label} :: {cells}")
            print(pbo_report.summary_line())
            print(pbo_report.deflated_sharpe.summary_line())
            result = build_job_result(
                run_type="pbo",
                robot=robot.value,
                source=job.source,
                pbo=pbo_report,
                report_label="PBO/CSCV overfitting audit",
                finished_at=finished_at,
                starting_equity=cfg.starting_equity,
            )
            if job.notify:
                notifier(cfg).notify(f"Overfitting audit complete: {pbo_report.summary_line()}")
            if journal_enabled:
                _record_journal(
                    cfg,
                    _journal_entry(
                        subject=subject,
                        gates=(
                            f"PBO/CSCV blocks={pbo_report.blocks} "
                            f"configurations={pbo_report.configuration_count}"
                        ),
                        reason=pbo_report.summary_line(),
                    ),
                )
            return result, buffer.getvalue()

        bar_origin = BarOrigin.SYNTHETIC if job.source == "synthetic" else BarOrigin.CATALOG
        tearsheet = job.tearsheet_path if job.generate_tearsheet else None
        custom_window = _optional_window(job)

        if job.full_sample and job.source == "catalog" and not job.use_optuna:
            backtest_report = research_use_case(cfg).execute(
                research_request(
                    cfg,
                    bar_count=job.bars,
                    robot=robot,
                    source=BarOrigin.CATALOG,
                    stress_slice=job.stress_slice,
                    tearsheet_path=tearsheet,
                )
            )
            print("full-sample catalog run (in-sample only; not an out-of-sample report)")
            _print_backtest(backtest_report)
            result = build_job_result(
                run_type="full_sample",
                robot=robot.value,
                source=job.source,
                single_backtest=backtest_report,
                tearsheet_path=backtest_report.tearsheet_path,
                report_label="Full-sample catalog run (in-sample only; not an OOS report)",
                finished_at=finished_at,
                starting_equity=cfg.starting_equity,
            )
            if job.notify:
                notifier(cfg).notify(
                    f"Full-sample backtest complete: fills={backtest_report.fills} "
                    f"ending={backtest_report.ending_balance}"
                )
            if journal_enabled:
                _record_journal(
                    cfg,
                    _journal_entry(
                        subject=subject,
                        gates="full-sample catalog (no OOS split)",
                        fills=backtest_report.fills,
                        reason=(
                            "auto: in-sample only; "
                            f"IS return {pct(window_return(backtest_report, cfg.starting_equity))} "
                            "(not an OOS number)"
                        ),
                        artifact=backtest_report.tearsheet_path,
                    ),
                )
            return result, buffer.getvalue()

        if job.source == "synthetic" and not (job.folds > 1 or job.use_optuna or custom_window):
            backtest_report = research_use_case(cfg).execute(
                research_request(
                    cfg,
                    bar_count=job.bars,
                    robot=robot,
                    source=BarOrigin.SYNTHETIC,
                    stress_slice=job.stress_slice,
                    tearsheet_path=tearsheet,
                )
            )
            _print_backtest(backtest_report)
            result = build_job_result(
                run_type="backtest",
                robot=robot.value,
                source=job.source,
                single_backtest=backtest_report,
                tearsheet_path=backtest_report.tearsheet_path,
                report_label="Synthetic smoke backtest (not an OOS report)",
                finished_at=finished_at,
                starting_equity=cfg.starting_equity,
            )
            if job.notify:
                notifier(cfg).notify(
                    f"Synthetic backtest complete: fills={backtest_report.fills} "
                    f"ending={backtest_report.ending_balance}"
                )
            if journal_enabled:
                _record_journal(
                    cfg,
                    _journal_entry(
                        subject=subject,
                        gates="synthetic backtest (no OOS split)",
                        fills=backtest_report.fills,
                        reason=(
                            "auto: in-sample only; "
                            f"IS return {pct(window_return(backtest_report, cfg.starting_equity))} "
                            "(not an OOS number)"
                        ),
                        artifact=backtest_report.tearsheet_path,
                    ),
                )
            return result, buffer.getvalue()

        wf_request = walk_forward_request(
            cfg,
            robot=robot,
            source=bar_origin,
            bar_count=job.bars if job.source == "synthetic" else 0,
            window=custom_window,
            in_sample_fraction=job.is_fraction,
            stress_slice=job.stress_slice,
            tearsheet_path=tearsheet,
            use_optuna=job.use_optuna,
            optuna_trials=job.optuna_trials,
            folds=job.folds,
        )
        use_case = walk_forward_use_case(cfg)

        if job.folds > 1:
            multi = use_case.execute_multi(wf_request)
            _print_multi_window(multi)
            tearsheet_path = None
            for fold in multi.folds:
                if fold.out_of_sample.tearsheet_path:
                    tearsheet_path = fold.out_of_sample.tearsheet_path
                    break
            result = build_job_result(
                run_type="multi_window",
                robot=robot.value,
                source=job.source,
                multi_window=multi,
                tearsheet_path=tearsheet_path,
                report_label="Out-of-sample multi-window walk-forward",
                finished_at=finished_at,
                starting_equity=cfg.starting_equity,
            )
            if job.notify:
                notifier(cfg).notify(f"Multi-window walk-forward complete: {multi.summary_line()}")
            if journal_enabled:
                _record_journal(
                    cfg,
                    _journal_entry(
                        subject=subject,
                        gates=f"walk-forward {job.source} folds={job.folds}",
                        oos_return=multi.mean_oos_return,
                        buy_and_hold=multi.mean_buy_and_hold_return,
                        fills=multi.total_oos_fills,
                        reason=(
                            f"auto: profitable {multi.profitable_folds}/{len(multi.folds)} folds"
                        ),
                        artifact=tearsheet_path,
                    ),
                )
            return result, buffer.getvalue()

        wf = use_case.execute(wf_request)
        _print_walk_forward(wf)
        result = build_job_result(
            run_type="walk_forward",
            robot=robot.value,
            source=job.source,
            walk_forward=wf,
            tearsheet_path=wf.out_of_sample.tearsheet_path,
            report_label="Single-split walk-forward",
            finished_at=finished_at,
            starting_equity=cfg.starting_equity,
        )
        oos_return = window_return(wf.out_of_sample, cfg.starting_equity)
        result["single_backtest"] = serialize_backtest(wf.out_of_sample)
        result["oos_return"] = pct(oos_return)
        result["oos_return_raw"] = str(oos_return) if oos_return is not None else None
        if job.notify:
            notifier(cfg).notify(
                f"Walk-forward complete: OOS fills={wf.out_of_sample.fills} "
                f"ending={wf.out_of_sample.ending_balance}"
            )
        if journal_enabled:
            _record_journal(
                cfg,
                _journal_entry(
                    subject=subject,
                    gates=f"walk-forward {job.source} single split",
                    oos_return=oos_return,
                    fills=wf.out_of_sample.fills,
                    reason="auto: single split; buy&hold not measured",
                    artifact=wf.out_of_sample.tearsheet_path,
                ),
            )
        return result, buffer.getvalue()
    except Exception as exc:
        traceback.print_exc()
        result = build_job_result(
            run_type="error",
            robot=job.robot,
            source=job.source,
            is_error=True,
            error_message=str(exc),
            finished_at=finished_at,
        )
        return result, buffer.getvalue()
    finally:
        sys.stdout = original_stdout


def config_from_job(job: ResearchJobConfig) -> dict[str, Any]:
    """The full job configuration, archived with every run.

    Everything accepted by `POST /api/research` is recorded, not just the handful of
    fields the first dashboard version needed. "Load config" then replays the experiment
    that actually ran: while the stress slice, embargo, Optuna and PBO settings were
    missing from this record, replaying a run silently changed its conditions.
    """
    return {
        "config_version": 2,
        "robot": job.robot,
        "source": job.source,
        "bars": job.bars,
        "folds": job.folds,
        "is_fraction": str(job.is_fraction),
        "embargo_bars": job.embargo_bars,
        "use_optuna": job.use_optuna,
        "optuna_trials": job.optuna_trials,
        "pbo": job.pbo,
        "pbo_blocks": job.pbo_blocks,
        "bar_vpin": job.bar_vpin,
        "stress_slice": job.stress_slice,
        "generate_tearsheet": job.generate_tearsheet,
        "journal": job.journal,
        "notify": job.notify,
        "full_sample": job.full_sample,
        "catalog_path": job.catalog_path,
        "instrument_id": job.instrument_id,
        "bar_interval": job.bar_interval,
        "is_start": job.is_start,
        "is_end": job.is_end,
        "oos_start": job.oos_start,
        "oos_end": job.oos_end,
        "param_overrides": job.param_overrides or {},
    }


def write_job_artifacts(
    result: dict[str, Any],
    log_text: str,
    *,
    reports_dir: Path,
    command_line: str,
    job: ResearchJobConfig | None = None,
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    if job is not None:
        result = {
            **result,
            "config": config_from_job(job),
        }
    log_path = reports_dir / "last_run.log"
    json_path = reports_dir / "last_run.json"
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"Command: {command_line}\nStarted at: {started}\n\n"
    log_path.write_text(header + log_text, encoding="utf-8")
    if not result.get("is_error"):
        log_path.write_text(
            log_path.read_text(encoding="utf-8") + "\nProcess finished with code 0\n",
            encoding="utf-8",
        )
    else:
        log_path.write_text(
            log_path.read_text(encoding="utf-8") + "\nProcess finished with code 1\n",
            encoding="utf-8",
        )
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not result.get("is_error"):
        archive_job_result(
            result, reports_dir=reports_dir, robot=str(result.get("robot", "unknown"))
        )


def load_job_result(reports_dir: Path) -> dict[str, Any] | None:
    json_path = reports_dir / "last_run.json"
    if not json_path.exists():
        return None
    with json_path.open(encoding="utf-8") as handle:
        return cast(dict[str, Any], json.load(handle))


def summary_from_result(result: dict[str, Any] | None) -> dict[str, Any]:
    """Shape consumed by the frontend ResearchLab summary cards."""
    if result is None:
        return {
            "is_finished": False,
            "is_error": False,
            "run_type": None,
            "robot": None,
            "source": None,
            "finished_at": None,
            "config": None,
            "starting_equity": None,
            "tearsheet_url": None,
            "multi_window": None,
            "walk_forward": None,
            "single_backtest": None,
            "pbo": None,
            "raw_summary": None,
        }

    multi = result.get("multi_window")
    single = result.get("single_backtest")
    return {
        "is_finished": bool(result.get("is_finished")),
        "is_error": bool(result.get("is_error")),
        "run_type": result.get("run_type"),
        "robot": result.get("robot"),
        "source": result.get("source"),
        "finished_at": result.get("finished_at"),
        "report_label": result.get("report_label"),
        "config": result.get("config"),
        "starting_equity": result.get("starting_equity"),
        "error_message": result.get("error_message"),
        "tearsheet_url": result.get("tearsheet_url"),
        "multi_window": multi,
        "walk_forward": result.get("walk_forward"),
        "single_backtest": single,
        "pbo": result.get("pbo"),
        "raw_summary": result.get("summary_line") or (multi or {}).get("summary_line"),
    }


def default_tearsheet_path(reports_dir: Path, robot: str) -> str:
    ts = int(datetime.now(UTC).timestamp())
    filename = f"tearsheet_{robot}_{ts}.html"
    return str(reports_dir / filename)
