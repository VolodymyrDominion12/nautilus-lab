# AGENTS.md — інструкції для AI-агентів у nautilus-lab

Поглиблений кукбук команд, пасток і розходжень документації з кодом —
у `.agents/skills/nautilus-lab/SKILL.md`. Цей файл — короткі правила, яких треба
триматись завжди; той — довідник, коли доходить до конкретної команди.

## Про проєкт

Дослідницька лабораторія торгових роботів на **NautilusTrader** (event-driven
рушій Rust + Python). Python ≥ 3.12, менеджер залежностей — `uv`.

**Типовий режим — research / симуляція. `lab live` завжди fail closed.** Адаптера
виконання не існує: це не «ще не налаштовано», а свідомий запобіжник.

Точки входу — CLI `lab` (`src/nautilus_lab/interfaces/cli.py`) і FastAPI-дашборд
(`src/nautilus_lab/api/app.py`, запускається `uvicorn nautilus_lab.api.app:app`).
Обидві збирають ті самі use cases через `interfaces/composition.py` — другого
бектесту в проєкті не існує.

## Правила роботи

1. **In-sample — лише вибір параметрів, ніколи не результат.** Рядок
   `in-sample (selection only)` не можна подавати як досягнення. Звіт — це
   `out-of-sample (report this)`.
2. **Порівнюй із buy&hold за той самий OOS-період.** Плюсове число саме по собі
   не є перевагою; `--folds N≥2` друкує `baseline buy&hold mean=...`.
3. **Не підбирай параметри на OOS.** Перебирати сітку, Optuna, `--is-fraction`,
   `--embargo-bars` можна лише на IS. OOS дивляться один раз для фінальної
   конфігурації.
4. **`--full-sample` і `--synthetic` — не OOS-звіт.** Синтетика взагалі лише для
   smoke-тестів: вона дає артефакти на кшталт +3000%, це не перевага.
5. **`lab live` не можна «полагодити».** `LIVE_ENABLED=true` нічого не змінює.
   Не послаблюй ворота fail closed (напр. `adf_pvalue_max`), щоб «заторгувало»:
   `fills=0` — чесна відповідь.
6. **Ніяких LLM на гарячому шляху.** Модель живе лише в офлайн-контурі
   (`lab propose`, `research/prompts`, `research/hypotheses`). Виклик LLM під час
   бектесту — баг.
7. **Ніколи не комть і не друкуй секрети.** Ключі — лише в `.env` (git-ignored).
   Біржових ключів проєкт не потребує: дані беруться з публічних ендпоінтів.
8. **Не вигадуй числа.** Не робив прогону — так і скажи.
9. **Після змін коду** — зелені тести й лінтери (див. «Якість»).

## Структура

| Шар | Тека | Що там |
|-----|------|--------|
| Domain | `src/nautilus_lab/domain/` | сигнали, стратегії, ризик, метрики, `ports.py` |
| Application | `src/nautilus_lab/application/` | use cases: ingest, research, walk-forward, PBO-аудит, Optuna, журнал, ворота допуску |
| Infrastructure | `src/nautilus_lab/infrastructure/` | Binance REST + WS, Parquet-каталоги, Nautilus `BacktestEngine`, `Settings`, paper-сесії |
| Interfaces | `src/nautilus_lab/interfaces/` | `cli.py` і `composition.py` — єдина точка зборки залежностей |
| API | `src/nautilus_lab/api/` | FastAPI-дашборд: **ті самі** use cases, плюс живі paper-сесії й шлюз безпеки |
| Frontend | `frontend/` | React + Vite UI; власної логіки бектесту не має |

Залежності завжди йдуть **усередину**, до `domain/`. Отже:

- **`domain/` не імпортує `nautilus_trader`, не читає `.env` і не ходить у мережу.**
  Перевірка: `grep -rn "nautilus_trader\|Settings" src/nautilus_lab/domain/` — порожньо.
- `Settings` живе тільки в `infrastructure` і передається в домен параметрами.
- **Стратегія не знає розміру позиції**: `domain/` повертає лише напрямок
  (`Signal`), розмір рахує `application/risk.py`.
- Лише **закриті** бари (`RollingWindow.prior()`) і `Decimal`, не `float`.
- API не дублює логіку: зміна поведінки для CLI і для дашборду йде в
  `application/`/`domain/`, а не в `api/app.py`.

## Дані

`uv run lab ingest` тягне **публічні** дані Binance (без ключів) у Parquet-каталог:
klines типово, а також `--trades` (агреговані угоди), `--funding` (ставки фінансування)
і `--depth` (живі L2-знімки через WebSocket). Один каталог — один ingest: інший
інтервал (`BAR_INTERVAL`) чи інший інструмент = **нова тека** через `--catalog`.

```bash
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
uv run lab ingest --incremental --symbols ETHUSDT          # долити нові бари
uv run lab ingest --trades --live-ticks 20 --symbols ETHUSDT   # тіки для VPIN/Хоукса
```

## Основні команди

