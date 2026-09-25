---
name: nautilus-lab
description: Дослідницька лабораторія торгових роботів на NautilusTrader у /home/volodymyr/PycharmProjects/nautilus-lab — завантажує публічні Binance-klines у Parquet-каталог, запускає walk-forward бектести, Optuna-підбір, аудит перенавчання PBO/CSCV, тиршити, журнал досліджень і додає нових роботів у домен. Використовувати, коли користувач просить бектест, walk-forward, підбір параметрів, ingest klines Binance, оцінку робота, судження про перенавчання (overfitting/PBO) або створення нової стратегії в цьому проєкті.
whenToUse: Будь-яка задача, що торкається коду, даних, команд `lab` або звітів проєкту nautilus-lab; для інших проєктів у PycharmProjects ця навичка не діє.
---

# nautilus-lab — лабораторія роботів на NautilusTrader

Проєкт: `/home/volodymyr/PycharmProjects/nautilus-lab`; єдина точка входу — команда `lab` (`src/nautilus_lab/interfaces/cli.py`).
**Джерело правди про команди, прапорці та помилки — код, не `docs/`** (частина довідників відстала від `cli.py`, див. §10).

## 1. Коли застосовувати / коли ні

Застосовуй, коли користувач просить: **бектест** / walk-forward / out-of-sample результат («прожени робота»); **підбір параметрів**
(сітка або Optuna) чи чутливість (`--is-fraction`, `--embargo-bars`, `--slice`); оцінку **перенавчання** (overfitting, PBO/CSCV);
**ingest** історії Binance або полагодження порожнього/зламаного каталогу; додати чи змінити **робота (стратегію)**, параметри сітки,
ризик-шар, метрики; пояснення виводу `lab`, тиршита (`--tearsheet`), журналу (`--journal`), алертів (`--notify`); гіпотези альф
через `lab propose` (офлайн-контур LLM). **НЕ** застосовуй для живої торгівлі (адаптера виконання не існує — `lab live` завжди fail closed),
для обіцянок прибутковості та для інших проєктів у `/home/volodymyr/PycharmProjects`.

## 2. Золоті правила (дисципліна проєкту)

1. **In-sample — лише вибір параметрів, out-of-sample — це звіт**: рядок `in-sample (selection only)` не є результатом, а `out-of-sample (report this)` — єдине число, яке має значення.
3. `--full-sample` і `--synthetic` без `--walk-forward` — повний прогін (in-sample only); CLI друкує `full-sample catalog run (in-sample only; not an out-of-sample report)`.
4. Планка — **buy&hold за той самий OOS-період**: `--folds N≥2` друкує `baseline buy&hold mean=...` і, за потреби, `(does not beat buy&hold)`.
   Станом на зараз жоден із трьох основних роботів планку не обганяє (`README.md`, `docs/05 §4`): плюсове число без порівняння з buy&hold — не перевага.
5. **Підбір на OOS заборонено**: перебирати `--is-fraction`, `--embargo-bars`, сітку/Optuna можна лише на IS; OOS дивляться один раз для остаточної конфігурації.
6. **Embargo** (`--embargo-bars`, типово 10) — розрив між IS і OOS, це не помилка; IS і OOS не можуть перекриватися.
7. `lab live` — **fail closed by design**: `Live trading is disabled. This lab only runs research backtests.`, код 1; `LIVE_ENABLED=true` у `.env` нічого не змінює.
8. `lab paper` — лише лог гіпотетичних ордерів: без рушія, без виконання, **без стану позиції** (тому може записати кілька `buy` підряд — це спрощення, не баг).
9. **Дослідницький код ніколи не викликає LLM на гарячому шляху**: LLM живе тільки в офлайн-контурі (`lab propose`, `research/prompts`, `research/hypotheses`).
10. **Не послаблюй ворота fail closed**, щоб «заторгувало» (напр. `adf_pvalue_max` для `pairs`); `fills=0` — чесна відповідь, а не баг.
11. **Не вигадуй числа.** Якщо прогін не робився — так і скажи.

## 3. Середовище

Python **≥ 3.12** (`pyproject.toml`), локальний `.venv` — Python 3.13, менеджер залежностей — `uv`. Якщо `uv` не має доступу до кеша
(обмежене середовище) — запускай із venv: `.venv/bin/lab ...`, `.venv/bin/pytest -q`.

```bash
cd /home/volodymyr/PycharmProjects/nautilus-lab && cp .env.example .env
uv sync --extra dev                             # мінімум: pytest, ruff, mypy, pandas-stubs, pytest-cov
uv sync --extra dev --extra api                 # + fastapi, uvicorn, websockets, pyyaml, python-dotenv (дашборд)
uv sync --extra dev --extra ml --extra research # + lightgbm, optuna, arch, polars
uv sync --extra dev --extra research --extra visualization --extra alerts --extra api   # повний стек
```

