# 03. Архітектура: як усе з'єднано

Документ для тих, хто хоче розуміти код, а не лише запускати команди.

## 1. Чотири шари і одне правило

```
┌───────────────────────────────────────────────────────────────────────┐
│  interfaces/            CLI `lab`, збірка залежностей (composition)    │
│  знає про всі шари, єдина точка входу                                  │
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

Перевірити це можна однією командою:

```bash
grep -rn "nautilus_trader" src/nautilus_lab/domain/    # нічого не знайде
grep -rn "Settings" src/nautilus_lab/domain/           # нічого не знайде
```

## 2. Головні типи даних

Розуміння п'яти типів — це 80% розуміння коду.

### `OhlcvBar` — один закритий бар (`domain/bars.py`)

```python
OhlcvBar(
    instrument_id="ETH/USDT.SIM",
    ts_utc=datetime(..., tzinfo=UTC),   # час закриття бару, строго UTC
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
Signal(instrument_id="ETH/USDT.SIM", side=SignalSide.BUY, bar_ts_utc=..., reason="donchian breakout long")
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

## 4. Що робить кожен шар (детально)

### `domain/` — чиста логіка

| Підгрупа | Модулі | Роль |
|----------|--------|------|
| Базові типи | `bars.py`, `signals.py`, `errors.py`, `money.py`, `trading_mode.py`, `windows.py` | Бар, сигнал, помилки, гроші, режими, ковзне вікно |
| Індикатори | `ema.py`, `atr.py`, `windows.py`, `volatility.py` | EMA (з SMA-сідом), ATR Вайлдера, HAR-RV |
| Класифікація режиму | `regime.py` | `RegimeClassifier` (ER Кауфмана + нахил EMA + гістерезис), `RegimeParams`, `RobotName` |
| Стратегії | `donchian.py`, `mean_reversion.py`, `ema_crossover.py`, `regime_router.py` | Пробій, повернення до середнього, перетин EMA, маршрутизатор між ними |
| Пари | `pairs/cointegration.py`, `pairs/ou.py`, `pairs/pairs_trading.py`, `pairs/params.py` | Коінтеграція (OLS+спрощений ADF), процес О-У, торгівля спредом |
| Мікроструктура | `order_book.py`, `microstructure.py`, `vpin.py`, `hawkes.py`, `ml_obi_strategy.py` | Знімок книги, OBI/WOFI/fade, VPIN-кошики, інтенсивність Хоукса, ML-стратегія |
| Інші стратегії | `funding.py`, `glft.py`, `triangular_arb.py` | Funding cash-and-carry, GLFT-котировки, пошук від'ємних циклів |
| Ризик | `risk.py`, `portfolio_risk.py`, `kill_switch.py` | Ліміти, Келлі, VaR/CVaR, вимикач |
| Методологія | `walk_forward.py`, `stress_slices.py`, `metrics.py`, `align.py` | Вікна IS/OOS, стрес-періоди, метрики, вирівнювання серій |

### `application/` — сценарії

| Модуль | Роль |
|--------|------|
| `dtos.py` | `BacktestRequest`, `BacktestReport`, `WalkForwardRequest/Report`, `SelectedParams`, протоколи `ResearchBacktestPort`, `BarFeed` |
| `run_research_backtest.py` | Один прогін на всій вибірці + перевірка мінімальної кількості барів |
| `run_walk_forward.py` | Повний цикл IS/OOS: підбір → один запуск на OOS → звіт |
| `param_grid.py` | Сітка параметрів для кожного робота |
| `score.py` | Оцінка кандидата на in-sample (`ending_balance`) |
| `risk.py` | `size_position`, `stop_distance`, `evaluate_entry`, `effective_risk_fraction`, `require_simulated_mode` |
| `ingest_historical_bars.py` | Завантажити klines і записати в каталог |
| `run_paper.py` | Прогін у «паперовому» режимі: лог гіпотетичних ордерів |
| `train_classifier.py` | Purged K-fold із embargo + розмітка напрямку (`up`/`down`/`flat`) |
| `scan_triangular.py` | Сканер трикутних циклів (без виконання) |
| `optuna_optimizer.py` | `OptunaParamOptimizer` — байєсівський (TPE) підбір параметрів на in-sample замість сітки |

### `infrastructure/` — адаптери

| Модуль | Роль |
|--------|------|
| `settings.py` | Pydantic `Settings`, читання `.env` |
| `timeframe.py` | `1h` → `1-HOUR`, побудова `bar_type` |
| `binance_klines.py` | Публічний REST Binance, пагінація по 1000 свічок, `UrllibJsonClient` |
| `binance_funding.py` | Публічна історія ставок фінансування (fapi) |
| `lightgbm_classifier.py` | `LightGBMDirectionClassifier` (опційно) + `HeuristicDirectionClassifier` (fallback) |
| `egarch_forecast.py` | EGARCH(1,1) прогноз волатильності через `arch` (опційно) |
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

### `interfaces/` — вхід

| Модуль | Роль |
|--------|------|
| `cli.py` | argparse-команди `ingest`, `research`, `paper`, `scan`, `live`; друк звітів |
| `composition.py` | Збірка залежностей: `settings()`, `catalog()`, `notifier()`, `*_use_case()`, `*_request()` |

## 5. Чому саме так (три рішення, які варто розуміти)

**1. Стратегія не знає розміру позиції.**
Домен повертає лише напрямок. Розмір рахує `size_position()` з ризику і стопу.
Якщо дозволити стратегії самій вирішувати «скільки», з'являється спокуса підігнати розмір під історію — і весь walk-forward втрачає сенс.

**2. In-sample і out-of-sample — це різні прогони, а не один.**
`RunWalkForward` фізично запускає рушій двічі: спочатку багато разів на IS-барах (підбір),
потім **один раз** на OOS-барах (звіт). OOS-бари ніколи не потрапляють у цикл підбору.

**3. Живий режим відсікається на найнижчому рівні.**
`require_simulated_mode()` викликається і в use case, і в побудові запиту, і в CLI.
Тобто навіть програмний виклик у обхід CLI не зможе надіслати живий ордер: адаптера просто не існує.

## 6. Далі

- Повний перелік файлів з описами → [12-karta-fayliv.md](12-karta-fayliv.md)
- Як додати свій шар у цю архітектуру → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
