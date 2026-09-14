# 12. Карта файлів і публічного API

Довідник «де що лежить». Корисний, коли треба швидко знайти потрібну функцію або зрозуміти,
у якому шарі має жити новий код.

Правило шарів описано в [03-arhitektura.md](03-arhitektura.md).

---

## `domain/` — чиста логіка (без Nautilus, без мережі, без `.env`)

### Базові типи

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `bars.py` | `OhlcvBar`, `BarOrigin`, `validate_bar()` | Один закритий бар; перевірка UTC, OHLC-інваріантів, монотонності часу, відсутності майбутнього |
| `signals.py` | `Signal`, `SignalSide`, `LegIntent`, `SpreadSignal`, `QuoteIntent` | Наміри стратегій: однолегові, двуногові (спред) і котировки маркет-мейкера |
| `errors.py` | `DomainError`, `InvalidBarError`, `InvalidWindowError`, `CatalogEmptyError`, `InvalidRiskError`, `RobotNotWiredError`, `LiveTradingDisabledError`, `PaperTradingNotReadyError` | Помилки; політика fail-closed |
| `money.py` | `Money` | Негрошова сума (не від'ємна), `risk_amount(fraction)` |
| `trading_mode.py` | `TradingMode` | `RESEARCH` / `PAPER` / `LIVE` |
| `windows.py` | `RollingWindow` | Ковзне вікно закритих значень; `values()`, `prior()` (усе, крім щойно закритого бару — захист від look-ahead) |

### Індикатори та волатильність

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `ema.py` | `ExponentialMovingAverage` | EMA з SMA-сідом; `initialized`, `value`, `update(price)` |
| `atr.py` | `AverageTrueRange` | ATR на закритих барах (просте середнє справжніх діапазонів) |
| `volatility.py` | `HarRealizedVolatility`, `vol_scaled_risk_fraction()` | HAR-RV прогноз (денні/тижневі/місячні компоненти) і масштабування ризику під цільову волатильність |

### Класифікація режиму і стратегії

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `regime.py` | `MarketRegime`, `RobotName`, `BACKTEST_WIRED_ROBOTS`, `require_backtest_support()`, `RegimeParams`, `RegimeSnapshot`, `RegimeClassifier` | Класифікатор тренд/флет (ER Кауфмана + нахил EMA + гістерезис); перелік роботів і перевірка, чи має робот адаптер у рушії |
| `donchian.py` | `UptrendBreakout`, `DowntrendBreakout` | Пробій каналу Дончіана з виходом за EMA |
| `mean_reversion.py` | `RangeMeanReversion` | Повернення до середнього за смугами Боллінджера |
| `ema_crossover.py` | `EmaCrossover` | Класичний перетин EMA, завжди в ринку |
| `regime_router.py` | `RegimeRouter` | Класифікує бар → викликає відповідну стратегію; `FLAT` при зміні режиму; VPIN-фільтр |

### Пари (статистичний арбітраж)

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `pairs/params.py` | `PairsParams` | Ноги, lookback, `z_entry`/`z_exit`, ворота (half-life, ADF) |
| `pairs/cointegration.py` | `CointegrationResult`, `fit_cointegration()`, `critical_values()`, `p_value_from_statistic()` | OLS-хедж-коефіцієнт + **справжній ADF** на залишках: t-відношення коефіцієнта при `e_{t−1}`, критичні значення й p-value з квантилів МакКіннона (2010), порядок лагів за BIC. Поле `adf_lags` у `CointegrationResult` зберігає обраний лаг; `critical_values(nobs)` віддає три межі, `p_value_from_statistic(t, nobs)` — p-value |
| `pairs/ou.py` | `OuFit`, `fit_ou_half_life()`, `z_score()` | Дискретний фіт процесу О-У, період напіврозпаду, Z-оцінка |
| `pairs/pairs_trading.py` | `PairsTrading` | Сигнали входу/виходу по спреду + time stop |

### Мікроструктура та ML

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `order_book.py` | `BookLevel`, `OrderBookSnapshot` | Знімок книги; `validate()` ловить перехрещену/неправильно впорядковану книгу |
| `microstructure.py` | `order_book_imbalance()`, `weighted_order_flow_imbalance()`, `liquidity_fade_velocity()` | OBI, WOFI, швидкість зникнення ліквідності |
| `vpin.py` | `VpinState`, `BarVpin` | VPIN на барових кошиках рівного обсягу; `toxic` за порогом |
| `hawkes.py` | `HawkesIntensity`, `ExponentialHawkes` | Інтенсивність потоку угод (самозбудження), прапорець токсичності |
| `ml_classifier.py` | `DirectionProbabilities`, `DirectionClassifier` | Протокол класифікатора напрямку |
| `ml_obi_strategy.py` | `MlObiStrategy` | Сигнал за OBI/WOFI/fade із порогом імовірності |

### Інші стратегії

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `funding.py` | `FundingSnapshot`, `FundingParams`, `FundingCashAndCarry` | Дельта-нейтральний cash-and-carry (спот лонг + перп шорт) |
| `glft.py` | `GlftParams`, `GlftMarketMaker` | Котировки GLFT зі зсувом від інвентарю |
| `triangular_arb.py` | `FxEdge`, `TriangularOpportunity`, `find_negative_cycles()` | Беллман-Форд: пошук циклів від'ємної ваги |

### Ризик і методологія

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `risk.py` | `RiskLimits`, `AccountSnapshot`, `RiskDecision` | Жорсткі ліміти, стан рахунку, рішення про вхід |
| `portfolio_risk.py` | `fractional_kelly_cap()`, `historical_var()`, `historical_cvar()` | Фракційний Келлі, історичні VaR/CVaR |
| `kill_switch.py` | `KillSwitch`, `NoOpKillSwitch` | Протокол аварійної зупинки (у research — заглушка) |
| `metrics.py` | `BacktestMetrics`, `compute_metrics()`, `buy_and_hold_return()` | Комісії, максимальна просадка, оборот, `sharpe_like`; `buy_and_hold_return()` — дохідність простого утримання інструменту за вікно (планка для кожного фолда walk-forward) |
| `walk_forward.py` | `WalkForwardWindow`, `WalkForwardSplit`, `bars_in_range()`, `split_by_window()`, `anchored_window()`, `rolling_windows()` | Вікна IS/OOS, embargo, нарізка барів (без підглядання); `rolling_windows()` — N ковзних фолдів (вікно підбору зсувається на один OOS-блок уперед, останній фолд забирає остачу від ділення націло) |
| `stress_slices.py` | `StressSliceName`, `StressSlice`, `STRESS_SLICES`, `resolve_stress_slice()` | `covid2020`, `ftx2022`, `etf2024` |
| `align.py` | `align_bars_inner_join()`, `split_aligned_by_window()` | Вирівнювання кількох серій за часом (inner join) |
| `fees.py` | `FeeSchedule` | Розклад комісій; `binance_spot_vip0()`, `binance_usdm_vip0()` |
| `ports.py` | `PublicBarFeed`, `BarCatalog`, `JsonHttpClient`, `FundingRateFeed`, `OrderBookSnapshotFeed` | Протоколи, які реалізує infrastructure |

---

## `application/` — сценарії використання

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `dtos.py` | `BacktestRequest`, `BacktestReport`, `IngestRequest`, `IngestReport`, `WalkForwardRequest`, `WalkForwardReport`, `WalkForwardFold`, `MultiWindowReport`, `SelectedParams`, `ResearchBacktestPort`, `BarFeed`, `selected_from_request()`, `apply_selected()` | Усі структури даних; протоколи рушія й фіду; застосування підібраних параметрів. `WalkForwardFold` — один ковзний фолд; `MultiWindowReport` — агрегат OOS: `oos_returns`, `profitable_folds`, `mean_oos_return`, `median_oos_return`, `worst_oos_return`, `best_oos_return`, `mean_buy_and_hold_return`, `total_oos_fills`, `beats_buy_and_hold()` (`None`, коли щось із двох боків не вимірюється) і `summary_line()` |
| `run_research_backtest.py` | `RunResearchBacktest` | Один прогін; перевірка мінімуму барів (`_minimum_bars`) |
| `run_walk_forward.py` | `RunWalkForward` | Повний цикл IS/OOS із grid search; `_require_warmup()`; `execute_multi()` — багатовіконний прогін: окремий walk-forward на кожен фолд і агрегат OOS (відхиляє `folds < 2` і явне `window`; працює і для `pairs`) |
| `param_grid.py` | `iter_param_grid()` | Сітки: regime 6, ema 4, pairs 3 |
| `score.py` | `in_sample_score()` | Оцінка кандидата = `ending_balance` (відсутній → −1) |
| `risk.py` | `size_position()`, `stop_distance()`, `evaluate_entry()`, `effective_risk_fraction()`, `require_simulated_mode()` | Розмір позиції, стоп, запобіжники, Келлі-обмеження, заборона live |
| `ingest_historical_bars.py` | `IngestHistoricalBars` | Fetch → write у каталог; перевірки й звіт |
| `run_paper.py` | `RunPaperResearch` | Лог гіпотетичних ордерів (без рушія) |
| `train_classifier.py` | `PurgedFold`, `purged_k_fold()`, `label_direction()` | Purged K-fold із embargo і розмітка напрямку |
| `scan_triangular.py` | `scan_triangular_opportunities()` | Обгортка над пошуком циклів (fee на кожне ребро) |
| `optuna_optimizer.py` | `OptunaParamOptimizer` | Байєсівська оптимізація (TPE) на in-sample: `optimize(request, run_is)` → `(params, report, trials)` |

---

## `infrastructure/` — адаптери

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `settings.py` | `Settings` | Pydantic-конфіг із `.env`; `risk_limits()`, `fee_schedule()`, `regime_params()`, `pairs_params()` |
| `timeframe.py` | `NAUTILUS_BAR_SPEC`, `nautilus_bar_type()` | `1h` → `1-HOUR`, побудова `bar_type` |
| `binance_klines.py` | `BinancePublicKlines`, `UrllibJsonClient`, `parse_binance_kline()` | Публічний REST klines із пагінацією |
| `binance_funding.py` | `BinancePublicFunding` | Історія ставок фінансування (fapi) |
| `lightgbm_classifier.py` | `HeuristicDirectionClassifier`, `LightGBMDirectionClassifier` | Rule-based fallback і опційний LightGBM |
| `egarch_forecast.py` | `egarch_forecast_volatility()` | EGARCH(1,1) через `arch`; `None`, якщо недоступно |
| `alerts.py` | `AlertNotifier`, `NullAlertNotifier`, `TelegramAlertNotifier`, `WebhookAlertNotifier`, `CompositeAlertNotifier`, `build_notifier()` | Сповіщення про завершення прогону; `httpx`, fail-safe |
| `orderbook_microstructure.py` | `compute_order_book_imbalance()`, `compute_micro_price()`, `compute_microstructure_dataframe()` | Мікроструктура на float/Polars (векторні обчислення), окремо від доменної версії на `Decimal` |
| `paper_trading.py` | `PaperOrderLog`, `PaperTradingLogger` | Журнал гіпотетичних ордерів |
| `nautilus/parquet_catalog.py` | `NautilusParquetCatalog` | `write()`, `load()`; валідація кожного бару; `write()` спершу **видаляє перекритий діапазон** (`delete_data_range`) — повторний ingest замінює вікно, а не додає другий файл; `load()` дедуплікує за `ts_utc` (останнє входження) і сортує за часом, тому старі каталоги лишаються читабельними |
| `nautilus/bar_feed.py` | `ResearchBarFeed` | Каталог або синтетика; `load()`, `load_multi()`; стрес-вікна; inner-join |
| `nautilus/bar_convert.py` | `to_engine_bars()`, `to_domain_bar()`, `datetime_to_nanos()`, `nanos_to_datetime()` | Доменний бар ↔ нативний `Bar` |
| `nautilus/instrument.py` | `resolve_instrument()`, `binance_symbol_to_instrument_id()`, `eth_usdt_sim()`, `btc_usdt_sim()`, `eth_usdt_perp_sim()` | Описи інструментів симуляції |
| `nautilus/synthetic_bars.py` | `synthetic_ohlcv()`, `synthetic_regime_ohlcv()` | Детерміновані синтетичні бари (random walk; тренд-флет-тренд) |
| `nautilus/synthetic_pairs.py` | `synthetic_cointegrated_pair()` | Синтетична коінтегрована пара для тестів |
| `nautilus/backtest_runner.py` | `NautilusResearchBacktest` | Налаштування `BacktestEngine` (венʼю SIM, комісії, затримка, проковзування); `run()`, `run_spread()` |
| `nautilus/signal_strategy.py` | `SignalRobotConfig`, `SignalRobot`, `_build_robot()` | Адаптер однолегової стратегії: сигнал → ризик → ордер |
| `nautilus/spread_strategy.py` | `SpreadRobotConfig`, `SpreadRobot` | Адаптер двуногової стратегії (pairs) |

---

## `interfaces/` — вхід у застосунок

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `cli.py` | `main()`, `parse_utc()` | argparse-команди `ingest`, `research`, `paper`, `scan`, `live`; друк звітів |
| `composition.py` | `settings()`, `catalog()`, `research_use_case()`, `walk_forward_use_case()`, `ingest_use_case()`, `research_request()`, `ingest_request()`, `walk_forward_request()` | Єдина точка збірки залежностей |

---

## Тести

| Файл | Що покриває |
|------|-------------|
| `conftest.py` | Фікстура `default_limits` (RiskLimits) і хелпер `make_bars(count, start, step_minutes)` |
| `unit/test_bars.py` | Валідація OHLCV, UTC, монотонність, майбутні бари |
| `unit/test_binance_klines.py` | Парсинг kline, пагінація, помилкові відповіді |
| `unit/test_cli.py` | `live` fail-closed, `paper` працює, часткові дати → код 1, `parse_utc`, роботи без адаптера (`funding`/`ml_obi`/`glft`/`tri_scan`) → код 1 |
| `unit/test_cointegration.py` | ADF-ворота `pairs`: коінтегрована пара проходить, два незалежні random walk — ні; статистика є **t-відношенням**, а не сирим коефіцієнтом; критичні значення збігаються з МакКінноном; p-value рівно 0.05 у 5%-точці й монотонна за статистикою; білий шум обирає 0 лагів; детермінізм; валідація входу |
| `unit/test_donchian.py` | Пробої вгору/вниз, вихід за EMA, відсутність підглядання |
| `unit/test_ema_crossover.py` | Прогрів, перетин, валідація періодів |
| `unit/test_ingest.py` | Use case ingest: fetch → write, порожня відповідь → помилка |
| `unit/test_mean_reversion.py` | Смуги, вихід у середину, нульова дисперсія |
| `unit/test_mft_modules.py` | Великий набір: комісії, align, коінтеграція+О-У, VPIN, funding, HAR-RV, OBI, трикутний сканер, GLFT, метрики, Келлі/VaR, purged K-fold, стресові слайси, ATR, vol-scaling |
| `unit/test_money.py` | Від'ємні суми, `risk_amount` |
| `unit/test_param_grid.py` | Розміри сіток для кожного робота |
| `unit/test_regime_classifier.py` | ER, нахил, гістерезис, прогрів |
| `unit/test_regime_router.py` | Маршрутизація режимів, `FLAT` при зміні |
| `unit/test_risk.py` | `size_position`, `stop_distance`, `evaluate_entry`, Келлі, VaR, live-заборона |
| `unit/test_run_walk_forward.py` | Вибір параметрів на IS, звіт на OOS, embargo; `execute_multi()`: окремий walk-forward на кожен фолд, зсув вікна підбору, відмова при `folds < 2` і при явному вікні |
| `unit/test_synthetic_bars.py` | Детермінованість, валідність, структура режимів |
| `unit/test_walk_forward.py` | Вікна, нарізка, overlap-помилки; `rolling_windows()`: ковзне вікно підбору з точними очікуваними межами (100 барів, `folds=4`, `fraction=0.5`, `embargo=2` → IS `[0:50]`, OOS `[52:64]`), розрив embargo, досягання останнього бару, відсутність перекриття IS/OOS, відмова при забагато фолдів / поганій частці / нулі фолдів |
| `unit/test_multi_window_report.py` | Агрегат `MultiWindowReport`: арифметика середнього/медіани/найгіршого/найкращого, порівняння з buy&hold, шлях «невідомо» (коли один бік не вимірюється) і рядок `summary_line()` |
| `unit/test_optuna_optimizer.py` | Оптимізатор Optuna: кількість trials, вибір параметрів для кожного робота |
| `unit/test_alerts.py` | Нотифікатори: успіх, HTTP-помилка, виняток, композиція (з моками `httpx`) |
| `unit/test_orderbook_microstructure.py` | OBI (скаляр і список рівнів), micro-price, Polars-трансформація |
| `integration/test_research_backtest.py` | Реальний рушій Nautilus: синтетичний прогін, roundtrip каталогу, pairs, порожній каталог → fail closed; повторний ingest перекритого вікна замінює дані, а не дублює їх; `load()` дедуплікує каталог, у якому вже лежать перекриті файли |
| `integration/test_tearsheet_generation.py` | Генерація HTML-тиршита: файл створюється, непорожній, шлях повертається у звіті |

Запуск:

```bash
uv run pytest                                      # усі 167 тестів
uv run pytest tests/unit -q                        # лише швидкі
uv run pytest tests/integration -q                 # лише рушій (локально, без мережі)
uv run pytest --cov --cov-report=term-missing      # з покриттям (порог 80%; поточне — 83.70%)
```

---

## Кореневе

| Файл | Призначення |
|------|-------------|
| `README.md` | Короткий вступ і швидкий старт |
| `Стратегії MFT Криптоторгівлі 2026.md` | Вихідний дослідницький документ: ідеї, математика, інфраструктура, податки |
| `docs/` | Ця документація |
| `pyproject.toml` | Залежності, extras (`dev`, `ml`, `research`, `visualization`, `alerts`), налаштування ruff/mypy/pytest/coverage |
| `.env.example` | Шаблон усіх змінних з коментарями |
| `.env` | Ваші локальні налаштування (у `.gitignore`) |
| `uv.lock` | Зафіксовані версії залежностей |
| `catalog/` | Parquet-каталог даних (у `.gitignore`) |

---

## Куди додавати новий код

| Що додаєте | Куди | Чому |
|------------|------|------|
| Нову стратегію (логіку сигналів) | `domain/` | Чистий код без I/O — швидкі тести |
| Нове джерело даних | `infrastructure/` + протокол у `domain/ports.py` | Домен не знає про конкретну біржу |
| Новий сценарій («зроби X із даними») | `application/` | Оркестрація без деталей I/O |
| Нову команду CLI | `interfaces/cli.py` + `composition.py` | Точка входу і збірка залежностей |
| Нову метрику звіту | `domain/metrics.py` | Одна формула — одне місце |
| Новий запобіжник ризику | `application/risk.py::evaluate_entry` + `domain/risk.py::RiskLimits` | Уся політика ризику в одному місці |
| Сповіщення про подію | `infrastructure/alerts.py` (новий нотифікатор) + `composition.notifier()` | Один протокол `notify(message, level)` для всіх каналів |
| Новий спосіб підбору параметрів | `application/` (поряд із `param_grid.py` та `optuna_optimizer.py`) | `RunWalkForward` викликає їх через єдиний інтерфейс `run_is` |

## Куди йти далі

- Створити свою стратегію → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
- Повернутися до змісту → [README.md](README.md)