Extras з `pyproject.toml`: `dev`, `api` (fastapi, uvicorn, websockets, pyyaml, python-dotenv — потрібен, щоб підняти
`uvicorn nautilus_lab.api.app:app`), `ml` (lightgbm), `research` (arch, optuna, polars), `visualization` (plotly, kaleido,
simplejson — для `--tearsheet`), `alerts` (httpx — для `--notify`). Пріоритет конфігурації: **змінні оболонки → `.env` → значення в коді**.

| Змінна | Типово | Значення |
|--------|--------|----------|
| `TRADING_MODE` / `LIVE_ENABLED` | `research` / `false` | `research` \| `paper` \| `live` (`live` блокується в коді); `true` у `LIVE_ENABLED` живу торгівлю не вмикає |
| `CATALOG_PATH` / `BAR_INTERVAL` / `INSTRUMENT_ID` | `catalog` / `1h` / `ETH/USDT.SIM` | тека Parquet-каталогу / `1m`, `5m`, `15m`, `1h`, `4h`, `1d` / інструмент симуляції |
| `BINANCE_SYMBOL` / `BINANCE_SYMBOLS` | `ETHUSDT` / `["ETHUSDT","BTCUSDT"]` | символи для ingest без `--symbols` (лише `*USDT`) |
| `STARTING_EQUITY` / `RISK_PER_TRADE` / `STOP_PCT` / `MAX_DAILY_LOSS` / `MAX_DRAWDOWN` / `MAX_OPEN_POSITIONS` | `100000`, `0.005`, `0.01`, `0.02`, `0.06`, `1` | капітал і ризик: частка на ризик в угоді, стоп 1% ціни, circuit breaker зупиняє нові входи |
| `ROBOT` / `ER_PERIOD` / `TREND_EMA_PERIOD` / `SLOPE_LOOKBACK` / `ENTER_TREND_ER` / `EXIT_TREND_ER` / `DONCHIAN_PERIOD` / `BB_PERIOD` / `BB_K` | `regime` / `20`, `40`, `10`, `0.30`, `0.20`, `20`, `20`, `2` | робот за замовчуванням і параметри `regime` (ER Кауфмана + нахил EMA, гістерезис) |
| `FAST_EMA` / `SLOW_EMA` | `10` / `20` | робот `ema` (slow > fast) |
| `EMBARGO_BARS` | `10` | розрив у барах між IS і OOS |
| `MAKER_FEE` / `TAKER_FEE` | `0.001` / `0.001` | комісії 0.1%; роботи ставлять ринкові ордери → платять taker |
| `USE_BAR_VPIN` / `VPIN_BUCKET_VOLUME` / `VPIN_TOXIC_THRESHOLD` | `false`, `1000`, `0.7` | VPIN-фільтр токсичного потоку |
| `KELLY_FRACTION` / `MAX_VAR_99` / `USE_VOL_SCALING` / `USE_FRACTIONAL_KELLY` / `USE_CVAR_BREAKER` / `USE_RATCHET` / `PAIRS_REFIT_EVERY` | `0.25`, `0.05`, решта `false`, `0` | ризик-overlays (типово вимкнені) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `ALERT_WEBHOOK_URL` | порожньо | потрібні для `--notify`; без них — порожній нотифікатор |
| `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` | порожньо | **не використовуються**: код їх не читає, ключі не потрібні |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_PROMPTS_DIR` / `LLM_HYPOTHESES_DIR` | порожньо, `https://api.deepseek.com/v1`, `deepseek-chat`, `research/prompts`, `research/hypotheses` | офлайн-контур `lab propose` |
| `JOURNAL_ENABLED` / `JOURNAL_PATH` / `JOURNAL_JSONL_PATH` | `false`, `research/journal.md`, `research/journal.jsonl` | журнал дослідження |
| `API_TOKEN` / `API_ALLOWED_ORIGINS` | порожньо | шлюз дашборду: токен `X-Lab-Token` і перелік дозволених origin (типово `:5173`/`:4173`/`:8000`) |
| `LAB_ROLE` | `full` | `full` \| `paper`; `paper` дозволяє лише контроли живого paper-терміналу на сервері |
| `USE_TICK_VPIN` / `USE_HAWKES` / `HAWKES_*` | `false`, `0.1`, `0.5`, `1.0`, `2.0` | тік-рівневі фільтри (потрібна серія `agg_trade` у каталозі) |
| `META_LABEL_MODEL_PATH` / `META_LABEL_THRESHOLD` / `FORMULAIC_MODEL_PATH` / `FORMULAIC_THRESHOLD` / `ML_OBI_MODEL_PATH` / `ML_OBI_THRESHOLD` | порожньо / `0.55` | шляхи до натренованих моделей (`lab ml train`) і їхні пороги |
| `CATALOG_PATHS` | порожньо | додаткові каталоги для побудови зрізів (окрім `CATALOG_PATH`) |
| `SELECTION_METRIC` / `DRAWDOWN_COOLDOWN_DAYS` / `USE_PROTECTIVE_STOP` / `PAIRS_Z_ENTRY_QUANTILE` | `pnl` / `0` / `true` / `0` | метрика відбору на IS, кулдаун після просадки, reduce-only стоп після входу, квантильний поріг входу `pairs` |
| `LIVE_PAPER_*` | `autostart=false`, `symbol=ETHUSDT`, `interval=1h`, `robot=regime`, `starting_equity=10000`, `max_sessions=8`, `max_feeds=5` | живий paper-термінал: сесії, портфель, ліміти фідів; `LIVE_PAPER_PORTFOLIO` — файл портфеля |

