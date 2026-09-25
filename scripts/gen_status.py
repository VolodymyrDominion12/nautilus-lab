"""`docs/STATUS.md`: the one status table, generated from the code and the specs.

    uv run python scripts/gen_status.py           # rewrite docs/STATUS.md
    uv run python scripts/gen_status.py --check   # exit 1 when it is stale

Why (docs/27 E-2.8, §3.9): the state of every robot used to be restated by hand in
docs/21, docs/22 and docs/README — five to seven tables per change, and they drifted.
The promotion thresholds drifted too: docs/21 §10 said folds >= 4 and PBO < 0.25 while
`application/promotion_gate.py` enforced 6 and 0.3. Here every cell is read from where
the behaviour actually lives:

* spec status, evidence and reasons  -> `specs/strategies/*.yaml`, `specs/components/*.yaml`
* what the backtest can run          -> `domain.regime.BACKTEST_WIRED_ROBOTS`
* tick-level filters                 -> `TICK_VPIN_ROBOTS`, `HAWKES_ROBOTS`
* batch paper / live paper terminal  -> `PAPER_SUPPORTED_ROBOTS`, `LIVE_PAPER_ROBOTS`
* promotion gate thresholds          -> `application.promotion_gate.GateCriteria`

`tests/unit/test_status_doc.py` fails when the committed file is stale and when a spec
and the code disagree (a spec that claims a backtest adapter the code does not have).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from nautilus_lab.api.paper_streamer import LIVE_PAPER_ROBOTS
from nautilus_lab.application.promotion_gate import GateCriteria
from nautilus_lab.application.run_paper import PAPER_SUPPORTED_ROBOTS
from nautilus_lab.domain.regime import (
    BACKTEST_WIRED_ROBOTS,
    HAWKES_ROBOTS,
    TICK_VPIN_ROBOTS,
    RobotName,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "STATUS.md"
SPECS = ROOT / "specs"

YES, NO = "так", "—"

#: What each gate threshold means, in the words the research docs use.
GATE_TEXT: dict[str, str] = {
    "min_folds": "ковзних walk-forward фолдів, не менше",
    "min_profitable_share": "частка OOS-фолдів у плюсі після комісій, не менше",
    "min_oos_fills": "OOS-угод у сумі по фолдах, не менше",
    "max_pbo": "ймовірність перенавчання (PBO, CSCV), не більше",
    "min_dsr": "дефльований Шарп (DSR як імовірність; 0.95 = p ≤ 0.05), не менше",
}


def load_specs(kind: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in sorted((SPECS / kind).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("name"):
            data["_file"] = f"specs/{kind}/{path.name}"
            specs.append(data)
    return specs


def _first_sentence(text: object, limit: int = 140) -> str:
    """One line for a table cell: the first sentence, cut at `limit` characters."""
    flat = " ".join(str(text or "").split())
    for stop in (". ", "; "):
        if stop in flat:
            flat = flat.split(stop, 1)[0] + "."
            break
    flat = flat.replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _mark(flag: bool) -> str:
    return YES if flag else NO


def _evidence(spec: Mapping[str, Any]) -> str:
    evidence = spec.get("evidence") or {}
    if not evidence.get("measured"):
        return "не виміряно"
    beats = evidence.get("beats_buy_hold")
    if beats is True:
        return "виміряно: **обганяє** buy&hold"
    if beats is False:
        return "виміряно: не обганяє buy&hold"
    return "виміряно"


def _reason(spec: Mapping[str, Any]) -> str:
    """Why a closed or blocked robot is where it is; for the rest, what it is."""
    key = {"rejected": "rejection_reason", "blocked": "blocked_reason"}.get(
        str(spec.get("status", ""))
    )
    if key and spec.get(key):
        return _first_sentence(spec[key])
    return _first_sentence(spec.get("title", ""))


def discrepancies(strategies: Iterable[Mapping[str, Any]]) -> list[str]:
    """Places where a spec and the code say different things. Empty = consistent."""
    problems: list[str] = []
    by_name = {str(spec["name"]): spec for spec in strategies}
    problems.extend(
        f"{robot.value}: у коді є робот, але немає специфікації"
        for robot in RobotName
        if robot.value not in by_name
    )
    known = {robot.value for robot in RobotName}
    for name, spec in by_name.items():
        if name not in known:
            problems.append(f"{name}: є специфікація, але немає `RobotName`")
            continue
        claimed = bool((spec.get("implementation") or {}).get("wired_in_backtest"))
        wired = RobotName(name) in BACKTEST_WIRED_ROBOTS
        if claimed != wired:
            problems.append(
                f"{name}: spec `wired_in_backtest: {str(claimed).lower()}`, "
                f"а `BACKTEST_WIRED_ROBOTS` каже {'так' if wired else 'ні'}"
            )
        if spec.get("status") == "validated" and not (spec.get("evidence") or {}).get(
            "beats_buy_hold"
        ):
            problems.append(f"{name}: status validated без виміру, що обганяє buy&hold")
    return problems


def _robot_table(strategies: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Робот | Статус spec | Бектест | Адаптер | Tick VPIN | Hawkes | Paper (батч) "
        "| Live paper | Вимір | Причина / суть |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    order = {"validated": 0, "candidate": 1, "blocked": 2, "rejected": 3}
    for spec in sorted(strategies, key=lambda s: (order.get(s.get("status", ""), 9), s["name"])):
        name = str(spec["name"])
        robot = RobotName(name) if name in {r.value for r in RobotName} else None
        impl = spec.get("implementation") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    f"[`{name}`](../{spec['_file']})",
                    str(spec.get("status", "?")),
                    _mark(robot in BACKTEST_WIRED_ROBOTS),
                    f"`{impl.get('backtest_adapter') or 'none'}`",
                    _mark(robot in TICK_VPIN_ROBOTS),
                    _mark(robot in HAWKES_ROBOTS),
                    _mark(robot in PAPER_SUPPORTED_ROBOTS),
                    _mark(name in LIVE_PAPER_ROBOTS),
                    _evidence(spec),
                    _reason(spec),
                ]
            )
            + " |"
        )
    extra = sorted(LIVE_PAPER_ROBOTS - {robot.value for robot in RobotName})
    if extra:
        lines.append("")
        lines.append(
            "Лише в live paper (еталони, не стратегії): "
            + ", ".join(f"`{name}`" for name in extra)
            + "."
        )
    return lines


def _gate_table() -> list[str]:
    criteria = GateCriteria()
    lines = ["| Поріг | Значення | Що означає |", "|---|---|---|"]
    for field in dataclasses.fields(criteria):
        value = getattr(criteria, field.name)
        shown = f"{value * 100:.0f}%" if field.name.endswith("_share") else str(value)
        if isinstance(value, Decimal) and not field.name.endswith("_share"):
            shown = format(value.normalize(), "f")
        lines.append(f"| `{field.name}` | {shown} | {GATE_TEXT.get(field.name, '')} |")
    return lines


def _component_table(components: list[dict[str, Any]]) -> list[str]:
    return [
        "| Компонент | Статус | Суть |",
        "|---|---|---|",
        *(
            f"| [`{spec['name']}`](../{spec['_file']}) | {spec.get('status', '?')} "
            f"| {_first_sentence(spec.get('title', ''))} |"
            for spec in components
        ),
    ]


def render() -> str:
    strategies = load_specs("strategies")
    components = load_specs("components")
    problems = discrepancies(strategies)
    out = [
        "# Стан роботів і гейтів",
        "",
        "<!-- Згенеровано scripts/gen_status.py. Не редагувати вручну: змінити код або",
        "     spec і виконати `uv run python scripts/gen_status.py`.",
        "     tests/unit/test_status_doc.py падає, поки файл застарілий. -->",
        "",
        "Єдина таблиця стану (docs/27 E-2.8). Кожна клітинка прочитана з коду або зі",
        "специфікації, тож розійтися з ними вона не може; docs/21, docs/22 і docs/README",
        "посилаються сюди замість того, щоб переписувати статуси.",
        "",
        "## Роботи",
        "",
        *_robot_table(strategies),
        "",
        "**Бектест** — робот є в `BACKTEST_WIRED_ROBOTS` (інакше він fail-closed, а не",
        "підмінюється іншим). **Paper (батч)** — `lab paper`; **Live paper** — термінал",
        "дашборду. **Вимір** — `evidence` зі spec: «не обганяє» означає «не доведено», а",
        "не «закрито»; закрита гіпотеза має статус `rejected`.",
        "",
        "## Гейт просування (research → paper)",
        "",
        "Джерело — `GateCriteria` в `src/nautilus_lab/application/promotion_gate.py`;",
        "пороги зафіксовані до будь-якого прогону",
        "([ADR 0003](adr/0003-porohy-heita-z-kodu.md)). Робот проходить, лише коли кожна",
        "перевірка виміряна й пройдена: невиміряне ніколи не читається як «так».",
        "",
        *_gate_table(),
        "",
        "Додатково до гейта, поки без машинної перевірки (docs/21 §10): поріг",
        "беззбитковості > сплачені витрати + 5 bps і жодного маржин-колу чи стоп-ауту",
        "на кризових слайсах `covid2020` та `ftx2022`.",
        "",
        "## Компоненти",
        "",
        *_component_table(components),
        "",
        "## Розбіжності spec ↔ код",
        "",
        *(
            [f"- {problem}" for problem in problems]
            if problems
            else ["Немає: кожна специфікація каже те саме, що код."]
        ),
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--check", action="store_true", help="fail when the file is stale")
    args = parser.parse_args(argv)
    text = render()
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
    if args.check:
        if current != text:
            print(f"{OUTPUT} is stale: run `uv run python scripts/gen_status.py`", file=sys.stderr)
            return 1
        print(f"{OUTPUT.name} is up to date")
        return 0
    if current != text:
        OUTPUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUTPUT}")
    else:
        print(f"{OUTPUT.name} unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
