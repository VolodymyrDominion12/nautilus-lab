#!/usr/bin/env python3
# =============================================================================
#  _validator.py — перевірка специфікацій проти КОДУ
# =============================================================================
#  Запуск:
#      .venv/bin/python specs/_validator.py             # усі спеки
#      .venv/bin/python specs/_validator.py regime      # одна
#      .venv/bin/python specs/_validator.py --quiet     # тільки підсумок
#
#  ЧОМУ ЦЕ НЕ ПРОСТО YAML-СХЕМА:
#  Схема перевіряє, що спека «добре написана». Але спека, яка розійшлася з
#  кодом, — гірша за відсутню: вона впевнено бреше. Тому кожне поле, яке можна
#  звірити з кодом, тут ЗВІРЯЄТЬСЯ:
#
#      spec.name                    == значення RobotName
#      implementation.wired_...     == членство в BACKTEST_WIRED_ROBOTS
#      implementation.minimum_bars  == minimum_bars(robot)
#      implementation.grid_source   == наявність гілки в param_grid.py
#      domain_module / strategy_class / params[].env  — існують
#      component.invariants[].verified_by — тест справді існує
#
#  І ще одне: покриття. Кожен RobotName мусить мати спеку. Додав робота —
#  валідатор падає, доки не з'явиться спека. Це навмисно.
#
#  РЕАЛІЗАЦІЯ БЕЗ ІМПОРТУ ПРОЄКТУ:
#  Усе читається через ast — без import nautilus_lab. Причини дві: (1) валідатор
#  не має побічних ефектів (не читає .env, не тягне nautilus_trader); (2) він
#  працює навіть якщо залежності зламані — а саме тоді перевірка найпотрібніша.
#
#  Якщо форма коду зміниться так, що розбір не вдасться, валідатор ГОЛОСНО
#  скаже «не можу розібрати» — це правильна відмова: краще гучна помилка, ніж
#  тихо неправильна перевірка.
# =============================================================================
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = ROOT / "specs"
SCHEMA_PATH = SPECS_DIR / "_schema.yaml"

REGIME_PY = ROOT / "src/nautilus_lab/domain/regime.py"
PARAM_GRID_PY = ROOT / "src/nautilus_lab/application/param_grid.py"
SETTINGS_PY = ROOT / "src/nautilus_lab/infrastructure/settings.py"
RESEARCH_PY = ROOT / "src/nautilus_lab/application/run_research_backtest.py"
WALK_FORWARD_PY = ROOT / "src/nautilus_lab/application/run_walk_forward.py"
DOCS_05_MD = ROOT / "docs/05-roboty.md"

# Адаптер, який рушій реально інстанціює. Клас стратегії може жити або в
# доменному модулі, або в самому адаптері (так зроблено для pairs/спредів) —
# тому шукаємо в обох місцях, а не в одному «правильному».
ADAPTER_MODULES = {
    "signal_strategy": ROOT / "src/nautilus_lab/infrastructure/nautilus/signal_strategy.py",
    "spread_strategy": ROOT / "src/nautilus_lab/infrastructure/nautilus/spread_strategy.py",
}


# ── Збір фактів із коду ──────────────────────────────────────────────────────


@dataclass
class CodeFacts:
    """Те, що вдалось прочитати з коду. Порожнє поле = не розібралось."""

    robot_names: set[str] = field(default_factory=set)
    wired: set[str] = field(default_factory=set)
    minimum_bars: dict[str, int] = field(default_factory=dict)
    minimum_bars_default: int | None = None
    warmup_bars: dict[str, int] = field(default_factory=dict)
    warmup_bars_default: int | None = None
    grid_robots: set[str] = field(default_factory=set)
    setting_fields: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _robot_member(node: ast.AST) -> str | None:
    """`RobotName.REGIME` → 'regime' (значення з StrEnum), інакше None."""
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "RobotName"
    ):
        return node.attr.lower()
    return None