```bash
uv run python -c "from nautilus_lab.infrastructure.settings import Settings; s=Settings(); print(s.trading_mode, s.robot, s.bar_interval, s.fee_schedule())"
```

## 4. Кукбук команд

Коди виходу: `0` — успіх, `1` — будь-яка помилка (повідомлення в `stderr`).

### `lab ingest` — публічні дані Binance → Parquet-каталог

| Прапорець | Типово | Призначення |
|-----------|--------|-------------|
| `--start` / `--end` | 365 днів тому / зараз | вікно UTC (`YYYY-MM-DD`), кінець **виключно** |
| `--catalog` / `--symbols` | `CATALOG_PATH` / `BINANCE_SYMBOLS` | тека каталогу / символи через кому (лише `*USDT`) |
| `--incremental` | вимкнено | дописати лише бари після останнього збереженого; якщо вже актуально — пропустити |
| `--funding` | вимкнено | замість klines — розрахунки фінансування USD-M (подієва серія, `catalog/data/funding/`) |
| `--trades` | вимкнено | замість klines — агреговані угоди (тіки, `catalog/data/agg_trade/`); дають справжній VPIN і Хоукс |
| `--live-ticks MINUTES` | — | збирати живі aggTrades з публічного WebSocket задану кількість хвилин замість REST-історії (`MINUTES>0`) |
| `--depth` | вимкнено | живі L2-снапшоти стакану через WebSocket (`catalog/data/orderbook/`); працює, доки не зупиниш |

```bash
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
uv run lab ingest --start 2019-01-01 --end 2025-01-01 --symbols ETHUSDT,BTCUSDT --catalog catalog_long
uv run lab ingest --incremental --symbols ETHUSDT        # долити нові бари
uv run lab ingest --trades --live-ticks 20 --symbols ETHUSDT   # 20 хв живого потоку тіків
```

Друкує `symbol=... wrote=... first=... last=... catalog=...` (для тіків — свій формат із прогресом по днях); пише бари
+ опис інструмента в каталог, інтервал — з `BAR_INTERVAL`.
**Один каталог — один ingest**: для іншого вікна/інтервалу — нова тека через `--catalog`.

### `lab research` — основний шлях (за замовчуванням walk-forward по каталогу)

| Прапорець | Типово | Призначення |
|-----------|--------|-------------|
| `--robot` | `ROBOT` | див. §6: CLI приймає всі 11 назв `RobotName`, рушій підключено лише до 8 |
| `--bars` / `--synthetic` | `3000` / вимкнено | синтетичні бари замість каталогу (мережа не потрібна) |
| `--walk-forward` / `--full-sample` | увімкнено для каталогу / вимкнено | підбір на IS і звіт на OOS / один прогін на всій серії (**не** OOS-звіт) |
| `--is-start` `--is-end` `--oos-start` `--oos-end` | — | явні вікна (UTC, кінець виключно); потрібні **всі чотири** |
| `--is-fraction` / `--embargo-bars` | `0.7` / `EMBARGO_BARS` (10) | частка історії на підбір, коли дат немає / розрив між IS і OOS |
| `--catalog` / `--slice` | `CATALOG_PATH` / — | тека каталогу / стрес-період `covid2020`, `ftx2022`, `etf2024` |
| `--bar-vpin` / `--tick-vpin` / `--hawkes` | вимкнено | три різні фільтри: обсяг бару як проксі / справжні aggTrades / інтенсивність Хоукса (останні два потребують серії `agg_trade`) |
| `--optuna` / `--trials N` | вимкнено / `20` | байєсівський підбір (Optuna TPE) замість сітки; extra `research` |
| `--folds N` | `1` | `N≥2` → окремий walk-forward на кожен фолд + агрегат OOS і buy&hold; `N<1` → помилка |
| `--pbo` / `--pbo-blocks N` | вимкнено / `8` | аудит перенавчання PBO/CSCV; `N<2` → помилка; несумісний з `--tearsheet` |
| `--tearsheet PATH` / `--notify` | — / вимкнено | HTML-тиршит (extra `visualization`) / Telegram-Webhook після завершення (збій не змінює код виходу) |
| `--journal` | вимкнено | дописати рядок у журнал дослідження |

