# 03. Архітектура: як усе з'єднано

Документ для тих, хто хоче розуміти код, а не лише запускати команди.

## 1. Чотири шари і одне правило

```
┌───────────────────────────────────────────────────────────────────────┐
│  interfaces/            CLI `lab`, збірка залежностей (composition)    │
│  api/ + frontend/       FastAPI `/api/*` + WebSocket, React-SPA        │
│  дві точки входу, обидві знають про всі шари                           │
└───────────────┬───────────────────────────────────────────────────────┘
                │ створює об'єкти, передає налаштування
┌───────────────▼───────────────────────────────────────────────────────┐
│  application/           сценарії використання (use cases)              │
│  ingest, research, walk-forward, paper, param grid, ризик, DTO         │
└───────────────┬───────────────────────────────────────────────────────┘
                │ викликає чисту логіку, залежить від протоколів (ports)
┌───────────────▼───────────────────────────────────────────────────────┐
│  domain/                чиста логіка: сигнали, індикатори, стратегії   │
│  ЖОДНОГО import nautilus_trader, ЖОДНОГО читання .env, ЖОДНОЇ мережі   │
└───────────────▲───────────────────────────────────────────────────────┘
                │ реалізує протоколи домену (adapter pattern)
┌───────────────┴───────────────────────────────────────────────────────┐
│  infrastructure/        Binance REST, Parquet-каталог, Nautilus-рушій, │
│  синтетичні дані, pydantic Settings, LightGBM, arch                    │
└───────────────────────────────────────────────────────────────────────┘
```

**Правило залежностей:** стрілки завжди йдуть **усередину** — до `domain`.
Домен нічого не знає про Nautilus, біржу чи файли. Тому:

- логіку стратегії можна тестувати за мілісекунди без мережі й без рушія;
- заміна біржі чи рушія не чіпає жодного рядка логіки;
- `Settings` (читання `.env`) живе лише в `infrastructure` і передається в домен параметрами.

**Дві точки входу, один набір сценаріїв.** `lab` у терміналі
(`interfaces/cli.py`) і веб-додаток (`api/app.py` + статика `frontend/`) викликають
ті самі use cases з `application/` — окремої «серверної» копії логіки немає.
Розгортання веб-додатка на VPS описано в `deploy/` (Dockerfile.api, Dockerfile.web,
Caddyfile, docker-compose.yml) і в [26-deploy-vps.md](26-deploy-vps.md).

Перевірити інваріант домену можна однією командою:

```bash
grep -rn "nautilus_trader" src/nautilus_lab/domain/    # нічого не знайде
grep -rn "Settings" src/nautilus_lab/domain/           # нічого не знайде
```

Станом на зараз `domain/` не має **жодного** стороннього імпорту — лише stdlib
(`decimal`, `datetime`, `enum`, `math`, `itertools`, `collections.abc`, `typing`).
Перевірити повністю:

```bash
grep -rn "^from \|^import " src/nautilus_lab/domain/ | grep -v nautilus_lab.domain
```

## 2. Головні типи даних

Розуміння п'яти типів — це 80% розуміння коду.

### `OhlcvBar` — один закритий бар (`domain/bars.py`)

```python
OhlcvBar(
    instrument_id="ETH/USDT.SIM",
    ts_utc=datetime(..., tzinfo=UTC),  # час закриття бару, строго UTC
    open=Decimal("3500.00"),
    high=Decimal("3510.00"),
    low=Decimal("3495.00"),
    close=Decimal("3505.00"),
    volume=Decimal("120.5"),
)
```

Чому `Decimal`, а не `float`: гроші не терплять двійкової похибки. `0.1 + 0.2 != 0.3` у float —
у торгівлі це призводить до розбіжностей у розрахунках позиції.

Функція `validate_bar()` (там же) перевіряє інваріанти й відкидає погані дані:
часовий пояс мусить бути UTC, `high >= max(open, close)`, `low <= min(open, close)`,
обсяг не від'ємний, час **строго зростає**, бар не з майбутнього.

### `Signal` — намір стратегії (`domain/signals.py`)

```python
Signal(
    instrument_id="ETH/USDT.SIM",
    side=SignalSide.BUY,
    bar_ts_utc=...,
    reason="donchian breakout long",
)
```

`SignalSide` — це `BUY`, `SELL` або `FLAT` (вийти в кеш). **Немає поля «кількість»** — навмисно.

Крім `Signal` є ще два родинні типи:

- `SpreadSignal` + `LegIntent` — намір для двох ніг одночасно (pairs, funding). `qty_weight` — відносна вага ноги, не розмір у USDT.
- `QuoteIntent` — намір виставити дві лімітні котировки bid/ask (маркет-мейкінг GLFT).

### `RiskLimits` і `AccountSnapshot` (`domain/risk.py`)

`RiskLimits` — жорсткі обмеження (частка ризику, стоп, денний ліміт, просадка, VaR).
`AccountSnapshot` — «стан рахунку зараз»: поточний капітал, пік, капітал на початок дня, кількість відкритих позицій, останні дохідності.
Разом вони дають `RiskDecision(allowed: bool, reason: str)`.

### `BacktestRequest` / `BacktestReport` (`application/dtos.py`)

`BacktestRequest` — повний опис прогону: режим, інструмент, кількість барів, стартовий капітал,
ризик-ліміти, який робот, параметри, джерело барів (`catalog` чи `synthetic`), комісії, embargo, стрес-слайс.
`BacktestReport` — результат: кількість філів, позицій, кінцевий баланс, метрики, текстова нотатка.

### `Settings` (`infrastructure/settings.py`)

Pydantic-модель, яка читає `.env` і змінні середовища, і **вміє перетворювати себе** на доменні об'єкти:
`risk_limits()`, `fee_schedule()`, `regime_params()`, `pairs_params()`.

## 3. Головний ланцюг: що відбувається під час `lab research`

```
CLI  interfaces/cli.py: main()
  │  аргументи --robot, --catalog, --is-fraction, --slice, --embargo-bars ...
  ▼
composition.py: settings() → Settings()            читає .env + env vars
  │            walk_forward_request(cfg)  → WalkForwardRequest
  │            walk_forward_use_case(cfg) → RunWalkForward(engine, feed)
  ▼
application/run_walk_forward.py: RunWalkForward.execute()
  │  1. require_simulated_mode()      ← живий режим відсікається тут
  ▼
infrastructure/nautilus/bar_feed.py: ResearchBarFeed.load() / load_multi()
  │  джерело: catalog (ParquetDataCatalog) АБО синтетика (детермінований генератор)
  │  для pairs: завантажує дві серії та робить inner-join за часом (domain/align.py)
  ▼
domain/walk_forward.py: anchored_window() + split_by_window()
  │  ділить історію: [IS ... embargo ... OOS]
  ▼
вибір параметрів (одне з двох):
  │  A) сітка: application/param_grid.py → iter_param_grid()
  │  B) байєсівський пошук: application/optuna_optimizer.py (прапорець --optuna)
  │  для кожного кандидата → apply_selected() → engine.run(candidate, IS-бари)
  │  оцінка: application/score.py → in_sample_score() = ending_balance (вищий = кращий)
  ▼
infrastructure/nautilus/backtest_runner.py: NautilusResearchBacktest.run()
  │  створює BacktestEngine: венʼю SIM, OmsType.NETTING, MARGIN, плече 1x,
  │  FillModel(prob_slippage=0.25), LatencyModel(50 мс), bar_execution=True
  │  конвертує доменні бари у нативні Bar (bar_convert.py), додає інструмент і стратегію
  ▼
infrastructure/nautilus/signal_strategy.py: SignalRobot.on_bar()
  │  нативний Bar → доменний OhlcvBar (з валідацією)
  │  → domain: RegimeRouter.on_bar() або EmaCrossover.on_bar()
  │  → Signal (buy/sell/flat або None)
  │  → application/risk.py: evaluate_entry()  ← circuit breakers
  │  → application/risk.py: stop_distance() (2×ATR, якщо ATR є; інакше 1% ціни)
  │  → application/risk.py: size_position()   ← розмір з ризику і стопу
  │  → order_factory.market(...) → submit_order(...)
  ▼
engine.run() → fills / positions / account report (pandas DataFrame)
  │  → domain/metrics.py: compute_metrics() → fees_paid, max_dd, turnover, sharpe_like
  ▼
BacktestReport  →  друк у консоль
```

Для робота `pairs` ланцюг майже той самий, але замість `SignalRobot` працює `SpreadRobot`
(`spread_strategy.py`), який чекає, доки зійдуться часові мітки обох ніг, і надсилає **два** ордери.

### 3.1 Другий вхід: веб-додаток і паперовий термінал

Той самий набір сценаріїв, але замість `argparse` — HTTP і WebSocket:

```
frontend/ (React + Vite SPA)  ──fetch /api/*──►  api/app.py: FastAPI
                                                   │  middleware: Origin + X-Lab-Token
  ▼                                                │  + LAB_ROLE (full | paper) — api/security.py
два типи роботи:
  │  A) важкі прогони (research, ingest, ML-тренування) — окремим процесом:
  │     api/run_research_job.py / run_paper_job.py / run_ml_job.py
  │     → application/run_walk_forward.py тощо, результат у reports/
  │     (слот на задачу — один, повторний запуск відхиляється)
  │  B) живий паперовий термінал — у процесі сервера:
  │     api/market_feed.py: MarketFeed — ОДИН сокет Binance на symbol+interval,
  │                            спільний для всіх сесій (FeedHub)
  │     → infrastructure/binance_ws.py: BinanceKlineStream / parse_kline_message
  │     → api/paper_streamer.py: LivePaperSessionManager — доменний робот,
  │       application/risk.py, симульовані філи в пам'яті (ордерів на біржу немає)
  │     → WebSocket /api/paper/live-stream  ──►  браузер (INIT_STATE + оновлення)
  │     → infrastructure/live_paper_journal.py: журнал сесії, що переживає рестарт
  ▼
api/live_sessions.py: SessionRegistry — реєстр сесій, resume після SIGTERM
```

Важлива відмінність від CLI: тут є **мережа в реальному часі** (публічний
Binance WebSocket) і процес, що живе довго. Виконання живих ордерів як не було,
так і немає — це той самий паперовий контур, лише з потоковими барами замість
каталогу (див. [24-paper-treydynh.md](24-paper-treydynh.md)).

## 4. Що робить кожен шар (детально)

### `domain/` — чиста логіка

| Підгрупа | Модулі | Роль |
|----------|--------|------|
| Базові типи | `bars.py`, `signals.py`, `errors.py`, `money.py`, `trading_mode.py`, `windows.py`, `ticks.py` | Бар, сигнал, помилки, гроші, режими, ковзне вікно, тик (`AggTrade`) |
| Індикатори | `ema.py`, `atr.py`, `windows.py`, `volatility.py`, `quantiles.py` | EMA (з SMA-сідом), ATR Вайлдера, HAR-RV, емпіричний квантиль |
| Класифікація режиму | `regime.py` | `RegimeClassifier` (ER Кауфмана + нахил EMA + гістерезис), `RegimeParams`, `RobotName`, `BACKTEST_WIRED_ROBOTS`, `TICK_VPIN_ROBOTS`, `HAWKES_ROBOTS` |
| Стратегії | `donchian.py`, `mean_reversion.py`, `ema_crossover.py`, `regime_router.py`, `adaptive_ema.py`, `vpin_momentum.py`, `buy_and_hold.py` | Пробій, повернення до середнього, перетин EMA, маршрутизатор між ними, адаптивне згладжування, VPIN-моментум, контроль buy&hold |
| Пари | `pairs/cointegration.py`, `pairs/ou.py`, `pairs/pairs_trading.py`, `pairs/params.py` | Коінтеграція (OLS + справжній ADF: t-відношення, квантили МакКіннона, лаги за BIC), процес О-У, торгівля спредом |
| Мікроструктура | `order_book.py`, `microstructure.py`, `vpin.py`, `hawkes.py` | Знімок книги, OBI/WOFI/fade, VPIN-кошики, інтенсивність Хоукса |
| ML-стратегії | `ml_classifier.py`, `ml_obi_strategy.py`, `formulaic_lgbm_strategy.py`, `meta_label_strategy.py` | Протокол класифікатора напрямку, ML-стратегія на OBI/WOFI, формульні ознаки + LightGBM, мета-мітка поверх первинного робота |
| Інші стратегії | `funding.py`, `glft.py`, `triangular_arb.py` | Funding cash-and-carry, GLFT-котировки, пошук від'ємних циклів |
| Крос-секційні | `xsmom.py`, `align.py`, `windowing.py` | Крос-секційний моментум, вирівнювання серій, вікна барів і прогрів |
| Позиція та виходи | `position_plan.py`, `marking.py`, `triple_barrier.py`, `ratchet_stop.py`, `drawdown_cooldown.py` | План утримання, маркування відкритих лотів, потрійний бар'єр, храповик-стоп, пауза після просадки |
| Офлайн-контур | `formulaic_alphas.py`, `factor_dsl.py`, `hypothesis.py` | 12 формульних ознак, DSL рецептів факторів, контракт гіпотези з лінтером вигаданих ознак |
| Ризик | `risk.py`, `risk_overlay.py`, `portfolio_risk.py`, `kill_switch.py` | Ліміти, оверлей (vol-scaling, Келлі, CVaR), Келлі, VaR/CVaR, вимикач |
| Методологія | `walk_forward.py`, `stress_slices.py`, `metrics.py`, `overfitting.py`, `deflated_sharpe.py`, `counterfactual.py` | Вікна IS/OOS, стрес-періоди, метрики, PBO/CSCV, дефльований Шарп, контрфактичні барами |

### `application/` — сценарії

| Модуль | Роль |
|--------|------|
| `dtos.py` | `BacktestRequest`, `BacktestReport`, `WalkForwardRequest/Report`, `SelectedParams`, `PaperSessionReport`, `OverfitAuditReport`, протоколи `ResearchBacktestPort`, `BarFeed`, `TickFeed`, `OrderBookFeed`, `PaperBacktestPort` |
| `run_research_backtest.py` | Один прогін на всій вибірці + перевірка мінімальної кількості барів |
| `run_walk_forward.py` | Повний цикл IS/OOS: підбір → один запуск на OOS → звіт; `execute_multi()` — N ковзних фолдів |
| `param_grid.py` | Сітка параметрів для кожного робота (окремі гілки для `pairs`, `vpin_momentum`, `formulaic_lgbm`, `meta_label`, `adaptive_ema`, `ema`; решта — спільна сітка) |
| `select_params.py` | `RunParamSelection` — підбір параметрів з holdout-вікном і embargo, окремо від walk-forward |
| `score.py` | Оцінка кандидата на in-sample (`ending_balance`) |
| `risk.py` | `size_position`, `stop_distance`, `evaluate_entry`, `effective_risk_fraction`, `require_simulated_mode` |
| `run_overfitting_audit.py` | Аудит перенавчання: матриця «блоки × конфігурації» → PBO/CSCV |
| `promotion_gate.py` | `evaluate_gate()` — ворота допуску: чи виміряна перевага над buy&hold, чи пройдено PBO-аудит |
| `ingest_historical_bars.py` | Завантажити klines і записати в каталог |
| `ingest_funding_history.py` | Завантажити ставки фандингу у `ParquetFundingCatalog` |
| `ingest_agg_trades.py` / `collect_live_agg_trades.py` | Агреговані угоди: історичний ingest і збір із живого потоку |
| `ingest_orderbook.py` | Знімки книги → `ParquetOrderBookCatalog` |
| `catalog_queries.py` | Запити до каталогу: хвіст серії, старт інкрементального ingest |
| `run_paper.py` | `RunPaperSession` — паперова сесія (рушій + журнал гіпотетичних філів); `RunPaperResearch` — лише прев'ю ордерів; `require_paper_support()` |
| `train_classifier.py` | Purged K-fold із embargo + розмітка напрямку (`up`/`down`/`flat`) |
| `train_formulaic.py` / `train_meta_label.py` / `train_obi.py` | Побудова датасету й тренування LightGBM для трьох ML-роботів |
| `xsmom_backtest.py` / `run_xsmom.py` | Крос-секційний моментум: бектест і walk-forward з PBO-аудитом |
| `evaluate_recipe.py` | Оцінка формульного рецепта (IC) на історії |
| `scan_triangular.py` | Сканер трикутних циклів (без виконання) |
| `journal.py` | Append-only журнал дослідження: рядок у `research/journal.md` + JSONL |
| `propose_alphas.py` / `run_alpha_proposal.py` | Офлайн-цикл пропозиції альф і його запуск як job для API |
| `optuna_optimizer.py` | `OptunaParamOptimizer` — байєсівський (TPE) підбір параметрів на in-sample замість сітки |

### `infrastructure/` — адаптери

| Модуль | Роль |
|--------|------|
| `settings.py` | Pydantic `Settings`, читання `.env` |
| `timeframe.py` | `1h` → `1-HOUR`, побудова `bar_type` |
| `binance_klines.py` | Публічний REST Binance, пагінація по 1000 свічок, `UrllibJsonClient` |
| `binance_funding.py` | Публічна історія ставок фінансування (fapi) |
| `binance_agg_trades.py` | Публічні агреговані угоди (REST) |
| `binance_orderbook.py` | `BinanceLiveOrderBook` — знімок книги |
| `binance_ws.py` | Публічний **WebSocket** Binance: `BinanceKlineStream` (закриті бари) і `BinanceAggTradeStream`; `ReconnectPolicy`, парсери повідомлень |
| `http_resilience.py` | `ResilientJsonClient` — вага лімітів, `Retry-After`, backoff |
| `agg_trades_catalog.py`, `orderbook_catalog.py`, `funding_catalog.py`, `taker_flow_catalog.py` | Parquet-каталоги окремих серій: тики, книга, фандинг, потік тейкерів |
| `live_bar_feed.py` | `SeededLiveBarFeed` — прогрів із історії + живі закриті бари |
| `live_paper_journal.py` | Журнал паперових сесій: знімки, філи, resume після рестарту |
| `paper_sessions.py` | `session_record()`, `append_session()` — реєстр завершених сесій для API |
| `lightgbm_classifier.py` | `LightGBMDirectionClassifier` (опційно) + `HeuristicDirectionClassifier` (fallback) |
| `egarch_forecast.py`, `vol_forecast.py` | EGARCH(1,1) через `arch` і вибір прогнозатора волатильності (HAR / EGARCH) |
| `llm_client.py` | `OpenAICompatibleChatClient` — чат-комплішени OpenAI-сумісного ендпоінта (офлайн-контур) |
| `alerts.py` | `AlertNotifier`, `NullAlertNotifier`, `TelegramAlertNotifier`, `WebhookAlertNotifier`, `CompositeAlertNotifier`, `build_notifier()` — сповіщення про завершення прогонів |
| `orderbook_microstructure.py` | Мікроструктура на Polars: `compute_order_book_imbalance()`, `compute_micro_price()`, `compute_microstructure_dataframe()` |
| `paper_trading.py` | `PaperTradingLogger` — журнал гіпотетичних ордерів |
| `nautilus/parquet_catalog.py` | Обгортка над `ParquetDataCatalog`: `write()`, `load()` |
| `nautilus/bar_feed.py` | `ResearchBarFeed`: каталог або синтетика, стрес-вікна, мульти-серії |
| `nautilus/bar_convert.py` | Доменний бар ↔ нативний `Bar` Nautilus |
| `nautilus/instrument.py` | Описи інструментів симуляції (`ETH/USDT.SIM`, `BTC/USDT.SIM`, `ETHUSDT-PERP.SIM`) |
| `nautilus/synthetic_bars.py` | Детерміновані синтетичні бари (random walk і «тренд-флет-тренд») |
| `nautilus/synthetic_pairs.py` | Синтетична коінтегрована пара для тестів |
| `nautilus/backtest_runner.py` | Налаштування й запуск `BacktestEngine` |
| `nautilus/signal_strategy.py` | `SignalRobot` — адаптер однолегової стратегії до Nautilus |
| `nautilus/spread_strategy.py` | `SpreadRobot` — адаптер двуногової стратегії |

### `api/` — веб-шар (FastAPI)

| Модуль | Роль |
|--------|------|
| `app.py` | Сам застосунок: усі роути `/api/*` (research, ingest, catalog, settings, ml, paper, scan, propose, journal, command-center), WebSocket `/api/paper/live-stream`, статичні монти `/static_reports` і `/static_hypotheses` |
| `security.py` | `ApiSecurity` — три ворота: `Origin`, токен `X-Lab-Token`, роль `LAB_ROLE` (`full` \| `paper`) |
| `market_feed.py` | `MarketFeed` / `FeedHub` — один сокет на `symbol+interval`, спільний для всіх сесій |
| `paper_streamer.py` | `LivePaperSessionManager` — жива паперова сесія: доменний робот, ризик, симульовані філи, смуга equity; `LIVE_PAPER_ROBOTS` |
| `live_sessions.py` | `SessionRegistry` — реєстр сесій, resume незавершених, ліміт кількості |
| `live_paper_boot.py` | Старт сесій із `.env` і з декларованого портфеля при піднятті застосунку |
| `paper_runner.py` | `execute_paper()` — batch-прогін паперової сесії як окремий job |
| `research_runner.py` | `ResearchJobConfig`, `execute_research()` — важкий прогін у дочірньому процесі |
| `run_research_job.py`, `run_paper_job.py`, `run_ml_job.py` | Точки входу дочірніх процесів (`python -m ...`), які запускає `app.py` |
| `ml_runner.py` | `execute_ml_train()` і `list_models()` |
| `catalog_service.py`, `data_health.py`, `command_center.py` | Опис каталогу, здоров'я даних, зведення для головного екрана |
| `experiment_history.py` | Архів прогонів у `reports/` |
| `journal_service.py` | Читання журналу й зміна ручного рішення |
| `serializers.py` | `Decimal` → JSON: метрики, walk-forward, PBO, дефльований Шарп |
| `settings_schema.py`, `settings_coerce.py` | Схема `.env` для UI, валідація і застосування оновлень |

### `interfaces/` — вхід

| Модуль | Роль |
|--------|------|
| `cli.py` | argparse-команди `ingest`, `research`, `paper`, `scan`, `propose`, `ml train`, `xsmom`, `live`; друк звітів |
| `composition.py` | Збірка залежностей: `settings()`, `catalog()`, `research_feed()`, `notifier()`, `*_use_case()`, `*_request()` |

## 5. Чому саме так (п'ять рішень, які варто розуміти)

**1. Стратегія не знає розміру позиції.**
Домен повертає лише напрямок. Розмір рахує `size_position()` з ризику і стопу.
Якщо дозволити стратегії самій вирішувати «скільки», з'являється спокуса підігнати розмір під історію — і весь walk-forward втрачає сенс.

**2. In-sample і out-of-sample — це різні прогони, а не один.**
`RunWalkForward` фізично запускає рушій двічі: спочатку багато разів на IS-барах (підбір),
потім **один раз** на OOS-барах (звіт). OOS-бари ніколи не потрапляють у цикл підбору.

**3. Живий режим відсікається на найнижчому рівні.**
`require_simulated_mode()` викликається і в use case, і в побудові запиту, і в CLI.
Тобто навіть програмний виклик у обхід CLI не зможе надіслати живий ордер: адаптера просто не існує.

**4. Робот без адаптера падає, а не підміняється.**
`require_backtest_support()` (перелік — `BACKTEST_WIRED_ROBOTS` у `domain/regime.py`) викликається
на вході в `RunResearchBacktest.execute()` і `RunWalkForward.execute()`, а також у `_build_robot()`.
Тому `--robot funding` дає помилку з кодом 1, а не тихий запуск `regime` з правдоподібним звітом.

**5. Веб-шар — це привід, а не друга реалізація.**
`api/` не має власної логіки стратегій чи метрик: він складає ті самі об'єкти
(`interfaces/composition.py`) і викликає ті самі use cases. Живий паперовий термінал
тримає **один** сокет на ринок (`market_feed.MarketFeed`) і роздає його всім сесіям,
щоб два роботи на одному символі бачили однакові бари. Важкі прогони винесені
в дочірні процеси (`api/run_*_job.py`), а сервер на VPS працює в ролі `LAB_ROLE=paper`,
яка забороняє все, крім читання й керування живими сесіями.

## 5.1 Відомі відхилення від правила шарів

Правило «стрілки лише всередину» виконується для `domain/` бездоганно, але не для
кожного модуля `application/`: частина use case імпортує адаптери напряму замість
протоколів `domain/ports.py`:

```
src/nautilus_lab/application/catalog_queries.py:7     from nautilus_lab.infrastructure.nautilus.instrument import ...
src/nautilus_lab/application/catalog_queries.py:8     from nautilus_lab.infrastructure.nautilus.parquet_catalog import ...
src/nautilus_lab/application/catalog_queries.py:9     from nautilus_lab.infrastructure.settings import Settings
src/nautilus_lab/application/catalog_queries.py:10    from nautilus_lab.infrastructure.timeframe import ...
src/nautilus_lab/application/ingest_orderbook.py:5    from nautilus_lab.infrastructure.binance_orderbook import ...
src/nautilus_lab/application/ingest_orderbook.py:6    from nautilus_lab.infrastructure.orderbook_catalog import ...
src/nautilus_lab/application/run_alpha_proposal.py:17 from nautilus_lab.infrastructure.settings import Settings
src/nautilus_lab/application/run_paper.py:45          from nautilus_lab.infrastructure.lightgbm_classifier import ...
src/nautilus_lab/application/run_paper.py:46          from nautilus_lab.infrastructure.paper_trading import ...
```

Це не «тиха» помилка — код працює — але такий модуль уже не можна тестувати підміною
протоколу. Крім того, `interfaces/cli.py` імпортує `infrastructure.settings`,
`infrastructure.paper_sessions` і `infrastructure.llm_client` безпосередньо, тож
`composition.py` — не єдина точка збірки залежностей (див. точний перелік у
[12-karta-fayliv.md](12-karta-fayliv.md)).

## 6. Далі

- UML-діаграми шарів, класів і сценаріїв → [uml/README.md](uml/README.md)
- Повний перелік файлів з описами → [12-karta-fayliv.md](12-karta-fayliv.md)
- Як додати свій шар у цю архітектуру → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
- Веб-дашборд і alpha proposer → [20-veb-dashbord-ta-alpha-proposer.md](20-veb-dashbord-ta-alpha-proposer.md)
- Паперовий термінал → [24-paper-treydynh.md](24-paper-treydynh.md)
- Розгортання на VPS (Docker Compose, Caddy) → [26-deploy-vps.md](26-deploy-vps.md)
