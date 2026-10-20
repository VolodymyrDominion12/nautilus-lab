"""Screen report: JSON for machines, Markdown for the researcher, trials for the ledger."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol

from nautilus_lab.application.alpha.screen import ScreenReport, SignalResult


class TrialLedger(Protocol):
    """Same contract as `application.trial_ledger.TrialLedger`, without its imports.

    That module pulls in the backtest DTOs. The screen only needs `record`, and the
    JSONL ledger satisfies both protocols structurally.
    """

    def record(self, dataset: str, trial_ids: Iterable[str]) -> int: ...


def dataset_key(report: ScreenReport, label: str) -> str:
    """One dataset = one panel, zone and research universe; windows are views of it."""
    return f"alpha-screen|{label}|{report.zone.value}|{','.join(sorted(report.symbols))}"


def record_trials(ledger: TrialLedger | None, report: ScreenReport, label: str) -> int | None:
    """Every non-control signal x horizon is one trial, rejected or not."""
    if ledger is None:
        return None
    trials = (r.trial_id for r in report.results if not r.control)
    return ledger.record(dataset_key(report, label), trials)


def to_payload(report: ScreenReport, label: str) -> dict[str, Any]:
    return {
        "dataset": dataset_key(report, label),
        "zone": report.zone.value,
        "windows": [list(w) for w in report.windows],
        "symbols": list(report.symbols),
        "held_out_symbols": list(report.held_out),
        "bar_minutes": report.bar_minutes,
        "generated_at": report.generated_at,
        "config": asdict(report.config),
        "rows_by_horizon": report.rows_by_horizon,
        "skipped_templates": list(report.skipped),
        "trials_total": report.trials_total,
        "controls_ok": report.controls_ok,
        "notes": list(report.notes),
        "results": [_result_payload(r) for r in report.results],
    }


def _result_payload(result: SignalResult) -> dict[str, Any]:
    data = asdict(result)
    data["trial_id"] = result.trial_id
    data["ic_by_year"] = {str(k): v for k, v in result.ic_by_year.items()}
    data["reasons"] = list(result.reasons)
    return data


def write_report(report: ScreenReport, out_dir: Path, label: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "alpha_screen.json"
    md_path = out_dir / "alpha_screen.md"
    json_path.write_text(
        json.dumps(to_payload(report, label), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    md_path.write_text(render_markdown(report, label), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: ScreenReport, label: str) -> str:
    cfg = report.config
    trials = [r for r in report.results if not r.control]
    lines = [
        f"# Скринінг альфи: {label}, зона {report.zone.value}",
        "",
        f"- Згенеровано: {report.generated_at}",
        f"- Вікна зони: {', '.join(f'{a}..{b}' for a, b in report.windows)}",
        f"- Монети дослідження ({len(report.symbols)}): {', '.join(report.symbols)}",
        f"- Відкладено в holdout: {', '.join(report.held_out) or 'жодної'}",
        f"- Таргет: залишкова доходність (після β·ринок і funding), горизонти у барах "
        f"{', '.join(str(h) for h in cfg.horizons)}",
        f"- Витрати: {cfg.cost_bps:g} bps за одиницю одностороннього обороту; "
        f"поріг breakeven ≥ {cfg.breakeven_multiple * cfg.cost_bps:g} bps",
        f"- Гейт: |t_block| і |perm_z| ≥ {cfg.t_threshold}, q_BH ≤ {cfg.q_threshold}, "
        f"|corr ринок| ≤ {cfg.max_abs_market_corr}, знак стабільний у ≥ "
        f"{cfg.min_year_consistency:.0%} років, net Sharpe > 0 (β-нейтральна книга)",
        f"- Спроб у цьому прогоні: {len(trials)}; усього в ledger для датасету: "
        f"{report.trials_total if report.trials_total is not None else 'не записано'}",
        "- Контролі: "
        + ("OK" if report.controls_ok else "ПРОВАЛ, таблиці нижче не означають нічого"),
        "",
        "Це in-sample вибір на exploration, а не результат. Кандидат іде далі лише через "
        "преєстрацію і walk-forward на validation.",
        "",
    ]
    if report.skipped:
        lines += [f"Пропущено (немає полів у панелі): {', '.join(report.skipped)}", ""]

    candidates = report.candidates
    lines += ["## Кандидати", ""]
    if candidates:
        lines += _table(sorted(candidates, key=lambda r: -abs(r.t_block or 0)))
    else:
        lines.append("Жоден сигнал не пройшов гейт.")
    lines += ["", "## Усі спроби (за |t_block|)", ""]
    lines += _table(sorted(trials, key=lambda r: -abs(r.t_block or 0)))
    lines += ["", "## Контролі", ""]
    lines += _table([r for r in report.results if r.control])
    lines += ["", "## Причини відмови (топ-20)", ""]
    for result in sorted(trials, key=lambda r: -abs(r.t_block or 0))[:20]:
        if result.reasons:
            lines.append(f"- `{result.trial_id}`: {'; '.join(result.reasons)}")
    lines.append("")
    return "\n".join(lines)


def _table(results: list[SignalResult]) -> list[str]:
    head = (
        "| сигнал | сімʼя | h | дати | IC | IR | t_block | perm_z | q | роки | напрям "
        "| SR gross β0 | SR net β0 | оборот/бар | breakeven bps | corr β0 | corr $0 | вердикт |"
    )
    rows = [head, "|" + "---|" * 18]
    for r in results:
        bn, dn = r.book_beta_neutral, r.book
        rows.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} "
            "| {} | {} |".format(
                r.name,
                r.family,
                r.horizon,
                r.dates,
                _f(r.ic_mean, 4),
                _f(r.ic_ir, 3),
                _f(r.t_block, 2),
                _f(r.perm_z, 2),
                _f(r.q_value, 3),
                _f(r.year_consistency, 2, signed=False),
                "+" if r.direction > 0 else "−",
                _f(bn.sharpe_gross, 2),
                _f(bn.sharpe_net, 2),
                _f(bn.turnover, 4, signed=False),
                _f(bn.breakeven_bps, 1),
                _f(bn.market_corr, 2),
                _f(dn.market_corr, 2),
                r.verdict,
            )
        )
    return rows


def _f(value: float | None, digits: int, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