def collect_robot_names(facts: CodeFacts) -> None:
    """Значення enum RobotName (StrEnum → attr.lower() дає значення)."""
    try:
        tree = _parse(REGIME_PY)
    except (OSError, SyntaxError) as exc:
        facts.problems.append(f"не читається {REGIME_PY.relative_to(ROOT)}: {exc}")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RobotName":
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    facts.robot_names.add(stmt.value.value)
            return
    facts.problems.append("у domain/regime.py не знайдено клас RobotName")


def collect_wired(facts: CodeFacts) -> None:
    """Члени BACKTEST_WIRED_ROBOTS.

    Враховуємо ОБИДВІ форми оголошення: `X = ...` (Assign) і
    `X: frozenset[RobotName] = ...` (AnnAssign). У цьому проєкті вжито другу —
    саме на ній перша версія валідатора й спіткнулась.
    """
    try:
        tree = _parse(REGIME_PY)
    except (OSError, SyntaxError) as exc:
        facts.problems.append(f"не читається {REGIME_PY.relative_to(ROOT)}: {exc}")
        return
    target_names: set[str] = set()
    for node in ast.walk(tree):
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            target_names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_names = {node.target.id}
            value = node.value
        if "BACKTEST_WIRED_ROBOTS" not in target_names or value is None:
            continue
        for inner in ast.walk(value):
            member = _robot_member(inner)
            if member:
                facts.wired.add(member)
        return
    facts.problems.append("не знайдено BACKTEST_WIRED_ROBOTS у domain/regime.py")


def _bucketed_ints(path: Path, func_name: str) -> tuple[dict[str, int], int | None] | None:
    """Розібрати «ланцюг порогів по роботах» у функції.

    Вміє дві форми, які реально вжито в проєкті:
        if robot in (RobotName.A, ...): return 150      # minimum_bars()
        if robot is RobotName.A: minimum = 150          # _require_warmup()
    плюс `elif` і завершальний `else` як типове значення.
    Повертає None, якщо форму не розпізнано — краще гучна відмова, ніж тиха.
    """
    try:
        tree = _parse(path)
    except (OSError, SyntaxError):
        return None
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            func = node
            break
    if func is None:
        return None

    def first_int(body: list[ast.stmt]) -> int | None:
        for stmt in body:
            if (
                isinstance(stmt, ast.Return)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, int)
            ):
                return stmt.value.value
            if (
                isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, int)
            ):
                return stmt.value.value
        return None

    found: dict[str, int] = {}
    default: int | None = None
    for stmt in func.body:
        node = stmt
        while isinstance(node, ast.If):
            members = {m for m in (_robot_member(n) for n in ast.walk(node.test)) if m}
            value = first_int(node.body)
            if members and value is not None:
                for member in members:
                    found[member] = value
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                node = node.orelse[0]
                continue
            if node.orelse and not isinstance(node.orelse[0], ast.If):
                value = first_int(node.orelse)
                if value is not None:
                    default = value
            break
    return (found, default) if found else None