```bash
uv run lab research --synthetic --bars 5000            # smoke-тест без мережі
uv run lab research                                    # walk-forward regime по каталогу
uv run lab research --robot ema                        # baseline (завжди порівнюй із ним)
uv run lab research --robot pairs                      # дві ноги ETH/BTC
uv run lab research --robot regime --folds 4           # чи витримує результат нарізку на 4 вікна
uv run lab research --optuna --trials 30               # байєсівський підбір на IS
uv run lab research --full-sample                      # уся вибірка, лише in-sample
uv run lab research --is-fraction 0.5 --embargo-bars 0 # чутливість нарізки
uv run lab research --slice ftx2022 --catalog catalog_long
uv run lab research --robot regime --pbo               # PBO/CSCV: блоки × конфігурації
uv run lab research --tearsheet reports/tearsheet.html
uv run lab research --robot regime --folds 4 --journal # багатовіконний прогін + рядок у журнал
```

- walk-forward друкує `walk-forward (grid|optuna): parameters selected on in-sample only; report out-of-sample. tried=... selected=...`, далі
  `in-sample (selection only)` і `out-of-sample (report this)`; тиршит — для **OOS**-прогону (`tearsheet_saved=<шлях>`).
- `--folds N≥2`: рядок на фолд (`fold i OOS=[start, end) fills=... return=... buy_hold=... selected=...`), потім `out-of-sample aggregate profitable=k/N mean=...
  median=... worst=... best=...`, `baseline buy&hold mean=...`, `summary_line()`; тиршит — **лише останнього** фолда.
- `--full-sample` / `--synthetic`: `fills= positions= ending=` і метрики `fees_paid= max_dd= turnover= sharpe_like=`.
- `--pbo`: `blocks= configurations=`, матриця `blocks × configurations` у відсотках, підсумок `PBO=... over <k> splits ...` (`≈ 0` — вибір відтворюється;
  `≈ 0.5` — монетка; `> 0.5` — вибір шкодить; `undefined` — конфігурацій < 2).
- `--journal` (або `JOURNAL_ENABLED=true`): дописує рядок у `research/journal.md` + `research/journal.jsonl`, друкує `journal_row_appended=<шлях>`; у колонці OOS ніколи не буває IS-числа (там `n/a`, а IS іде в «Причину»).

### Решта команд

| Команда | Що робить | Вивід / артефакт |
|---------|-----------|------------------|
| `lab paper [--bars N] [--robot {…8 назв…}] [--source {catalog,synthetic,live}] [--live-bars N] [--live-timeout S] [--select-on-is] [--embargo-bars N] [--tick-vpin] [--hawkes] [--journal]` | проганяє **заморожену** конфігурацію вперед і пише повний журнал угод/позицій/комісій; ордери нікуди не надсилаються | рядок сесії + `--journal` дописує в `reports/paper/sessions.jsonl`; без `--select-on-is` робот із дефолтами, які не торгують, чесно дає `fills=0` |
| `lab ml train --model-type {formulaic,meta_label,obi} [--catalog] [--instrument] [--interval] [--output] [--folds 5] [--embargo 10] [--horizon] [--profit] [--stop] [--vol-window] [--start] [--end] [--threshold]` | навчає LightGBM-класифікатор із purged K-fold і потрійним бар'єром | `saved=<шлях> rows=... folds=...`; потрібен extra `ml`, інакше `lightgbm extra not installed` |
| `lab xsmom --symbols A,B,C [--interval] [--catalog] [--start] [--end] [--folds 6] [--is-fraction] [--lookbacks 14,30,60] [--top-n 2,3] [--rebalance 7] [--no-positive-filter] [--inverse-vol] [--slippage-bps] [--metric {pnl,sharpe,calmar}] [--pbo] [--pbo-blocks 8]` | крос-секційний momentum: ранжує кошик за минулою доходністю, тримає `top-n`, переранжовує; ковзний walk-forward + опційний аудит | рядки фолдів, агрегат OOS і `promotion_gate=PROMOTE\|REJECT\|INCOMPLETE (...)` |
| `lab scan --triangular` | сканер трикутного арбітражу на зашитих курсах | `triangular_opportunities=N` (зараз 0 — демонстрація); без прапорця `Specify --triangular`, код 1 |
| `lab propose [--prompt ...] [--count 5] [--as-of YYYY-MM-DD] [--model ...] [--base-url ...] [--output-dir ...] [--slug ...] [--dry-run] [--journal]` | питає LLM про гіпотези альф — офлайн, без ринкових даних і без торгівлі | `--dry-run` друкує промпт без мережі; інакше `artifact=<шлях>` у `research/hypotheses/`; без `LLM_API_KEY` — fail closed, код 1 |
| `lab live` | завжди помилка | `Live trading is disabled. This lab only runs research backtests.`, код 1 |