```bash
uv run lab research --synthetic --bars 3000     # smoke без мережі
uv run lab research                             # walk-forward regime по каталогу
uv run lab research --robot ema                 # baseline, з яким треба порівнювати
uv run lab research --robot regime --folds 4    # чи витримує нарізку на 4 вікна (+ ворота)
uv run lab research --robot regime --pbo        # аудит перенавчання PBO/CSCV (не разом з --optuna)
uv run lab research --optuna --trials 30        # байєсівський підбір (extra research)
uv run lab research --tearsheet reports/t.html  # HTML-тиршит (extra visualization)
uv run lab paper --robot regime --journal       # paper-сесія: повний журнал, ордерів немає
uv run lab xsmom --symbols BTCUSDT,ETHUSDT --folds 6 --pbo   # кошик + ворота допуску
uv run lab ml train --model-type meta_label --output models/meta_label.txt  # extra ml
uv run lab live                                 # завжди помилка, код 1
```

Extras: `dev`, `api` (fastapi, uvicorn, websockets — для дашборду), `ml` (lightgbm),
`research` (optuna, arch, polars), `visualization` (plotly, kaleido), `alerts` (httpx).

## Якість

```bash
uv run pytest                                    # має бути зеленим після будь-яких змін
uv run pytest --cov --cov-report=term-missing    # поріг покриття fail_under = 80
uv run ruff check --fix && uv run ruff format    # line-length 100
uv run mypy src tests                            # strict = true
.venv/bin/python specs/_validator.py             # специфікації проти коду
```

`uv run pytest` уже включає `tests/unit/test_specs.py`, тож дрейф спек ловиться
звичайним прогоном. Окремий виклик валідатора — коли треба деталі по спеці.

## Пастки середовища

- **`uv` може впасти з `Permission denied` на своєму кеші** — це обмеження
  оточення, а не проєкту. Тоді працюй через venv: `.venv/bin/lab`,
  `.venv/bin/pytest`, `.venv/bin/python`.
- **Змінні оболонки мають вищий пріоритет за `.env`.** У цьому оточенні задано
  `MAKER_FEE=0.0002` і `TAKER_FEE=0.0005`, тож фактичні комісії беруться звідти, а
  не з `.env` (`0.001`). Перевірка: `env | grep -iE "maker|taker"`.
- **`lab research | tail` показує код 0**, навіть якщо команда впала (код виходу
  pipeline — це код останньої команди). Перевіряй: `...; echo "exit=$?"`.
- Каталог порожній або вікно поза даними → `no bars in catalog ... Run 'lab ingest' first.`

## Spec-Driven Development

Кожен робот із `RobotName` має специфікацію в `specs/strategies/<robot>.yaml`,
яка **звіряється з кодом** (`name`, `wired_in_backtest`, `minimum_bars`,
`grid_source`, `domain_module`, `strategy_class`, `params[].env`):

```bash
.venv/bin/python specs/_validator.py            # усі спеки проти коду
.venv/bin/python specs/_validator.py regime     # одна
uv run pytest tests/unit/test_specs.py -q       # те саме + покриття
```

1. **Специфікація — до коду.** Змінюєш поведінку робота → спершу оновлюєш спеку.
   Спека, яка розійшлася з кодом, гірша за відсутню: вона впевнено бреше.
2. **Додав робота в `RobotName` — додай спеку.** Валідатор і тест покриття
   падають навмисно, доки її немає. Це і є `spec before code`, перевірене машиною.
3. **`grid_source` — не формальність.** `param_grid.py` має власні гілки для
   `pairs`, `vpin_momentum`, `formulaic_lgbm`, `meta_label`, `adaptive_ema`, `ema`;
   решта (`regime`, `ml_obi`) бере сітку `regime`. Робот без власної гілки підбирає
   чужі параметри й виглядає працюючим.
4. **`status` відображає реальність.** `validated` вимагає виміряної переваги над
   buy&hold. `candidate` («не доведено») ≠ `rejected` («доведено, що не працює»).
   Станом на зараз жоден робот не має `validated` — це задокументований результат.
5. **Інваріант компонента без тесту — твердження, а не гарантія.** У
   `specs/components/` пиши `verified_by`, а якщо тесту немає —
   `test_missing_reason`, а не мовчання.
6. **Не вигадуй числа в спеках.** Немає виміру — `measured: false`.

Повний протокол — `.agents/skills/spec-driven-development/SKILL.md`, зразок
спеки — `specs/strategies/regime.yaml`, пояснення — `specs/README.md`.

## Новий робот (end-to-end)

1. **Специфікація:** `specs/strategies/<robot>.yaml` за зразком `regime.yaml`,
   `.venv/bin/python specs/_validator.py <robot>` — нуль помилок **до** коду.
2. `domain/<robot>.py` — клас з `on_bar(bar) -> Signal | None`.
3. `tests/unit/test_<robot>.py` — тести без мережі.
4. Додати назву в `RobotName` **і** в `BACKTEST_WIRED_ROBOTS` (`domain/regime.py`) —
   без другого кроку `require_backtest_support()` заблокує робота.
5. `infrastructure/nautilus/signal_strategy.py` (гілка в `_build_robot()`) і
   `backtest_runner.py` (для спредових — `spread_strategy.py`).
6. Нові параметри — ланцюг із п'яти місць: `settings.py` → `.env.example` →
   `dtos.py` → `composition.py` → `backtest_runner.py`.
7. `application/param_grid.py` (гілка сітки) і `run_research_backtest.py::minimum_bars`.
8. Онови спеку під фактичні `grid`, `minimum_bars`, `grid_source`, і прожени
   `uv run pytest tests/ -q`.

Деталі, актуальні результати роботів і повний перелік розходжень документації з
кодом — у `.agents/skills/nautilus-lab/SKILL.md`.