def collect_minimum_bars(facts: CodeFacts) -> None:
    """Розбір minimum_bars() — точково під його конкретну форму.

    Форма, яку вміємо читати:
        def minimum_bars(robot):
            if robot in (RobotName.A, RobotName.B): return 150
            if robot is RobotName.C:              return 200
            return 50                     # ← типове значення
    """
    try:
        tree = _parse(RESEARCH_PY)
    except (OSError, SyntaxError) as exc:
        facts.problems.append(f"не читається {RESEARCH_PY.relative_to(ROOT)}: {exc}")
        return
    func = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "minimum_bars":
            func = node
            break
    if func is None:
        facts.problems.append("не знайдено функцію minimum_bars()")
        return

    def literal_return(body: list[ast.stmt]) -> int | None:
        for stmt in body:
            if (
                isinstance(stmt, ast.Return)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, int)
            ):
                return stmt.value.value
        return None

    for stmt in func.body:
        if isinstance(stmt, ast.If):
            value = literal_return(stmt.body)
            members = {m for m in (_robot_member(n) for n in ast.walk(stmt.test)) if m}
            if members and value is not None:
                for member in members:
                    facts.minimum_bars[member] = value
            continue
        if (
            isinstance(stmt, ast.Return)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, int)
        ):
            facts.minimum_bars_default = stmt.value.value
    if not facts.minimum_bars:
        facts.problems.append(
            "не вдалось розібрати minimum_bars() — форма змінилась, онови валідатор"
        )

    # Те саме правило продубльовано в _require_warmup() (walk-forward перевіряє
    # бари на КОЖЕН фолд окремо). Дві копії одного правила розходяться тихо,
    # тому звіряємо їх між собою, а не довіряємо одній.
    walk_forward = _bucketed_ints(WALK_FORWARD_PY, "_require_warmup")
    if walk_forward is None:
        facts.problems.append(
            "не вдалось розібрати _require_warmup() у run_walk_forward.py — "
            "правило мінімуму барів тепер НЕ звіряється між двома місцями"
        )
    else:
        facts.warmup_bars, facts.warmup_bars_default = walk_forward
        drift = {
            robot: (value, facts.warmup_bars.get(robot, facts.warmup_bars_default))
            for robot, value in facts.minimum_bars.items()
            if value != facts.warmup_bars.get(robot, facts.warmup_bars_default)
        }
        if drift:
            facts.problems.append(
                "правило мінімуму барів РОЗІЙШЛОСЬ у двох файлах "
                "(minimum_bars() vs _require_warmup()): "
                + ", ".join(f"{r}: {a} vs {b}" for r, (a, b) in drift.items())
            )


def collect_grid_robots(facts: CodeFacts) -> None:
    """Роботи, для яких у param_grid.py є ВЛАСНА гілка сітки."""
    try:
        tree = _parse(PARAM_GRID_PY)
    except (OSError, SyntaxError) as exc:
        facts.problems.append(f"не читається {PARAM_GRID_PY.relative_to(ROOT)}: {exc}")
        return
    for node in ast.walk(tree):
        member = _robot_member(node)
        if member:
            facts.grid_robots.add(member)
    if not facts.grid_robots:
        facts.problems.append("у param_grid.py не знайдено жодної гілки RobotName.*")


def collect_setting_fields(facts: CodeFacts) -> None:
    """Анотовані поля класу Settings (їхні імена ↔ env-змінні у верхньому регістрі)."""
    try:
        tree = _parse(SETTINGS_PY)
    except (OSError, SyntaxError) as exc:
        facts.problems.append(f"не читається {SETTINGS_PY.relative_to(ROOT)}: {exc}")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    facts.setting_fields.add(stmt.target.id)
            break
    if not facts.setting_fields:
        facts.problems.append("не знайдено поля класу Settings")


def collect_facts() -> CodeFacts:
    facts = CodeFacts()
    collect_robot_names(facts)
    collect_wired(facts)
    collect_minimum_bars(facts)
    collect_grid_robots(facts)
    collect_setting_fields(facts)
    return facts


# ── Хелпери перевірок ────────────────────────────────────────────────────────