Ворота допуску (`application/promotion_gate.py`, `GateCriteria`): `min_folds=6`, `min_profitable_share=0.83`,
`min_oos_fills=30`, `max_pbo=0.3`, `min_dsr=0.95`. Кожна перевірка дає PASS / FAIL / **not measured**, і `not measured`
**ніколи** не читається як PASS — тому verdict `INCOMPLETE` ≠ `REJECT`.

## 5. Дані та каталог

Потік (усі джерела — **публічні**, без API-ключів): REST `https://api.binance.com/api/v3/klines` (пагінація по 1000 свічок) →
`BinancePublicKlines` → `NautilusParquetCatalog` → каталог `CATALOG_PATH` (типово `catalog/`) → `lab research`.
Окремі джерела з власними каталогами: `--trades` (aggTrades: REST із пагінацією або живий WS через `--live-ticks`),
`--funding` (USD-M funding), `--depth` (живий L2 через WS).

```
catalog/data/bar/<INSTRUMENT_ID>-<SPEC>-LAST-EXTERNAL/*.parquet   # ETHUSDT.SIM-1-HOUR-LAST-EXTERNAL
catalog/data/currency_pair/<INSTRUMENT_ID>/*.parquet              # ETHUSDT.SIM, BTCUSDT.SIM
catalog/data/agg_trade/<SYMBOL>/*.parquet                         # тіки для VPIN і Хоукса
catalog/data/funding/<SYMBOL>/*.parquet                           # розрахунки фінансування
catalog/data/orderbook/<SYMBOL>/*.parquet                         # L2-снапшоти
```

- Інтервал у назві серії: `1-MINUTE`, `5-MINUTE`, `15-MINUTE`, `1-HOUR`, `4-HOUR`, `1-DAY` (`infrastructure/timeframe.py`); інструменти симуляції — `ETH/USDT.SIM`, `BTC/USDT.SIM` (спот) і `ETHUSDT-PERP.SIM` (перпетуал), підтримуються лише Binance-символи на `USDT`.
- `catalog/`, `reports/`, `*.html` — у `.gitignore`; `research/journal.md`, `research/journal.jsonl`, `research/hypotheses/` — артефакти в git.
- Зміна `BAR_INTERVAL` або `INSTRUMENT_ID` = **новий ingest**: серії `-1-HOUR-` і `-5-MINUTE-` — різні набори даних.
- **Відсутня серія тіків читається як порожня** (`agg_trades_catalog.py` прямо це документує): `--tick-vpin`/`--hawkes` на
  каталозі без `--trades` не падає — фільтр просто не має на чому рахувати. Перевіряй наявність серії заздалегідь
  (дашборд показує `present`/`missing` по кожному інструменту).

## 6. Архітектура: куди писати код

Чотири шари, залежності завжди йдуть **усередину** — до `domain`:

| Шар | Тека | Що там |
|-----|------|--------|
| Domain | `src/nautilus_lab/domain/` | сигнали, індикатори, стратегії, ризик-правила, метрики, `ports.py` |
| Application | `src/nautilus_lab/application/` | use cases: ingest, research, walk-forward, overfitting audit, param grid, Optuna, journal, promotion gate, DTO |
| Infrastructure | `src/nautilus_lab/infrastructure/` | Binance REST + WS, Parquet-каталоги (бари, тіки, funding, стакан), Nautilus `BacktestEngine`, синтетика, `Settings`, LightGBM, alerts, LLM-клієнт, paper-сесії |
| Interfaces | `src/nautilus_lab/interfaces/` | `cli.py` (argparse + друк) і `composition.py` — **єдина точка зборки залежностей** |
| API | `src/nautilus_lab/api/` | FastAPI-додаток: **ті самі** use cases через `composition.py`, плюс живі paper-сесії, WS-фіди й шлюз безпеки (`security.py`) |
| Frontend | `frontend/` | React + TypeScript + Vite UI; власної логіки бектесту не має |

