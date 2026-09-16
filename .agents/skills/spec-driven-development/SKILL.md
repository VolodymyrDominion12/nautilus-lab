---
name: spec-driven-development
description: Протокол Spec-Driven Development для nautilus-lab — специфікація пишеться й оновлюється ПЕРЕД зміною коду робота, а валідатор і тести звіряють спеку з кодом. Використовувати при додаванні нового робота, зміні логіки чи параметрів існуючого, зміні сітки підбору, а також коли треба зрозуміти, які роботи підключені до бектесту, а які зобов'язані падати fail closed.
whenToUse: Будь-яка зміна поведінки робота або його параметрів. Для правок, що не змінюють логіку (коментарі, рефакторинг без зміни поведінки), не потрібно.
---

# Spec-Driven Development у nautilus-lab

## Принцип

> **Специфікація — до коду.** Змінюєш поведінку робота — спершу оновлюєш
> `specs/strategies/<robot>.yaml`, потім код. Валідатор і тести перевіряють,
> що вони не розійшлися.

Навіщо це тут, а не «для галочки»: специфікація, яка розійшлася з кодом, гірша
за відсутню — вона впевнено бреше. У цьому проєкті це вже траплялося: `docs/05`
і `docs/10` стверджували, що до рушія підключено 3 роботи, коли в коді їх 5.

## Структура

```
specs/
├── README.md
├── _schema.yaml              ← ЩО перевіряється (мета-схема). Не чіпай без причини.
├── _validator.py             ← ЯК перевіряється. Одна реалізація для CLI і тестів.
├── strategies/
│   ├── regime.yaml           ← ЕТАЛОН. Копіюй його структуру.
│   └── <robot>.yaml          ← по одній на кожне значення RobotName
└── components/
    └── <component>.yaml      ← наскрізні механізми (ризик, walk-forward, ...)
tests/unit/test_specs.py      ← та сама перевірка + покриття, у pytest
```

Запуск:

```bash
.venv/bin/python specs/_validator.py              # усі спеки
.venv/bin/python specs/_validator.py regime       # одна
.venv/bin/python specs/_validator.py --quiet      # лише підсумок
uv run pytest tests/unit/test_specs.py -v         # те саме + покриття
```

## Що саме перевіряється проти коду

Не «чи гарно написано», а чи не розійшлося:

| Поле спеки | Звідки береться істина |
|---|---|
| `name` | значення `RobotName` (`domain/regime.py`) |
| `implementation.wired_in_backtest` | членство в `BACKTEST_WIRED_ROBOTS` |
| `implementation.minimum_bars` | `minimum_bars()` (`application/run_research_backtest.py`) |
| `implementation.grid_source` | наявність гілки в `application/param_grid.py` |
| `implementation.domain_module` | файл або тека існує |
| `implementation.strategy_class` | клас існує в доменному модулі **або** в модулі адаптера |
| `params[].env` | поле класу `Settings` (ім'я у верхньому регістрі) |
| `component.invariants_enforced[].verified_by` | тест справді існує (`файл::функція`) |

Плюс **покриття**: для кожного `RobotName` мусить бути спека. Додав робота —
валідатор і `test_every_robot_has_a_spec` падають, доки спеки немає. Це навмисно.

## `grid_source`: найпідступніша пастка проєкту

`param_grid.py` має гілки лише для `pairs`, `vpin_momentum`, `formulaic_lgbm`,
`ema`. **Усі інші** роботи тихо провалюються в останній блок — сітку `regime`
(`donchian_period` × `bb_k`). Тобто новий робот без власної гілки підбирає
параметри **чужої** стратегії й виглядає так, ніби працює.

Тому поле обов'язкове:

- `explicit` — у `param_grid.py` **є** гілка для цього робота;
- `default_branch` — гілки немає, застосується сітка `regime`.

Валідатор звіряє значення з кодом і падає при розбіжності. Це не формальність:
саме ця перевірка ловить «робота, якого насправді не підбирали».

## Протокол: НОВИЙ РОБОТ

1. **Спека.** Створи `specs/strategies/<name>.yaml` за зразком
   `specs/strategies/regime.yaml`. `status: candidate`, якщо адаптера ще немає —
   `blocked` (див. нижче).
2. **Валідація.** `.venv/bin/python specs/_validator.py <name>` — нуль помилок
   **до** написання коду.
3. **Домен.** `domain/<robot>.py`: `on_bar(bar) -> Signal | None`. Без Nautilus,
   без `.env`, без мережі. Лише закриті бари, лише `Decimal`.
4. **Реєстрація — чотири місця, не одне:**
   - `domain/regime.py` — назва в `RobotName`;
   - `domain/regime.py` — назва в `BACKTEST_WIRED_ROBOTS` (інакше
     `require_backtest_support()` заблокує робота — і це правильно, якщо
     адаптера немає);
   - `application/param_grid.py` — гілка сітки (або свідомо
     `grid_source: default_branch`);
   - `infrastructure/nautilus/signal_strategy.py` — гілка в `_build_robot()`
     (для спредових роботів — `spread_strategy.py`).
5. **Параметри — ланцюг із п'яти місць:** `infrastructure/settings.py` →
   `.env.example` → `application/dtos.py` (`BacktestRequest`, `SelectedParams`,
   `apply_selected()`) → `interfaces/composition.py` → `backtest_runner.py`.
   Забув хоч одне — параметр не доїде до рушія.
6. **`minimum_bars`**, якщо роботу треба більше барів на розігрів
   (`application/run_research_backtest.py`).
7. **Онови спеку** під фактичні `grid`, `minimum_bars`, `grid_source`.
8. **Тести:** `.venv/bin/python specs/_validator.py <name>` і
   `uv run pytest tests/ -q`.

## Протокол: ЗМІНА ІСНУЮЧОГО РОБОТА

| Що змінюється | Що змінити в спеці |
|---|---|
| Логіка сигналу | `hypothesis`, `edge_conditions`, `version` (minor bump) |
| Нові/змінені параметри | `params[]` (і `grid`, якщо входить у сітку) |
| Зміна сітки в `param_grid.py` | `params[].grid` — обов'язково |
| З'явилась гілка сітки | `grid_source: default_branch` → `explicit` |
| Змінився мінімум барів | `implementation.minimum_bars` |
| Робота підключили до рушія | `wired_in_backtest: true`, `status: blocked` → `candidate` |
| Є вимір OOS з перевагою над buy&hold | `status: validated` + заповнений `evidence` |
| Виміряно, переваги немає | `status: rejected` + `rejection_reason` з числами |
| Гіпотезу закрито назавжди | `status: rejected` (а не `candidate`) |

## Статуси: що вони означають

| Статус | Значення | Обов'язково |
|---|---|---|
| `candidate` | код є, **перевага не доведена** (вимір може бути відсутнім, а може бути й без переваги) | `edge_conditions` (≥2), `implementation`, `params` |
| `validated` | **виміряно перевагу**: OOS обганяє buy&hold за той самий період | ≥3 `edge_conditions`, `evidence.measured: true`, `beats_buy_hold: true` |
| `rejected` | виміряно, переваги немає — гіпотезу закрито | `rejection_reason` з числами |
| `blocked` | є доменний код, **немає адаптера виконання**; мусить падати fail closed | `blocked_reason`, `implementation` |

**`candidate` ≠ `rejected`.** Різниця не в тому, чи є вимір, а в тому, чи
закрито гіпотезу:

- `candidate` з `evidence.measured: true, beats_buy_hold: false` означає
  «виміряно, переваги не видно — але гіпотеза жива» (лишились неперевірені
  змінні: інший символ, таймфрейм, режим, пороги). Саме такий стан у більшості
  роботів цього проєкту.
- `rejected` означає «гіпотезу закрито, більше не повертаємось» — і вимагає
  `rejection_reason` з числами.

Плутанина між ними або передчасно ховає живого робота, або змушує нескінченно
повертатися до мертвої ідеї.

**Станом на зараз жоден робот не має статусу `validated`.** Це не недогляд, а
задокументований результат проєкту: за `README.md` і `docs/05` жоден із роботів
не обганяє buy&hold. Специфікація тут — спосіб зробити цей факт видимим, а не
сховати його.

## `blocked` — окремий випадок, і він важливий

Роботи `funding`, `ml_obi`, `glft`, `tri_scan` існують як доменні будівельні
блоки, але **адаптера виконання в бектесті не мають**. Правило проєкту:
такий робот зобов'язаний **упасти**, а не тихо підмінитись іншим —
`require_backtest_support()` кидає помилку зі списком підключених.

Тому в спеці `blocked`:

- `backtest_adapter: none`, `wired_in_backtest: false`,
  `invariants.fail_closed_without_adapter: true`;
- `blocked_reason` — **конкретно чого не хватає** (адаптер? гілка сітки? дані,
  яких у лабораторії немає: історія funding, стакан, живі котирування трьох ніг?).

«Ще не реалізовано» — не причина. Причина: «немає даних стакана за історію,
а без них OBI не порахувати».

## Специфікації компонентів

`specs/components/` описують наскрізні механізми (ризик, walk-forward, аудит
перенавчання, режими виконання). Головне правило там:

> **Інваріант без тесту — це твердження, а не гарантія.**

Тому кожен інваріант називає `enforced_by` (файл, який його забезпечує) і
`verified_by` (тест, який його доводить). Якщо тесту справді немає — пишеться
`test_missing_reason`, і валідатор дає **попередження** замість помилки.
Прогалину треба бачити, а не ховати.

## Чекліст завершення

- [ ] `specs/strategies/<robot>.yaml` створено або оновлено **до** коду
- [ ] `parameters`/`grid`/`minimum_bars`/`grid_source` збігаються з кодом
- [ ] `.venv/bin/python specs/_validator.py <robot>` — нуль помилок
- [ ] `uv run pytest tests/unit/test_specs.py -q` — зелено
- [ ] `uv run pytest tests/ -q` — зелено
- [ ] Статус відображає **реальність** (не «хочу, щоб було validated»)