def _test_nodes(path: Path) -> set[str]:
    """Імена функцій у файлі тестів (щоб перевірити verified_by)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
    return names


def _classes_in(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return set()
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}


# ── Перевірка однієї спеки ───────────────────────────────────────────────────


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def check_common(spec: dict, name: str, report: Report, schema: dict) -> None:
    for field_name in schema["common"]["required"]:
        if field_name not in spec or spec[field_name] in (None, "", [], {}):
            report.error(f"відсутнє обов'язкове поле: {field_name}")
    if spec.get("name") != name:
        report.error(f"name='{spec.get('name')}' не збігається з іменем файлу '{name}'")
    if not isinstance(spec.get("version"), str):
        report.error('version мусить бути рядком у лапках (напр. "1.0")')


def check_strategy(spec: dict, name: str, report: Report, schema: dict, facts: CodeFacts) -> None:
    st_cfg = schema["strategy"]
    status = spec.get("status")
    if status not in st_cfg["statuses"]:
        report.error(f"невідомий status='{status}' (дозволено: {sorted(st_cfg['statuses'])})")
        return
    status_cfg = st_cfg["statuses"][status]

    for field_name in status_cfg.get("required", []):
        if spec.get(field_name) in (None, "", [], {}):
            report.error(f"status='{status}' вимагає поле: {field_name}")

    conditions = spec.get("edge_conditions") or []
    if len(conditions) < status_cfg.get("min_edge_conditions", 0):
        report.error(
            f"status='{status}' вимагає щонайменше "
            f"{status_cfg['min_edge_conditions']} edge_conditions, є {len(conditions)}"
        )

    # measured: true без команди відтворення — твердження без джерела:
    # reports/ у .gitignore, тож у свіжому клоні доказу не буде.
    evidence_block = spec.get("evidence") or {}
    if evidence_block.get("measured") and not evidence_block.get("reproduce"):
        report.error(
            "evidence.measured: true вимагає evidence.reproduce — команду, якою "
            "цей вимір відтворюється (reports/ у .gitignore, доказ може зникнути)"
        )

    if status_cfg.get("requires_evidence"):
        evidence = spec.get("evidence") or {}
        if not evidence.get("measured"):
            report.error("status='validated' вимагає evidence.measured: true")
        if evidence.get("beats_buy_hold") is not True:
            report.error(
                "status='validated' вимагає evidence.beats_buy_hold: true — "
                "перевага без порівняння з buy&hold не є перевагою"
            )

    # ── інваріанти ──
    invariants = spec.get("invariants") or {}
    for key in schema["strategy"]["invariants"]["required_true"]:
        if invariants.get(key) is not True:
            report.error(f"invariants.{key} мусить бути true")

    # ── звірка з кодом ──
    if facts.robot_names and name not in facts.robot_names:
        report.error(f"'{name}' немає серед значень RobotName у domain/regime.py")

    impl = spec.get("implementation") or {}
    if not impl:
        return

    adapter = impl.get("backtest_adapter")
    allowed = schema["strategy"]["implementation"]["backtest_adapter"]["allowed"]
    if adapter not in allowed:
        report.error(f"backtest_adapter='{adapter}' не з {allowed}")

    wired = impl.get("wired_in_backtest")
    if facts.wired:
        expected_wired = name in facts.wired
        if wired is not expected_wired:
            report.error(
                f"wired_in_backtest={wired}, але '{name}' "
                f"{'є' if expected_wired else 'НЕ є'} у BACKTEST_WIRED_ROBOTS"
            )
    if wired is False and adapter != "none" and status != "blocked":
        report.warn(
            "wired_in_backtest: false, але адаптер вказано — "
            "перевір, чи це справді так (робот мусить падати fail closed)"
        )
    if wired is True and adapter == "none":
        report.error("wired_in_backtest: true несумісне з backtest_adapter: none")

    # minimum_bars
    declared = impl.get("minimum_bars")
    expected = facts.minimum_bars.get(name, facts.minimum_bars_default)
    if declared is not None and expected is not None and declared != expected:
        report.error(
            f"minimum_bars={declared}, але minimum_bars({name}) у коді повертає {expected}"
        )

    # grid_source — пастка «тихо взялась сітка regime»
    grid_source = impl.get("grid_source")
    if grid_source not in ("explicit", "default_branch", None):
        report.error("grid_source мусить бути 'explicit' або 'default_branch'")
    elif grid_source is not None and facts.grid_robots:
        has_branch = name in facts.grid_robots
        if grid_source == "explicit" and not has_branch:
            report.error(
                f"grid_source: explicit, але в param_grid.py немає гілки для '{name}' — "
                "тихо застосується сітка regime"
            )
        if grid_source == "default_branch" and has_branch:
            report.error(f"grid_source: default_branch, але гілка для '{name}' у param_grid.py Є")

    # доменний модуль (файл або тека) і клас стратегії
    module_rel = impl.get("domain_module")
    if module_rel:
        module_path = ROOT / module_rel
        if not module_path.exists():
            report.error(f"domain_module не існує: {module_rel}")
        else:
            cls = impl.get("strategy_class")
            if adapter == "none":
                # Без адаптера класу-стратегії може не бути взагалі: робот
                # існує як доменні будівельні блоки (funding, gltf, tri_scan).
                if cls:
                    report.warn(
                        f"backtest_adapter: none, але вказано strategy_class '{cls}' — "
                        "перевір, чи це справді клас, а не набір функцій"
                    )
            elif not cls:
                report.error("strategy_class обов'язковий, коли є адаптер")
            else:
                search_paths = [module_path] if module_path.is_file() else []
                adapter_path = ADAPTER_MODULES.get(adapter)
                if adapter_path and adapter_path.is_file():
                    search_paths.append(adapter_path)
                if not search_paths:
                    report.warn(
                        f"не вдалось перевірити strategy_class '{cls}': "
                        f"{module_rel} — тека, а модуль адаптера невідомий"
                    )
                elif not any(cls in _classes_in(path) for path in search_paths):
                    where = " або ".join(str(p.relative_to(ROOT)) for p in search_paths)
                    report.error(f"клас '{cls}' не знайдено у {where}")

    # параметри ↔ Settings
    if facts.setting_fields:
        for param in spec.get("params") or []:
            env = param.get("env")
            if not env:
                report.error("у params[] відсутнє поле env (ім'я змінної з Settings)")
                continue
            if env.lower() not in facts.setting_fields:
                report.error(f"params[].env='{env}' немає серед полів Settings")
            if not param.get("grid"):
                # Порожній grid припустимий лише якщо це СВІДОМЕ рішення.
                if param.get("tuned") is False and param.get("note"):
                    report.warn(f"params[{env}]: не підбирається — {param['note']}")
                else:
                    report.error(
                        f"params[{env}].grid порожній: або дай значення сітки, "
                        "або постав tuned: false з note (чому не підбираємо)"
                    )


def check_component(spec: dict, name: str, report: Report, schema: dict, facts: CodeFacts) -> None:
    cfg = schema["component"]
    status = spec.get("status")
    if status not in cfg["statuses"]:
        report.error(f"невідомий status='{status}' (дозволено: {sorted(cfg['statuses'])})")
        return
    status_cfg = cfg["statuses"][status]

    for field_name in status_cfg.get("required", []):
        if spec.get(field_name) in (None, "", [], {}):
            report.error(f"status='{status}' вимагає поле: {field_name}")

    invariants = spec.get("invariants_enforced") or []
    if status_cfg.get("requires_verified_by"):
        if not invariants:
            report.error(f"status='{status}' вимагає непорожній invariants_enforced")
        for item in invariants:
            statement = item.get("statement")
            if not statement:
                report.error("invariants_enforced[] без statement")
                continue
            label = f"«{statement[:48]}…»" if len(statement) > 48 else f"«{statement}»"

            enforced = item.get("enforced_by")
            if not enforced:
                report.error(f"{label}: відсутнє enforced_by")
            elif not (ROOT / enforced).is_file():
                report.error(f"{label}: enforced_by не існує — {enforced}")

            verified = item.get("verified_by")
            if not verified:
                # Тест може бути відсутній — але це треба назвати вголос.
                if item.get("test_missing_reason"):
                    report.warn(f"{label}: тесту немає — {item['test_missing_reason']}")
                else:
                    report.error(
                        f"{label}: потрібне АБО verified_by, АБО test_missing_reason — "
                        "інваріант без тесту це твердження, а не гарантія"
                    )
            else:
                path_part, _, func_part = verified.partition("::")
                test_path = ROOT / path_part
                if not test_path.is_file():
                    report.error(f"{label}: файл тесту не існує — {path_part}")
                elif func_part:
                    func_name = func_part.split("[")[0]
                    if func_name not in _test_nodes(test_path):
                        report.error(f"{label}: у {path_part} немає тесту '{func_name}'")


def check_docs_alignment(facts: CodeFacts) -> list[str]:
    """Звірка таблиці docs/05-roboty.md із BACKTEST_WIRED_ROBOTS та RobotName."""
    errors: list[str] = []
    if not DOCS_05_MD.is_file():
        errors.append(f"{DOCS_05_MD.relative_to(ROOT)} не існує")
        return errors

    content = DOCS_05_MD.read_text(encoding="utf-8")
    table_wired: set[str] = set()
    table_unwired: set[str] = set()

    for line in content.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 3:
            continue
        col_robot = parts[0].strip("` ")
        col_wired = parts[2]
        if col_robot in facts.robot_names:
            if "так" in col_wired or "✅" in col_wired:
                table_wired.add(col_robot)
            elif "ні" in col_wired or "❌" in col_wired:
                table_unwired.add(col_robot)

    missing_from_docs = facts.robot_names - (table_wired | table_unwired)
    if missing_from_docs:
        names_str = ", ".join(sorted(missing_from_docs))
        errors.append(f"у {DOCS_05_MD.relative_to(ROOT)} відсутні роботи: {names_str}")

    if facts.wired and table_wired != facts.wired:
        diff_wired = facts.wired - table_wired
        diff_unwired = table_wired - facts.wired
        if diff_wired:
            wired_str = ", ".join(sorted(diff_wired))
            errors.append(f"{DOCS_05_MD.relative_to(ROOT)} не позначає як підключені: {wired_str}")
        if diff_unwired:
            unwired_str = ", ".join(sorted(diff_unwired))
            errors.append(
                f"{DOCS_05_MD.relative_to(ROOT)} помилково позначає як підключені: {unwired_str}"
            )

    return errors


# ── Основний прогін ──────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    only = [a for a in argv[1:] if not a.startswith("-")]

    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    facts = collect_facts()

    if facts.problems and not quiet:
        print("⚠ Не все вдалось прочитати з коду:")
        for problem in facts.problems:
            print(f"    • {problem}")
        print("  Перевірки, що залежать від цього, пропущено (це гучна відмова, не тиха).\n")

    specs: list[tuple[str, str, dict]] = []
    for kind in ("strategy", "component"):
        directory = SPECS_DIR / schema[kind]["dir"]
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            if path.stem.startswith("_"):
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                print(f"✗ {path.relative_to(ROOT)}: не словник")
                continue
            specs.append((kind, path.stem, data))

    if only:
        specs = [s for s in specs if s[1] in only or f"{schema[s[0]]['dir']}/{s[1]}" in only]

    total_errors = 0
    for kind, name, spec in specs:
        report = Report()
        check_common(spec, name, report, schema)
        if kind == "strategy":
            check_strategy(spec, name, report, schema, facts)
        else:
            check_component(spec, name, report, schema, facts)

        declared_kind = spec.get("kind")
        if declared_kind != kind:
            report.error(f"kind='{declared_kind}' не відповідає теці '{kind}'")

        if report.errors:
            total_errors += len(report.errors)
            print(f"✗ {kind}/{name}")
            for err in report.errors:
                print(f"    • {err}")
        elif not quiet:
            print(f"✓ {kind}/{name}")
        for warning in report.warnings:
            print(f"    ⚠ {name}: {warning}")

    # ── покриття: кожен RobotName мусить мати спеку ──
    covered = {name for kind, name, _ in specs if kind == "strategy"}
    missing = sorted(facts.robot_names - covered)
    if missing:
        total_errors += len(missing)
        print(f"\n✗ Немає специфікацій для роботів: {', '.join(missing)}")
        print("  Додав робота в RobotName — додай і спеку в specs/strategies/.")

    # ── перевірка узгодженості docs/05 з BACKTEST_WIRED_ROBOTS (Sprint S6) ──
    if not only:
        docs_errors = check_docs_alignment(facts)
        if docs_errors:
            total_errors += len(docs_errors)
            print(f"\n✗ {DOCS_05_MD.relative_to(ROOT)}")
            for err in docs_errors:
                print(f"    • {err}")
        elif not quiet:
            print(f"✓ {DOCS_05_MD.relative_to(ROOT)} узгоджено з BACKTEST_WIRED_ROBOTS")

    print()
    if total_errors:
        print(f"❌ {total_errors} помилок у {len(specs)} спеках")
        return 1
    print(f"✅ {len(specs)} спек валідні та узгоджені з кодом")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