- **`domain/` не імпортує `nautilus_trader`, не читає `.env` і не ходить у мережу**; перевірка: `grep -rn "nautilus_trader" src/nautilus_lab/domain/` і `grep -rn "Settings" src/nautilus_lab/domain/` — порожньо.
- API не дублює логіку: якщо зміна поведінки потрібна і в CLI, і в дашборді, вона йде в `application/` або `domain/`, а не в `api/app.py`.
- `Settings` живе лише в `infrastructure` і передається в домен параметрами; залежності збирає `composition.py` (`settings()`, `catalog()`, `*_use_case()`, `*_request()`).
- **Стратегія не знає розміру позиції**: `domain/` повертає лише напрямок (`Signal`), розмір рахує `application/risk.py`.
- **Тільки закриті бари** (`RollingWindow.prior()` — усі значення, крім щойно закритого) і **`Decimal`**, не `float`; робот без адаптера не підміняється іншим — `require_backtest_support()` падає з `robot 'funding' has no backtest adapter yet; use one of: ...`, а новому роботу потрібна гілка в `application/param_grid.py` (інакше спрацює сітка `regime`) і, за потреби, новий мінімум барів.

**Новий робот end-to-end** (`docs/07`, звірено з кодом):
1. `domain/<robot>.py` — клас із `on_bar(bar: OhlcvBar) -> Signal | None` (без Nautilus, без `.env`, без ордерів); `tests/unit/test_<robot>.py` — юніт-тести без мережі.
2. `domain/regime.py` — додати назву в `RobotName` (тоді `--robot` підхопить її автоматично) **і** в `BACKTEST_WIRED_ROBOTS`, інакше `require_backtest_support()` заблокує робота (у `docs/07` цього кроку немає, а код його вимагає).
3. `infrastructure/nautilus/signal_strategy.py` — поля в `SignalRobotConfig` + гілка в `_build_robot()`; `infrastructure/nautilus/backtest_runner.py` — передати нові параметри в конфіг.
4. Нові параметри з `.env` — ланцюг із п'яти місць: `infrastructure/settings.py` → `.env.example` → `application/dtos.py` (`BacktestRequest`, `SelectedParams`, `apply_selected()`) → `interfaces/composition.py` → `backtest_runner.py`.
5. `application/param_grid.py` — гілка сітки; `application/run_research_backtest.py::minimum_bars` — мінімум барів на розігрів.

## 7. Якість (quality gates)

```bash
uv run pytest                                 # testpaths=tests, pythonpath=src, addopts "-q --strict-markers"
uv run pytest --cov --cov-report=term-missing # поріг покриття fail_under = 80 (branch = true)
uv run ruff check --fix && uv run ruff format # line-length 100, select E,F,I,N,UP,B,SIM,ANN,RUF
uv run mypy src tests                         # strict = true, python_version = 3.12
.venv/bin/python specs/_validator.py          # спеки проти коду (те саме в pytest як test_specs.py)
uv run lab research --synthetic --bars 3000   # smoke-тест після зміни коду
```

- `fail_under = 80` (`[tool.coverage.report]`) діє лише з `--cov`: `uv run pytest` без `--cov` покриття не рахує. Виключено з покриття `infrastructure/nautilus/{backtest_runner,instrument,signal_strategy}.py`.
- Маркер `integration` — локальний I/O рушія без мережі (`pytest -m integration`).
- Після змін у шляху виконання перевір, що `lab live` і далі падає fail closed.
- **Зміна робота = спершу специфікація.** `specs/strategies/<robot>.yaml` оновлюється (або створюється) **до** коду;
  валідатор і тест покриття падають навмисно, доки спеки немає. Числа в спеці — лише виміряні
  (`measured: true/false`), інакше вони стають «впевненою брехнею».

## 8. Пастки

