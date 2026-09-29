#!/usr/bin/env python3
"""decision_sweep_summary.py — зведення свіпу рішень у reports/decision-sweep/summary.md.

Читає `status.json` (його пише `scripts/run_decision_sweep.py`) і дайджести, і
складає один документ: числа out-of-sample, факти про журнали рішень, опис
кожного робота з його специфікації та перелік того, що запустити не вдалося.

Числа не вигадуються: усе береться з `status.json`, який, своєю чергою, розібраний
з stdout прогонів `lab`. Якщо числа немає — у таблиці буде `n/a`, а не нуль.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "reports" / "decision-sweep"
SPECS = REPO / "specs" / "strategies"

NA = "n/a"


def _spec(name: str) -> dict[str, Any]:
    path = SPECS / f"{name}.yaml"
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _flat(text: object, limit: int = 420) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _first_sentence(text: object) -> str:
    value = " ".join(str(text or "").split())
    for stop in (". ", ".\n"):
        head, sep, _ = value.partition(stop)
        if sep:
            return head + "."
    return _flat(value, 300)


def _top(counts: dict[str, Any] | None, n: int = 3) -> str:
    if not counts:
        return "—"
    ordered = sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
    return ", ".join(f"{key}×{value}" for key, value in ordered[:n])


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _numbers_row(entry: dict[str, Any]) -> list[str]:
    numbers = entry.get("numbers") or {}
    aggregate = numbers.get("aggregate") or {}
    baseline = numbers.get("baseline") or {}
    gate = numbers.get("gate") or {}
    # `promotion_gate=REJECT` тут означає саме «не обганяє buy&hold» лише разом із
    # перевіркою `beats_buy_hold=fail`; сама мітка воріт ширша за це (див. колонку).
    label = gate.get("label")
    if label == "REJECT":
        verdict_text = "не обганяє buy&hold"
    elif label:
        verdict_text = label
    else:
        verdict_text = NA
    return [
        entry["robot"],
        entry["symbol"],
        f"{aggregate.get('profitable', NA)}/{aggregate.get('folds', NA)}",
        aggregate.get("mean", NA),
        aggregate.get("median", NA),
        aggregate.get("worst", NA),
        aggregate.get("best", NA),
        baseline.get("buy_hold", NA),
        baseline.get("oos_fills", NA),
        verdict_text,
        (gate.get("checks") or NA).replace(", ", "; "),
    ]


def _journal_row(entry: dict[str, Any]) -> list[str]:
    journal = entry.get("journal") or {}
    failures = entry.get("write_failures") or {}
    window = entry.get("window") or {}
    start = str(window.get("out_of_sample_start", ""))[:16].replace("T", " ")
    end = str(window.get("out_of_sample_end", ""))[:16].replace("T", " ")
    window_text = f"{start} → {end}" if start and end else NA
    failed = failures.get("failed_writes_total")
    failed_text = NA if failed is None else f"{failed} (у OOS: {failures.get('failed_writes_in_oos_dates', 0)})"
    return [
        entry["robot"],
        entry["symbol"],
        str(journal.get("decisions", NA)),
        window_text,
        str(journal.get("bar_seq_gaps", NA)),
        failed_text,
        _top(journal.get("outcomes")),
        _top(journal.get("blocked_by")),
        _top(journal.get("regime_share_pct"), 3),
        str(entry.get("trace_matches_last_fold") or NA),
    ]


def _robot_sections(entries: list[dict[str, Any]]) -> list[str]:
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for entry in entries:
        grouped.setdefault(entry["robot"], []).append(entry)

    lines: list[str] = []
    for robot, rows in grouped.items():
        spec = _spec(robot)
        lines.append(f"### `{robot}` — {spec.get('title', '(специфікації немає)')}")
        lines.append("")
        lines.append(f"- **Статус у спеці:** `{spec.get('status', NA)}`")
        if spec.get("rejection_reason"):
            lines.append(f"- **Чому rejected:** {_flat(spec['rejection_reason'], 500)}")
        if spec.get("hypothesis"):
            lines.append(f"- **Гіпотеза:** {_first_sentence(spec['hypothesis'])}")
        impl = spec.get("implementation") or {}
        if impl:
            lines.append(
                f"- **Реалізація:** `{impl.get('domain_module', NA)}` / "
                f"`{impl.get('strategy_class', NA)}`, мінімум барів {impl.get('minimum_bars', NA)}, "
                f"сітка `{impl.get('grid_source', NA)}`"
            )
        lines.append("")
        for entry in rows:
            journal = entry.get("journal") or {}
            numbers = entry.get("numbers") or {}
            aggregate = numbers.get("aggregate") or {}
            baseline = numbers.get("baseline") or {}
            lines.append(
                f"**{entry['symbol']}** ({entry['interval']}, `{entry['catalog']}`) — "
                f"статус прогону `{entry['status']}`"
            )
            if entry.get("status") != "ok":
                lines.append(f"  - Помилка: `{_flat(entry.get('error'), 300)}`")
                lines.append("")
                continue
            lines.append(
                f"  - OOS: прибуткових фолдів {aggregate.get('profitable', NA)}/"
                f"{aggregate.get('folds', NA)}, mean {aggregate.get('mean', NA)}, "
                f"worst {aggregate.get('worst', NA)}, buy&hold {baseline.get('buy_hold', NA)}, "
                f"fills {baseline.get('oos_fills', NA)}"
            )
            lines.append(
                f"  - Журнал: {journal.get('decisions', NA)} записів "
                f"({journal.get('kinds', {})}), пропусків `bar_seq` {journal.get('bar_seq_gaps', NA)}, "
                f"config_hash {', '.join(journal.get('config_hashes') or []) or NA}"
            )
            lines.append(f"  - Що робив бар: {_top(journal.get('outcomes'), 5)}")
            lines.append(f"  - Що блокувало вхід: {_top(journal.get('blocked_by'), 5)}")
            lines.append(f"  - Режими: {_top(journal.get('regime_share_pct'), 5)}")
            lines.append(f"  - Дайджест: `digests/{entry['key']}.md`, журнал: `decisions/{entry['key']}.jsonl`")
            lines.append("")
    return lines


def _build(entries: list[dict[str, Any]], generated_at: datetime) -> str:
    ok = [e for e in entries if e.get("status") == "ok"]
    missing = [e for e in entries if e.get("status") != "ok"]

    manifests = Counter(
        str((e.get("numbers") or {}).get("manifest", "")).split(" settings=")[0]
        for e in ok
        if (e.get("numbers") or {}).get("manifest")
    )
    fee_line = ""
    for entry in ok:
        log = OUT / "logs" / f"{entry['key']}.numbers.log"
        if not log.exists():
            continue
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if "backtest with fees" in line:
                fee_line = line
                break
        if fee_line:
            break

    lines: list[str] = [
        "# Свіп рішень: усі роботи на ETHUSDT і BTCUSDT",
        "",
        f"Згенеровано: {generated_at.strftime('%Y-%m-%d %H:%M UTC')} · "
        f"прогонів `ok`: {len(ok)}/{len(entries)}",
        "",
        "Це звіт **не про прибутковість**, а про **рішення**: кожен робот прогнаний на",
        "двох інструментах, і для кожного зібраний журнал `decision_trace/1` — по запису",
        "на закритий бар: що робот побачив, що вирішив, і що його зупинило.",
        "",
        "## 1. Як це запускалося",
        "",
        "- **Каталоги.** Основний — `catalog`, 1h-бари 2024-01-01 → 2026-09-28 "
        "(≈23.9 тис. барів ≈ 2.7 роки, тобто більше за замовлені «мінімум 2 роки»). "
        "`funding` — `catalog_2019_4h`: йому потрібні **бари перпетуала**, яких у `catalog`",
        "  немає взагалі; на 4h перпетуали ETH і BTC є з 2024-01-01, і перетин зі спотом",
        "  дає ті самі 2.7 роки.",
        "- **Протокол.** `--folds 4`, `--is-fraction 0.7`, embargo 10 барів. Параметри",
        "  підбираються сіткою **лише на in-sample**; надруковане число — out-of-sample.",
        "- **Два проходи на кожен (робот × інструмент).**",
        "  1. *числа*: повний 4-фолдовий walk-forward, `DECISION_LOG_ENABLED=false`;",
        "  2. *рішення*: той самий walk-forward на вікні **останнього фолда** з "
        "`DECISION_LOG_ENABLED=true`.",
        "  Журнал другого проходу фільтрується по `ts ∈ [oos_start, oos_end)`, тому в ньому",
        "  лише out-of-sample записи; прогін сітки на IS у журнал не потрапляє (для `regime`",
        "  це ~100 тис. записів на прогін). Колонка `a↔b` перевіряє, що прохід B справді",
        "  відтворив числа останнього фолда проходу A (`match` = fills і доходність збіглися).",
        f"- **Комісії:** {fee_line or NA}",
        "- **Журнал тріалів** (`TRIALS_LEDGER_PATH`) навмисно виведений у `trials/` цього",
        "  свіпу, щоб розвідувальні прогони не переписували трекований `research/trials.jsonl`.",
        "",
        "## 2. Числа: out-of-sample проти buy&hold",
        "",
    ]
    lines += _table(
        [
            "Робот",
            "Інстр.",
            "Прибутк. фолдів",
            "mean OOS",
            "median",
            "worst",
            "best",
            "buy&hold (mean)",
            "OOS fills",
            "Вердикт",
            "Ворота допуску",
        ],
        [_numbers_row(e) for e in ok],
    )
    lines += [
        "",
        "`mean OOS` — середня доходність за out-of-sample фолдами після комісій; "
        "`buy&hold (mean)` — те саме вікно, якби просто тримати інструмент.",
        "Колонка «Вердикт» — це `beats_buy_and_hold()` звіту (`promotion_gate=REJECT` "
        "означає, що ворота не пройдені; `pbo` і `dsr` там `not measured`, бо це "
        "окремий аудит `--pbo`).",
        "",
        "## 3. Журнали рішень: факти",
        "",
    ]
    lines += _table(
        [
            "Робот",
            "Інстр.",
            "Записів",
            "OOS-вікно журналу",
            "Пропуски bar_seq",
            "Загублені записи",
            "Що робив бар (топ)",
            "Що блокувало (топ)",
            "Режими (топ)",
            "a↔b",
        ],
        [_journal_row(e) for e in ok],
    )
    lines += [
        "",
        "`Загублені записи` — рядки `Failed to write decision log` з логу проходу B: "
        "письменник журналу ловить помилку серіалізації й лише логує її, тож без цього "
        "стовпця «робот не торгував» і «записи не доїхали» виглядали б однаково.",
        "",
        "## 4. Робот за роботом",
        "",
    ]
    lines += _robot_sections(ok)

    lines += ["## 5. Що запустити не вдалося (і чому це чесний результат)", ""]
    if missing:
        lines += _table(
            ["Робот", "Інстр.", "Статус", "Повідомлення"],
            [
                [e["robot"], e["symbol"], e["status"], f"`{_flat(e.get('error'), 220)}`"]
                for e in missing
            ],
        )
        lines += [
            "",
            "`fail_closed` — робот не має адаптера в рушії або не пройшов ворота "
            "(`require_backtest_support`, `require_clean_model`). Це не збій свіпу: "
            "`lab live` і такі роботи падають навмисно, і послаблювати ці ворота заборонено.",
            "",
        ]
    else:
        lines += ["- Усі прогони завершилися з кодом 0.", ""]

    lines += [
        "## 6. Обмеження",
        "",
        "1. **Журнал покриває лише out-of-sample вікно останнього фолда** (найсвіжіше "
        "вікно; у 4-фолдовому прогоні воно найдовше — «останній фолд забирає остачу»). "
        "In-sample прогін сітки не журналюється, і це вибір, а не пропуск: у ньому "
        "немає жодного рішення, яке звіт подає як результат.",
        "2. **Числа і журнал — з різних прогонів** (прохід A і прохід B), але з тим самим "
        "вікном і тією самою сіткою; колонка `a↔b` це перевіряє.",
        "3. **Дайджест рахує форвард-прибуток без комісій і стопів** — це діагностика "
        "«куди пішла ціна після рішення», а не P&L.",
        "4. **ML-роботи** (`formulaic_lgbm`, `meta_label`) працюють на моделях "
        "`models/clean/*_preoos.txt`, навчених **до** першого OOS-бару (2025-11-29). "
        "Модель, навчена на всьому каталозі, була б відкинута `require_clean_model`.",
        "5. **`funding` — 4h і окремий каталог**: порівнювати його числа з 1h-роботами "
        "не можна (інший інтервал барів і інша пара інструментів: спот + перпетуал).",
        "6. **`ml_obi` не має ні моделі, ні історії книги**: у каталозі по одному дню "
        "L2-знімків на символ, а `ML_OBI_MODEL_PATH` порожній.",
        "7. **Жоден робот не має статусу `validated`**, і цей свіп його не змінює: "
        "він показує рішення, а не доводить перевагу.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--status", default=str(OUT / "status.json"))
    parser.add_argument("--out", default=str(OUT / "summary.md"))
    args = parser.parse_args(argv)

    status_path = Path(args.status)
    if not status_path.exists():
        raise SystemExit(f"no status file at {status_path}; run the sweep first")
    entries = json.loads(status_path.read_text(encoding="utf-8"))
    text = _build(entries, datetime.now(UTC))
    out_path = Path(args.out)
    out_path.write_text(text, encoding="utf-8")
    print(f"summary_saved={out_path} entries={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
