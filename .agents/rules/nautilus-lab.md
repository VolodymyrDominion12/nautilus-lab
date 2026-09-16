# nautilus-lab — правила роботи в проєкті

Дослідницька лабораторія торгових роботів на NautilusTrader. Python ≥ 3.12, `uv`,
єдина точка входу — CLI `lab` (`src/nautilus_lab/interfaces/cli.py`).

> У панелі Rules цьому правилу варто поставити активацію **Always On** (або
> **Model Decision** — опис нижче підходить як тригер).

Повний кукбук команд, пастки середовища й перелік розходжень документації з
кодом — у скілі, який підключено нижче. Цей файл — те, що треба пам'ятати завжди.

@../skills/nautilus-lab/SKILL.md

@../skills/spec-driven-development/SKILL.md

## Обов'язкові обмеження

1. **Режим — research.** `lab live` fail closed by design: адаптера виконання не
   існує. `LIVE_ENABLED=true` нічого не змінює. Не «лагодь» це.
2. **In-sample — лише вибір параметрів, не результат.** Звіт — виключно
   out-of-sample. `--full-sample` і `--synthetic` не є OOS-звітом.
3. **Завжди порівнюй із buy&hold** за той самий OOS-період. Плюсове число саме по
   собі не є перевагою.
4. **Не підбирай параметри на OOS.** Сітка, Optuna, `--is-fraction`,
   `--embargo-bars` — тільки на IS. OOS дивляться один раз для фінальної конфігурації.
5. **Не послаблюй ворота fail closed** (напр. `adf_pvalue_max`), щоб стратегія
   «заторгувала». `fills=0` — чесна відповідь.
6. **Жодних викликів LLM на гарячому шляху.** Модель живе лише в офлайн-контурі
   (`lab propose`, `research/prompts`, `research/hypotheses`).
7. **Секрети — лише в `.env`** (git-ignored). Не комть і не друкуй їх. Біржових
   ключів проєкт не потребує: дані беруться з публічних ендпоінтів Binance.
8. **Не вигадуй числа.** Не робив прогону — так і скажи.

## Spec-Driven Development (обов'язково)

Кожен робот із `RobotName` має специфікацію в `specs/strategies/<robot>.yaml`, і
вона **звіряється з кодом**:

```bash
.venv/bin/python specs/_validator.py            # усі спеки проти коду
uv run pytest tests/unit/test_specs.py -q       # те саме + покриття
```

1. **Специфікація — до коду.** Змінюєш поведінку робота → спершу оновлюєш спеку.
   Спека, яка розійшлася з кодом, гірша за відсутню: вона впевнено бреше.
2. **Додав робота в `RobotName` — додай спеку.** Валідатор і тест покриття
   падають навмисно, доки її немає.
3. **`grid_source` не формальність.** `param_grid.py` має гілки лише для `pairs`,
   `vpin_momentum`, `formulaic_lgbm`, `ema`; решта тихо бере сітку `regime`. Це
   найпідступніша пастка: робот без власної гілки підбирає чужі параметри й
   виглядає працюючим.
4. **`status` відображає реальність.** `validated` вимагає виміряної переваги над
   buy&hold; «не доведено» (`candidate`) і «доведено, що не працює» (`rejected`) —
   різні речі.
5. **Інваріант компонента без тесту — твердження, а не гарантія.** Пиши
   `verified_by`, а якщо тесту немає — `test_missing_reason`, не мовчання.
6. **Не вигадуй числа в спеках.** Немає виміру — `measured: false`.

## Архітектура

Залежності йдуть усередину, до `domain/`:

`domain/` → сигнали, стратегії, ризик, метрики · `application/` → use cases ·
`infrastructure/` → Binance, Parquet-каталог, Nautilus-рушій, `Settings` ·
`interfaces/` → `cli.py` + `composition.py` (єдина точка зборки).

- `domain/` **не імпортує `nautilus_trader`, не читає `.env`, не ходить у мережу**.
- Стратегія повертає лише напрямок (`Signal`) — розмір позиції рахує `application/risk.py`.
- Лише закриті бари (`RollingWindow.prior()`) і `Decimal`, не `float`.
- Новий робот реєструй у `RobotName` **і** в `BACKTEST_WIRED_ROBOTS`, інакше
  `require_backtest_support()` його заблокує.

## Команди

```bash
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
uv run lab research --synthetic --bars 3000     # smoke без мережі
uv run lab research                             # walk-forward по каталогу
uv run lab research --robot ema                 # baseline для порівняння
uv run lab research --robot regime --folds 4
uv run lab research --robot regime --pbo        # аудит перенавчання
```

## Перевірки після змін коду

```bash
uv run pytest                                    # має бути зеленим
uv run pytest --cov --cov-report=term-missing    # поріг покриття 80
uv run ruff check --fix && uv run ruff format    # line-length 100
uv run mypy src tests                            # strict = true
```

## Пастки середовища

- `uv` може впасти з `Permission denied` на своєму кеші — це обмеження оточення.
  Тоді працюй через `.venv/bin/lab`, `.venv/bin/pytest`, `.venv/bin/python`.
- Змінні оболонки мають **вищий** пріоритет за `.env`: тут `MAKER_FEE=0.0002` і
  `TAKER_FEE=0.0005` перекривають значення з `.env` (`0.001`).
- `lab research | tail` показує код 0, навіть коли команда впала. Перевіряй
  `...; echo "exit=$?"`.
- Один каталог — один ingest: інший `BAR_INTERVAL` чи інструмент вимагає нової
  теки через `--catalog`.