- **Порожній каталог / вікно поза даними** → `no bars in catalog ... Run 'lab ingest' first.` Причини: каталог не завантажений; `--catalog` вказує в інше місце (відносний шлях від cwd); `--slice`/дати поза історією (типово: каталог на 2025, а слайс `ftx2022`); інший `BAR_INTERVAL` чи `INSTRUMENT_ID`.
- **Дублікати барів** → `bar timestamps must be strictly increasing`. Причина: повторний ingest у той самий каталог із перекриттям. `write()` тепер ідемпотентний (replace діапазону), `load()` дедуплікує, тож помилка означає код, старіший за виправлення. Лікування: `rm -rf catalog && uv run lab ingest ...` або новий `--catalog`.
- **`bar_count must be >= N so indicators can warm up`** → мінімум на **кожен** фолд (`minimum_bars` у `application/run_research_backtest.py`): `regime`, `vpin_momentum`, `meta_label`, `adaptive_ema` — 150; `pairs` — 200; `formulaic_lgbm` — 80; решта (`ema`, `ml_obi`, `funding`, `glft`, `tri_scan`) — 50. Лікування: довша історія, менший `--folds`, інший `--is-fraction`.
- **`--folds N≥2` разом із явними датами** → `multi-window runs derive their own windows; drop --is-start/--oos-start`: багатовіконний прогін будує вікна сам, керуй через `--is-fraction` і `--embargo-bars`.
- **`--pbo --tearsheet`** → помилка навмисна: аудит симулює `blocks × configurations` прогонів, єдиного «того» прогону немає.
- **`--pbo` разом із `--optuna`/`--trials`** → прапорці Optuna **тихо ігноруються**: шлях PBO викликає `overfit_audit_request()`, який їх не приймає. Не подавай такий прогін як «bayesian PBO».
- **Синтетика дає +3000%** (`ending=3351101.12` з 100 000) — артефакт синтетичного random walk, не перевага; синтетика лише для smoke-тестів, результати — тільки з каталогу реальних даних. Walk-forward на синтетиці йде на **1-хвилинних** барах від 2024-01-01.
- **`fills=0` на `pairs`** — не зламаний ADF (його виправлено): не пройдені ворота коінтеграції (`adf_pvalue_max` 0.05), задовга half-life (> 240 барів) або z-score не дійшов до `z_entry` (2.0). Ворота fail closed — не послаблювати «щоб заторгувало».
- **`max_dd` майже завжди дорівнює `MAX_DRAWDOWN` (0.06)** → просадка впиралася в circuit breaker, який блокує нові входи: ризик завеликий або стратегія слабка. А **`fees_paid`, співмірний із прибутком**, означає високий `turnover` (типово для по-барних роботів, як `ema` — тому він baseline, а не робоча стратегія).
- **Тиршит не створився, а прогін успішний** → немає extra `visualization` (`Cannot generate tearsheet: plotly is missing.`) або помилка в Nautilus: генерація тиршита **ніколи не ламає прогін**; файл важкий (~4.3 МБ).
- **`--notify` нічого не надіслав, код 0** → потрібні `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (обидві) або `ALERT_WEBHOOK_URL` і extra `alerts`; збій сповіщення не є помилкою дослідження.
- **`optuna is not installed`** → `uv sync --extra research`; `lightgbm extra not installed; use HeuristicDirectionClassifier` → `--extra ml`; EGARCH повертає `None` без `arch`.
- **`Pandas4Warning: Timestamp.utcnow is deprecated`** — **не твій баг**: попередження виникає всередині NautilusTrader (`backtest/engine.pyx`) і точково заглушене у `filterwarnings`; якщо текст змінився — оновлюй фільтр, а не вимикай попередження глобально.
- **`.env` «не слухається»** → змінні оболонки мають вищий пріоритет. У цьому оточенні задано `MAKER_FEE=0.0002` і `TAKER_FEE=0.0005`, тобто фактичні комісії беруться звідти, а не з `.env` (`0.001`). Перевірка: `env | grep -iE "maker|taker|risk|robot|trading"`.
- **`lab research | tail` показує код 0**, хоча команда впала (код виходу pipeline = код останньої команди). Перевіряй так: `uv run lab research --slice ftx2022; echo "exit=$?"`. І пам'ятай: `uv` може впасти з `Permission denied` на своєму кеші — тоді запускай `.venv/bin/lab`, `.venv/bin/pytest`.
- **«Стратегія не працює»** → порядок: `fills > 0` → порівняти з baseline `--robot ema` → перевірити комісії/`turnover` → варіювати `--is-fraction`/`--embargo-bars` → стрес-слайс → і, найімовірніше, визнати, що переваги немає (нормальний результат більшості ідей).
- **`lab paper` дає `fills=0`, хоч робот «робочий»** → без `--select-on-is` сесія йде на **дефолтних** параметрах, а вони в багатьох роботів не перетинають поріг входу. `--select-on-is` підбирає параметри на історії **перед** вікном сесії (з embargo). Це не «зламаний режим» — це та сама гіпотеза, яку не підтверджено (див. `docs/24` §5).
- **`LAB_ROLE=paper` «не дає запустити research»** → так і задумано: сервер із цією роллю приймає лише `POST /api/paper/live/*` і створення paper-сесії, а research/ingest/ML/перезапис `.env` відхиляє (`api/security.py`, `PAPER_ROLE_WRITES`). Дослідження — на робочій станції.
- **Живий paper-термінал не бачить робота** → живий список (`LIVE_PAPER_ROBOTS` у `api/paper_streamer.py`) **коротший** за `BACKTEST_WIRED_ROBOTS`: там немає `pairs`, `meta_label`, `ml_obi` (їм потрібні дані, яких живий шлях не збирає), але є бенчмарк `hold`.
- **Дашборд показує порожньо** → API і UI — два процеси: `.venv/bin/uvicorn nautilus_lab.api.app:app --port 8000` (extra `api`) і `cd frontend && npm run dev` (`:5173`). UI не має власних даних.

## 9. Куди дивитись за деталями

`docs/10-cli-dovidnyk.md` — усі команди й прапорці (звіряй із `interfaces/cli.py`); `docs/04-tsykl-doslidzhennya.md` — повний цикл дослідження;
`docs/03-arhitektura.md` — шари й ланцюг даних; `docs/07-yak-stvoryty-strategiyu.md` — новий робот покроково; `docs/05-roboty.md` — роботи й реальні
результати; `docs/06-ryzyk-metryky.md` — ризик і метрики; `docs/11-troubleshooting-faq.md` — помилки й «дивна поведінка»;
`docs/15-audit-vypravlennya.md` — виправлені логічні баги; `docs/12-karta-fayliv.md` — карта модулів; `docs/14-llm-model-u-torhivli.md` і
`research/README.md` — офлайн-контур LLM;

новіші шари проєкту: `docs/24-paper-treydynh.md` — paper-сесії та живі виміри; `docs/25-xsmom-ta-vorota-dopusku.md` — `lab xsmom`
і пороги `promotion_gate`; `docs/26-deploy-vps.md` — VPS-деплой живого paper (`LAB_ROLE=paper`, Docker + Caddy);
`docs/20-veb-dashbord-ta-alpha-proposer.md` і `frontend/README.md` — дашборд (API-роути, вкладки, безпека);
`specs/README.md` — Spec-Driven Development; `docs/23-infrastruktura-danyh-plan.md` — які зовнішні дані варто підключати;
`docs/16-…19-…` — мапи відповідності зовнішніх оглядів (LLM, ML-ансамблі, трансформери/SSM, стекінг) до коду.

## 10. Де документи розходяться з кодом (перевіряй код)

**Стан після аудиту 2026-09-24.** Документацію звірено з кодом наскрізь і більшість
розходжень виправлено: `README.md`, `docs/README.md`, `AGENTS.md` + цей скіл, `docs/01–15`,
`docs/20–26`, `docs/uml/*`, `frontend/README.md`, `.env.example`. Список нижче — те, що
лишилося **навмисно** чи потребує рішення людини. Якщо документ суперечить коду — правда
в коді.

- **`--pbo --optuna --trials`.** Шлях `--pbo` у `cli.py` викликає `overfit_audit_request()`,
  який не має параметрів Optuna: у режимі аудиту `--optuna`/`--trials` **тихо ігноруються**
  (виконується сітковий аудит). Це вже попереджено в `docs/10`, але код поводиться так само —
  не подавай такий прогін як «байєсівський PBO».
- **Немає екстри → трейсбек, а не чисте повідомлення.** `optuna_optimizer.py` і
  `train_*.py` кидають `RuntimeError` (`optuna is not installed; run: uv sync --extra research`,
  `lightgbm extra not installed; run: uv sync --extra ml`), а `except`-набір у `cli.py`
  (`main`) його не містить. Код виходу все одно 1, але користувач бачить трейсбек.
- **`tools/` у репозиторії немає.** Для перевірки цілісності каталогу — inline-сніпет із
  `docs/04` або `find catalog/data/bar -maxdepth 1 -type d`; частковий веб-еквівалент —
  `GET /api/data` (`api/data_health.py`). `docs/23` позначила це як частково закритий борг.
- **`specs/components/derivatives-data.yaml` не існує**, хоч Фаза 3 у `docs/23` його обіцяла
  (тому Фаза 3 там позначена як виконана частково).
- **Виміри в `docs/24` §3 походять із трьох прогонів, яких немає в трекованому журналі**
  (`adaptive_ema`, `formulaic_lgbm`, `vpin_momentum`). Висновок таблиці від цього не
  змінюється, але конкретні числа не відтворюються з `reports/paper/sessions.jsonl` —
  попередження додано прямо в документі.
- **Два дефекти коду, знайдені під час аудиту документації (не виправлені):**
  `scripts/deploy_vps.sh` дописує `LAB_UID`/`LAB_GID`, яких **ніхто не читає**, тоді як
  `deploy/Dockerfile.api` жорстко фіксує `--uid 1000`; `deploy/paper_portfolio.yaml`
  обіцяє логувати змінені параметри сесії, а `live_sessions.py` порівнює лише
  `robot`/`symbol`/`interval`.
- **Крок покриття в CI блокує** (у Фазі E-1.9 `continue-on-error` прибрано,
  покриття 80.50% ≥ `fail_under = 80`). `pyproject.toml` тримає поріг 80%.
- **`uv` без доступу до кеша** падає з `Permission denied` — тоді працюй через
  `.venv/bin/lab`, `.venv/bin/pytest`, `.venv/bin/python`; це обмеження оточення, не проєкту.
