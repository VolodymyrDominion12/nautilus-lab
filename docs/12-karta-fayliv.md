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
| `errors.py` | `DomainError`, `InvalidBarError`, `InvalidWindowError`, `CatalogEmptyError`, `InvalidRiskError`, `RobotNotWiredError`, `InvalidHypothesisError`, `LiveTradingDisabledError`, `PaperTradingNotReadyError` | Помилки; політика fail-closed. `InvalidHypothesisError` — лише офлайн-контур пропозицій альф |
| `money.py` | `Money` | Негрошова сума (не від'ємна), `risk_amount(fraction)` |
| `trading_mode.py` | `TradingMode` | `RESEARCH` / `PAPER` / `LIVE` |
| `ticks.py` | `AggTrade` | Одна агрегована угода з публічного потоку: `instrument_id`, `ts_utc`, `agg_id`, `price`/`qty` (рядки — точне десяткове подання Binance), `is_buyer_maker`; властивості `is_aggressive_buy/sell` |
| `windows.py` | `RollingWindow` | Ковзне вікно закритих значень; `values()`, `prior()` (усе, крім щойно закритого бару — захист від look-ahead) |
| `windowing.py` | `bar_span()`, `within_bars()`, `warmup_tail()` | Межі серії барів, вибірка подій усередині вікна, хвіст для прогріву індикаторів |

### Індикатори та волатильність

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `ema.py` | `ExponentialMovingAverage` | EMA з SMA-сідом; `initialized`, `value`, `update(price)` |
| `atr.py` | `AverageTrueRange` | ATR на закритих барах (просте середнє справжніх діапазонів) |
| `volatility.py` | `HarRealizedVolatility`, `vol_scaled_risk_fraction()` | HAR-RV прогноз (денні/тижневі/місячні компоненти) і масштабування ризику під цільову волатильність |
| `quantiles.py` | `empirical_quantile()` | Емпіричний квантиль на `Decimal` — база для VaR/CVaR, без numpy |

### Класифікація режиму і стратегії

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `regime.py` | `MarketRegime`, `RobotName`, `BACKTEST_WIRED_ROBOTS`, `TICK_VPIN_ROBOTS`, `HAWKES_ROBOTS`, `require_backtest_support()`, `tick_filters_supported()`, `RegimeParams`, `RegimeSnapshot`, `RegimeClassifier` | Класифікатор тренд/флет (ER Кауфмана + нахил EMA + гістерезис); перелік роботів і перевірка, чи має робот адаптер у рушії. `TICK_VPIN_ROBOTS` / `HAWKES_ROBOTS` — роботи, чий режимний фільтр читає тикову серію, коли увімкнено `use_tick_vpin` / `hawkes` |
| `donchian.py` | `UptrendBreakout`, `DowntrendBreakout` | Пробій каналу Дончіана з виходом за EMA |
| `mean_reversion.py` | `RangeMeanReversion` | Повернення до середнього за смугами Боллінджера |
| `ema_crossover.py` | `EmaCrossover` | Класичний перетин EMA, завжди в ринку |
| `regime_router.py` | `RegimeRouter` | Класифікує бар → викликає відповідну стратегію; `FLAT` при зміні режиму; VPIN-фільтр |
| `adaptive_ema.py` | `AdaptiveEmaParams`, `AdaptiveEma`, `AdaptiveEmaSnapshot`, `AdaptiveEmaRouter`, `efficiency_ratio_of()` | Селективне згладжування (скалярна форма ідеї Mamba): крок EMA залежить від efficiency ratio, `selectivity=0` відтворює сталий крок тотожно. Той самий роутер і ті самі ноги, що в `regime` — єдиною змінною експерименту лишається фільтр |
| `vpin_momentum.py` | `VpinMomentum` | Моментум у напрямку інформованого (токсичного) потоку + трейлінг-стоп за ATR; `min_hold_bars` забороняє виходити надто рано |
| `buy_and_hold.py` | `BuyAndHold`, `HOLD_ROBOT` | Контрольний робот «купив і тримає»: просить лонг на кожному закритому барі — планка для порівняння з будь-яким паперовим результатом (у живому терміналі — робот `hold`) |

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
| `ml_classifier.py` | `DirectionProbabilities`, `DirectionClassifier`, `SuccessClassifier` | Протоколи класифікатора напрямку і класифікатора успіху (мета-мітка) |
| `ml_obi_strategy.py` | `MlObiStrategy` | Сигнал за OBI/WOFI/fade із порогом імовірності |
| `formulaic_lgbm_strategy.py` | `FormulaicLgbmStrategy` | Сигнал за бустером на формульних ознаках із порогом імовірності |
| `meta_label_strategy.py` | `MetaLabelStrategy`, `PrimaryRobot`, `encode_meta_features()` | Мета-мітка: первинний робот пропонує бік, класифікатор підтверджує або відкидає вхід |
| `formulaic_alphas.py` | `FEATURE_NAMES`, `MIN_HISTORY`, `FormulaicAlphaEngine` | 12 формульних ознак на закритих барах (WorldQuant-style). `FEATURE_NAMES` — публічний контракт порядку ознак: на нього спираються промпти, валідація гіпотез і набір для LightGBM, тому нова ознака не може тихо зламати схему |
| `hypothesis.py` | `Hypothesis`, `parse_hypotheses()`, `unknown_identifiers()`, `rejected_names()`, `ALLOWED_FORMULA_FUNCTIONS`, `MAX_HORIZON_BARS` | Контракт гіпотези з офлайн-контуру: обов'язкові поля, межі горизонту, нормалізація знаку, і **лінтер вигаданих ознак** — токени формули, яких немає ні серед `FEATURE_NAMES`, ні серед дозволених функцій |

### Інші стратегії

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `funding.py` | `FundingSnapshot`, `FundingParams`, `FundingCashAndCarry` | Дельта-нейтральний cash-and-carry (спот лонг + перп шорт) |
| `glft.py` | `GlftParams`, `GlftMarketMaker` | Котировки GLFT зі зсувом від інвентарю |
| `triangular_arb.py` | `FxEdge`, `TriangularOpportunity`, `find_negative_cycles()` | Беллман-Форд: пошук циклів від'ємної ваги |

### Крос-секційні роботи, план позиції та виходи

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `xsmom.py` | `Weighting`, `XsMomParams`, `momentum_score()`, `realized_vol()`, `target_weights()` | Крос-секційний моментум: оцінка за lookback зі скіпом, обернено-волатильні ваги, обмеження `top_n` |
| `position_plan.py` | `Holding`, `PositionPlan`, `holding_from_signed_qty()`, `plan_for_signal()` | Що сигнал означає для **уже наявної** позиції: `exit_position` (вихід не питає ризик — інакше відмова заморожує збиткову позицію) і `wants_entry` (лише це проходить крізь `evaluate_entry`) |
| `marking.py` | `OpenLot`, `lot_unrealized_pnl()`, `unrealized_pnl()`, `marked_equity()` | Маркування відкритих лотів за ціною для equity, що враховує нереалізоване |
| `triple_barrier.py` | `BarrierTouch`, `TripleBarrierConfig`, `TripleBarrierOutcome`, `rolling_volatility()`, `label_triple_barrier()` | Розмітка «потрійним бар'єром» (тейк / стоп / час) для ML-датасетів |
| `ratchet_stop.py` | `RatchetParams`, `RatchetState`, `initial_ratchet()`, `update_ratchet()`, `ratchet_hit()`, `step_ratchet()` | Храповик-стоп: рівень лише підтягується за ціною, ніколи не відпускається |
| `drawdown_cooldown.py` | `PeakState`, `on_refusal()`, `advance()`, `DRAWDOWN_REASON` | Кулдаун після спрацювання просадки: пік перебазовується на поточний equity через N днів блокування, щоб перервана просадка не глушила торгівлю до кінця історії (`0` — стара постійна поведінка) |

### Ризик і методологія

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `risk.py` | `RiskLimits`, `AccountSnapshot`, `RiskDecision` | Жорсткі ліміти, стан рахунку, рішення про вхід |
| `risk_overlay.py` | `RiskOverlay` | Опційні надбудови над лімітами: vol-scaling, дробовий Келлі, CVaR-вимикач |
| `portfolio_risk.py` | `fractional_kelly_cap()`, `historical_var()`, `historical_cvar()` | Фракційний Келлі, історичні VaR/CVaR |
| `kill_switch.py` | `KillSwitch`, `NoOpKillSwitch` | Протокол аварійної зупинки (у research — заглушка) |
| `metrics.py` | `SelectionMetric`, `BacktestMetrics`, `compute_metrics()`, `breakeven_cost()`, `buy_and_hold_return()` | Комісії, максимальна просадка, оборот, `sharpe_like`; `breakeven_cost()` — який результат потрібен, щоб лише покрити витрати; `buy_and_hold_return()` — дохідність простого утримання інструменту за вікно (планка для кожного фолда walk-forward) |
| `walk_forward.py` | `WalkForwardWindow`, `WalkForwardSplit`, `bars_in_range()`, `split_by_window()`, `anchored_window()`, `rolling_windows()` | Вікна IS/OOS, embargo, нарізка барів (без підглядання); `rolling_windows()` — N ковзних фолдів (вікно підбору зсувається на один OOS-блок уперед, останній фолд забирає остачу від ділення націло) |
| `overfitting.py` | `CscvResult`, `probability_of_backtest_overfitting()` | PBO/CSCV: із матриці `блоки × конфігурації` рахує частку симетричних розбиттів, де переможець in-sample упав у нижню половину out-of-sample. Дошка розбиттів, де всі конфігурації рівні, **пропускається** (нічия не обирає нічого), тому неінформативна матриця дає `undefined`, а не «PBO=1» |
| `stress_slices.py` | `StressSliceName`, `StressSlice`, `STRESS_SLICES`, `resolve_stress_slice()` | `covid2020`, `ftx2022`, `etf2024` |
| `align.py` | `align_bars_inner_join()`, `split_aligned_by_window()` | Вирівнювання кількох серій за часом (inner join) |
| `fees.py` | `FeeSchedule` | Розклад комісій; `binance_spot_vip0()`, `binance_usdm_vip0()` |
| `ports.py` | `PublicBarFeed`, `BarCatalog`, `JsonHttpClient`, `JsonTransport`, `JsonResponse`, `FundingRateFeed`, `FundingCatalog`, `TakerFlowCatalog`, `OrderBookSnapshotFeed`, `AggTradesFeed`, `AggTradesCatalog`, `ChatCompleter` | Протоколи, які реалізує infrastructure. `ChatCompleter` — **лише офлайн-дослідження**: жодна стратегія не має залежати від нього |

---

## `application/` — сценарії використання

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `dtos.py` | `BacktestRequest`, `BacktestReport`, `IngestRequest`, `IngestReport`, `IngestAggTradesRequest/Report`, `FundingIngestRequest/Report`, `WalkForwardRequest`, `WalkForwardReport`, `WalkForwardFold`, `MultiWindowReport`, `SelectedParams`, `OverfitAuditRequest`, `OverfitAuditReport`, `PaperFill`, `PaperPosition`, `PaperSessionReport`, `ResearchBacktestPort`, `PaperBacktestPort`, `BarFeed`, `TickFeed`, `OrderBookFeed`, `selected_from_request()`, `apply_selected()`, `index_of_best_configuration()` | Усі структури даних; протоколи рушія й фідів; застосування підібраних параметрів. `WalkForwardFold` — один ковзний фолд; `MultiWindowReport` — агрегат OOS: `oos_returns`, `profitable_folds`, `mean_oos_return`, `median_oos_return`, `worst_oos_return`, `best_oos_return`, `mean_buy_and_hold_return`, `total_oos_fills`, `beats_buy_and_hold()` (`None`, коли щось із двох боків не вимірюється) і `summary_line()` |
| `run_research_backtest.py` | `RunResearchBacktest` | Один прогін; перевірка мінімуму барів (`_minimum_bars`) |
| `run_walk_forward.py` | `RunWalkForward` | Повний цикл IS/OOS із grid search; `_require_warmup()`; `execute_multi()` — багатовіконний прогін: окремий walk-forward на кожен фолд і агрегат OOS (відхиляє `folds < 2` і явне `window`; працює і для `pairs`) |
| `run_walk_forward.py` (там же) | `window_return()` | Дохідність одного вікна за `starting_equity`. Публічна, бо CLI записує в журнал OOS-число єдиного спліту за тим самим означенням, що й ковзні фолди |
| `param_grid.py` | `iter_param_grid()` | Сітки: `pairs` 3, `vpin_momentum` 3, `formulaic_lgbm` 3, `meta_label` 3, `adaptive_ema` 9 (3 періоди × 3 selectivity), `ema` 4, решта — спільна сітка 6 (3 періоди Дончіана × 2 коефіцієнти Боллінджера) |
| `select_params.py` | `ParamSelection`, `RunParamSelection` | Підбір параметрів з окремим holdout-вікном і embargo — окремо від walk-forward, щоб вибір і звіт не змішувались |
| `score.py` | `in_sample_score()` | Оцінка кандидата = `ending_balance` (відсутній → −1) |
| `risk.py` | `size_position()`, `stop_distance()`, `evaluate_entry()`, `effective_risk_fraction()`, `require_simulated_mode()` | Розмір позиції, стоп, запобіжники, Келлі-обмеження, заборона live |
| `catalog_queries.py` | `bar_interval_to_timedelta()`, `catalog_tail()`, `incremental_ingest_start()` | Запити до каталогу: скільки барів уже є і звідки продовжувати ingest |
| `ingest_historical_bars.py` | `IngestHistoricalBars` | Fetch → write у каталог; перевірки й звіт |
| `ingest_funding_history.py` | `IngestFundingHistory` | Fetch ставок фандингу → `ParquetFundingCatalog`; звіт містить `missing_index_price` (скільки розрахунків лишилось без індексу) |
| `ingest_agg_trades.py` | `IngestAggTrades`, `utc_slices()` | Історичний ingest агрегованих угод вікнами → `ParquetAggTradesCatalog` |
| `collect_live_agg_trades.py` | `LiveAggTradeSource`, `LiveTickReport`, `CollectLiveAggTrades` | Збір тиків із живого потоку в той самий каталог |
| `ingest_orderbook.py` | `IngestOrderBook` | Знімки книги → `ParquetOrderBookCatalog` |
| `run_paper.py` | `RunPaperSession`, `RunPaperResearch`, `PAPER_SUPPORTED_ROBOTS`, `require_paper_support()` | `RunPaperSession` — паперова сесія на рушії (філи, equity, журнал); `RunPaperResearch` — лише прев'ю «які ордери були б», без рахунку й PnL |
| `run_overfitting_audit.py` | `RunOverfitAudit`, `BlockRunner` | Аудит перенавчання: ріже історію на `blocks` послідовних блоків, проганяє кожну конфігурацію сітки на кожному блоці (окремо для однолегових роботів і для `pairs` — там усі ноги ріжуться за однаковими індексами), будує матрицю й віддає її в `probability_of_backtest_overfitting()` |
| `promotion_gate.py` | `WalkForwardEvidence`, `CheckStatus`, `GateCriteria`, `GateCheck`, `GateVerdict`, `evaluate_gate()` | Ворота допуску: перевіряють, що перевага над buy&hold виміряна, а PBO-аудит пройдено, перш ніж робот потрапить у paper |
| `evaluate_recipe.py` | `RecipeScore`, `feature_rows()`, `score_recipe()`, `pearson()` | Оцінка формульного рецепта на історії (IC та пов'язані метрики) |
| `xsmom_backtest.py` | `XsMomRun`, `run_xsmom()`, `require_aligned()` | Бектест крос-секційного моментуму з ребалансуванням і витратами |
| `run_xsmom.py` | `XsMomGrid`, `XsMomRequest`, `XsMomFold`, `XsMomWalkForwardReport`, `run_xsmom_walk_forward()`, `run_xsmom_audit()` | Walk-forward і PBO-аудит для `lab xsmom` |
| `train_classifier.py` | `PurgedFold`, `purged_k_fold()`, `label_direction()` | Purged K-fold із embargo і розмітка напрямку |
| `train_formulaic.py` | `FormulaicDataset`, `FormulaicTrainReport`, `build_formulaic_dataset()`, `train_formulaic_lightgbm()` | Датасет на формульних ознаках і тренування бустера для `formulaic_lgbm` |
| `train_meta_label.py` | `MetaLabelDataset`, `MetaLabelTrainReport`, `build_meta_label_dataset()`, `train_meta_label_lightgbm()` | Датасет мета-мітки (успіх/невдача первинного входу) і тренування |
| `train_obi.py` | `ObiDataset`, `ObiTrainReport`, `build_obi_dataset()`, `train_obi_lightgbm()` | Датасет на OBI/WOFI і тренування бустера для `ml_obi` |
| `scan_triangular.py` | `scan_triangular_opportunities()` | Обгортка над пошуком циклів (fee на кожне ребро) |
| `journal.py` | `JournalEntry`, `record_run()`, `append_row()`, `append_record()`, `load_records()`, `ROWS_START`, `ROWS_END`, `PENDING`/`ACCEPTED`/`REJECTED`/`RERUN` | Append-only журнал дослідження: рядок у `research/journal.md` + JSON у `research/journal.jsonl`. Існуючі рядки не переписуються (ручне рішення переживає наступний прогін), а без маркерів `journal:rows:start/end` запис падає з `JournalFormatError`, а не вгадує місце |
| `propose_alphas.py` | `AlphaProposalRequest`, `AlphaProposalRun`, `SYSTEM_PROMPT`, `load_prompt_template()`, `render_prompt()`, `extract_json_block()`, `propose_alphas()`, `write_artifact()`, `artifact_slug()`, `summarise()`, `endpoint_host_of()` | Офлайн-цикл пропозиції альф: шаблон + 12 ознак + дата відсічення → один виклик моделі → валідація за контрактом гіпотези → JSON-артефакт із provenance (модель, хеш промпту, as-of, сира відповідь, блок `review` зі `status: pending`). Ключів в артефакті немає — лише хост |
| `run_alpha_proposal.py` | `ProposeJobConfig`, `execute_propose()` | Обгортка `lab propose` / `POST /api/propose` як один job із результатом для API |
| `optuna_optimizer.py` | `OptunaParamOptimizer` | Байєсівська оптимізація (TPE) на in-sample: `optimize(request, run_is)` → `(params, report, trials)`. Окремі гілки простору пошуку для `pairs`, `ema`, `vpin_momentum`, `formulaic_lgbm`, `meta_label`, `adaptive_ema`; `regime` (і будь-який інший робот) іде гілкою за замовчуванням. Там `exit_trend_er` обмежений зверху через `enter_trend_er`, бо `RegimeParams` вимагає `enter > exit` — інакше третина trials гинула на інваріанті й нічого не вчила семплер |

---

## `infrastructure/` — адаптери

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `settings.py` | `Settings` | Pydantic-конфіг із `.env`; `risk_limits()`, `fee_schedule()`, `regime_params()`, `adaptive_ema_params()`, `pairs_params()`, `risk_overlay()`, `all_catalog_paths()`; роль застосунку `LAB_ROLE` (`full` \| `paper`) і токен `API_TOKEN` |
| `timeframe.py` | `NAUTILUS_BAR_SPEC`, `nautilus_bar_type()`, `interval_from_bar_type()` | `1h` → `1-HOUR`, побудова `bar_type`; `interval_from_bar_type()` — обернена функція, шукає специфікацію як **цілий сегмент** `-SPEC-` (підрядковий пошук читав `15-MINUTE` як `5-MINUTE`) |
| `binance_klines.py` | `BinancePublicKlines`, `UrllibJsonClient`, `parse_binance_kline()` | Публічний REST klines із пагінацією |
| `http_resilience.py` | `ResilientJsonClient`, `UrllibJsonTransport`, `RateLimitPolicy`, `parse_used_weight()`, `parse_retry_after()` | Керування лімітами: читає `X-MBX-USED-WEIGHT-1M` і вичікує вікно при ≥90% ліміту, поважає `Retry-After` на 429, повторює 418/5xx з backoff, кидає `RateLimitedError` замість обрізаної серії; неретрайний статус → `MarketDataError` |
| `binance_funding.py` | `BinancePublicFunding` | Історія ставок фінансування (fapi) з пагінацією понад стелю 1000 розрахунків; `index_price` джойниться з `indexPriceKlines` за годиною розрахунку і лишається `None`, якщо не зійшовся |
| `binance_agg_trades.py` | `BinancePublicAggTrades` | Публічні агреговані угоди (REST) з пагінацією; парсер рядка → `AggTrade` |
| `binance_orderbook.py` | `BinanceLiveOrderBook` | Знімок книги замовлень із публічного ендпоінта |
| `binance_ws.py` | `BinanceKlineStream`, `BinanceAggTradeStream`, `parse_kline_message()`, `parse_agg_trade_message()`, `binance_stream_url()`, `agg_trade_stream_url()`, `ReconnectPolicy`, `KlinePayloadError`, `KlineStreamUnavailableError` | Публічний **WebSocket** Binance: закриті klines і потік aggTrades; політика перепідключення з backoff, парсери відкидають незакриті бари |
| `funding_catalog.py` | `ParquetFundingCatalog` | Parquet-серія фандингу в `<catalog>/data/funding/<SYMBOL>/`; злиття за часом розрахунку (ідемпотентно), `Decimal` зберігається рядком, запис через `os.replace` |
| `agg_trades_catalog.py` | `ParquetAggTradesCatalog` | Parquet-серія агрегованих угод; round-trip `AggTrade` без втрати точності |
| `orderbook_catalog.py` | `ParquetOrderBookCatalog` | Parquet-серія знімків книги замовлень |
| `taker_flow_catalog.py` | `ParquetTakerFlowCatalog` | Parquet-серія тейкерського потоку: `takerBuyBaseAssetVolume` з kline, яке не переживає round-trip через нативний `Bar` Nautilus. Окрема серія на `(symbol, interval)`, `Decimal` збережено рядком |
| `live_bar_feed.py` | `LiveBarSource`, `LiveCollectionResult`, `LiveBarCollector`, `SeededLiveBarFeed` | Прогрів із історії + живі закриті бари: робот починає не «холодним» |
| `live_paper_journal.py` | `LivePaperJournal`, `ResumableSession`, `SessionRecord` | Журнал паперових сесій: знімки, філи, resume після рестарту процесу |
| `paper_sessions.py` | `session_record()`, `append_session()` | Реєстр завершених паперових сесій для API |
| `lightgbm_classifier.py` | `HeuristicDirectionClassifier`, `LightGBMDirectionClassifier` | Rule-based fallback і опційний LightGBM |
| `egarch_forecast.py` | `egarch_forecast_volatility()` | EGARCH(1,1) через `arch`; `None`, якщо недоступно |
| `vol_forecast.py` | `VolForecaster`, `HarVolForecaster`, `ArchVolForecaster`, `build_vol_forecaster()` | Вибір прогнозатора волатильності за `VolModel`: HAR-RV або EGARCH |
| `alerts.py` | `AlertNotifier`, `NullAlertNotifier`, `TelegramAlertNotifier`, `WebhookAlertNotifier`, `CompositeAlertNotifier`, `build_notifier()` | Сповіщення про завершення прогону; `httpx`, fail-safe |
| `llm_client.py` | `OpenAICompatibleChatClient`, `LlmRequestError` | Чат-комплішени будь-якого OpenAI-сумісного ендпоінта (хмарний API або локальний сервер відкритих ваг). Тільки stdlib, без SDK; без `LLM_API_KEY` конструктор падає закрито; будь-яка несподівана форма відповіді → `LlmRequestError` |
| `orderbook_microstructure.py` | `compute_order_book_imbalance()`, `compute_micro_price()`, `compute_microstructure_dataframe()` | Мікроструктура на float/Polars (векторні обчислення), окремо від доменної версії на `Decimal` |
| `paper_trading.py` | `PaperOrderLog`, `PaperTradingLogger` | Журнал гіпотетичних ордерів |
| `nautilus/parquet_catalog.py` | `NautilusParquetCatalog` | `write()`, `load()`; валідація кожного бару; `write()` спершу **видаляє перекритий діапазон** (`delete_data_range`) — повторний ingest замінює вікно, а не додає другий файл; `load()` дедуплікує за `ts_utc` (останнє входження) і сортує за часом, тому старі каталоги лишаються читабельними |
| `nautilus/bar_feed.py` | `ResearchBarFeed` | Каталог або синтетика; `load()`, `load_multi()`; стрес-вікна; inner-join |
| `nautilus/bar_convert.py` | `to_engine_bars()`, `to_domain_bar()`, `datetime_to_nanos()`, `nanos_to_datetime()` | Доменний бар ↔ нативний `Bar` |
| `nautilus/instrument.py` | `resolve_instrument()`, `supported_instrument_ids()`, `binance_symbol_to_instrument_id()`, `eth_usdt_sim()`, `btc_usdt_sim()`, `eth_usdt_perp_sim()` | Описи інструментів симуляції |
| `nautilus/synthetic_bars.py` | `synthetic_ohlcv()`, `synthetic_regime_ohlcv()` | Детерміновані синтетичні бари (random walk; тренд-флет-тренд) |
| `nautilus/synthetic_pairs.py` | `synthetic_cointegrated_pair()` | Синтетична коінтегрована пара для тестів |
| `nautilus/backtest_runner.py` | `NautilusResearchBacktest` | Налаштування `BacktestEngine` (венʼю SIM, комісії, затримка, проковзування); `run()`, `run_spread()` |
| `nautilus/signal_strategy.py` | `SignalRobotConfig`, `SignalRobot`, `_build_robot()` | Адаптер однолегової стратегії: сигнал → ризик → ордер |
| `nautilus/spread_strategy.py` | `SpreadRobotConfig`, `SpreadRobot` | Адаптер двуногової стратегії (pairs) |

---

## `interfaces/` — вхід у застосунок

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `cli.py` | `main()`, `parse_utc()`, `parse_date()` | argparse-команди `ingest`, `research`, `paper`, `scan`, `propose`, `ml train --model-type {formulaic,meta_label,obi}`, `xsmom`, `live`; друк звітів. `research --journal` і `propose --journal` дописують рядок у журнал дослідження |
| `composition.py` | `settings()`, `catalog()`, `taker_flow_catalog()`, `orderbook_catalog()`, `research_feed()`, `notifier()`, `research_use_case()`, `walk_forward_use_case()`, `ingest_use_case()`, `ingest_funding_use_case()`, `ingest_agg_trades_use_case()`, `ingest_orderbook_use_case()`, `collect_live_agg_trades_use_case()`, `overfit_audit_use_case()`, `paper_use_case()`, `param_selection_use_case()`, `live_paper_use_case()`, `llm_completer()`, `alpha_proposal_request()`, `journal_paths()`, `research_request()`, `ingest_request()`, `funding_ingest_request()`, `ingest_agg_trades_request()`, `paper_request()`, `walk_forward_request()`, `overfit_audit_request()` | Точка збірки залежностей. `llm_completer()` — офлайн-контур, поза гарячим шляхом: без ключа падає закрито. Це **не** єдина точка збірки: `cli.py` і частина `application/` імпортують адаптери напряму (див. розділ 5.1 у [03-arhitektura.md](03-arhitektura.md)) |

---

## `api/` — веб-шар (FastAPI)

Застосунок `nautilus_lab.api.app:app` під `uvicorn` (див. `deploy/Dockerfile.api`).
Тут немає власної логіки стратегій: шар лише складає ті самі об'єкти, що й CLI,
і віддає їх у `application/`.

| Файл | Публічні символи | Призначення |
|------|------------------|-------------|
| `app.py` | `app`, `read_root()`, `get_status()`, `get_catalogs()`, `get_catalog()`, `get_catalog_bars()`, Pydantic-моделі запитів `ResearchRunRequest`, `IngestRunRequest`, `SettingsUpdate`, `MLTrainRequest`, `PaperRunRequest`, `PaperLiveStartRequest`, `JournalPatchRequest`, `ProposeRequest` | FastAPI-застосунок: REST `/api/*` (status, catalogs, catalog, data, strategies, reports, research, ingest, settings, command-center, journal, ml, paper, scan, propose, hypotheses) і WebSocket `/api/paper/live-stream`. Статичні монти `/static_reports` (тиршити) і `/static_hypotheses` — без токена, бо iframe не вміє слати заголовок. Слот на важку задачу один: повторний клік відхиляється, а не запускає другий процес |
| `security.py` | `ApiSecurity`, `role_refusal()`, `TOKEN_HEADER`, `ROLE_FULL`, `ROLE_PAPER`, `KNOWN_ROLES`, `PAPER_ROLE_WRITES`, `DEFAULT_ALLOWED_ORIGINS` | Три ворота: `Origin` (браузерні крос-сайт запити заборонено), токен `X-Lab-Token` (або `?token=` для WebSocket) і роль `LAB_ROLE`. Роль `paper` лишає доступними читання й керування живими сесіями, а research/ingest/ML/запис `.env` відхиляє |
| `market_feed.py` | `MarketFeed`, `FeedHub`, `FeedKey`, `FeedSubscriber`, `feed_key()` | Один сокет Binance на `symbol+interval`, спільний для всіх сесій: два роботи на одному ринку бачать однакові бари, а не два різні потоки |
| `paper_streamer.py` | `LivePaperSessionManager`, `LivePaperConfig`, `LivePosition`, `LiveFill`, `LiveBar`, `LiveEquityPoint`, `LIVE_PAPER_ROBOTS`, `WARMUP_BARS`, `parse_kline_message()`, `config_to_dict()`, `config_from_dict()`, `binance_history_loader()` | Жива паперова сесія: доменний робот + `application/risk.py`, симульовані філи в пам'яті, смуга equity, розсилка підписникам. Ордерів на біржу не надсилає — біржовий WebSocket тут лише джерело даних |
| `live_sessions.py` | `SessionRegistry`, `SessionRecord`, `_record_name()`, `_max_drawdown_pct()` | Реєстр сесій: створення, пошук за id або іменем, ліміт кількості, resume незавершених, читання історії з журналів |
| `live_paper_boot.py` | `boot_live_paper()`, `boot_sessions()`, `autostart_config()`, `registry_from_settings()`, `live_config_from_settings()`, `journal_from_settings()`, `sessions_dir_from_settings()`, `parse_portfolio()`, `load_portfolio()` | Підняття сесій при старті застосунку: з `.env` або з декларованого портфеля (`LIVE_PAPER_PORTFOLIO`) |
| `paper_runner.py` | `PaperRunConfig`, `execute_paper()`, `session_payload()` | Batch-прогін паперової сесії як окремий job |
| `research_runner.py` | `ResearchJobConfig`, `execute_research()`, `config_from_job()`, `write_job_artifacts()`, `load_job_result()`, `summary_from_result()`, `default_tearsheet_path()` | Важкий прогін у дочірньому процесі: конфіг → use case → артефакти `last_run.*` у `reports/` |
| `run_research_job.py`, `run_paper_job.py`, `run_ml_job.py` | `main()` | Точки входу дочірніх процесів, які запускає `app.py` (`--config-json`, `--reports-dir`) |
| `ml_runner.py` | `MLTrainConfig`, `execute_ml_train()`, `list_models()` | Тренування LightGBM як job і перелік збережених моделей |
| `catalog_service.py` | `describe_catalog()`, `describe_catalog_cached()`, `list_catalogs()`, `load_catalog_bars()`, `resolve_catalog_path()`, `invalidate_catalog_cache()`, `repo_root()` | Опис каталогу для UI: інструменти, діапазони, кількість барів |
| `data_health.py` | `describe_data_health()`, `describe_data_health_cached()`, `invalidate_data_health_cache()` | Здоров'я даних по кожній серії: бари, тики, книга, фандинг, тейкерський потік |
| `command_center.py` | `build_command_center()`, `scan_triangular_demo()` | Зведення для головного екрана: стан job-ів, останній прогін, журнал, здоров'я даних |
| `experiment_history.py` | `archive_job_result()`, `list_history()`, `load_history_entry()`, `history_dir()` | Архів прогонів у `reports/history/` |
| `journal_service.py` | `list_journal_entries()`, `update_journal_decision()`, `journal_summary()` | Читання журналу й зміна ручного рішення (єдине місце, де рядок журналу переписується) |
| `serializers.py` | `serialize_metrics()`, `serialize_costs()`, `serialize_backtest()`, `serialize_walk_forward()`, `serialize_fold()`, `serialize_multi_window()`, `serialize_pbo()`, `serialize_deflated_sharpe()`, `build_job_result()`, `tearsheet_url()`, `pct()` | `Decimal` → JSON без втрати точності; рядок порівняння з buy&hold |
| `settings_schema.py` | `SettingField`, `SettingGroup`, `settings_schema_payload()`, `normalize_env_key()`, `validate_settings_update()`, `mask_secret()` | Схема `.env` для UI, валідація оновлень, маскування секретів |
| `settings_coerce.py` | `apply_setting_overrides()` | Застосування оновлених значень до `Settings` із приведенням типів |

---

## Тести

| Файл | Що покриває |
|------|-------------|
| `conftest.py` | Фікстура `default_limits` (RiskLimits) і хелпер `make_bars(count, start, step_minutes)` |
| `unit/test_bars.py` | Валідація OHLCV, UTC, монотонність, майбутні бари |
| `unit/test_binance_klines.py` | Парсинг kline, пагінація, помилкові відповіді |
| `unit/test_http_resilience.py` | Парсинг ваги й `Retry-After` (відсутній заголовок не читається як нуль), експоненційний backoff із стелею, повтор 429/418/5xx і обриву сокета, негайна відмова на 400, `RateLimitedError` замість обрізаної серії, проактивна пауза при ≥90% ваги |
| `unit/test_binance_funding.py` | Пагінація понад стелю 1000, джойн `index_price` за годиною розрахунку, `None` замість підстановки mark price, відкидання позавіконних і зламаних рядків, типовий клієнт — стійкий |
| `unit/test_funding_ingest.py` | Parquet-серія фандингу: точний round-trip `Decimal`, `None` лишається `None`, повторний запис вікна не дублює, фільтр за вікном; use case: звіт, `missing_index_price`, порожня відповідь → помилка, live → fail closed |
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
| `unit/test_optuna_optimizer.py` | Оптимізатор Optuna: кількість trials, вибір параметрів для кожного робота; `regime` ніколи не порушує `enter_trend_er > exit_trend_er`; `vpin_momentum` і `formulaic_lgbm` справді перебирають свої параметри |
| `unit/test_overfitting.py` | PBO/CSCV: домінантна конфігурація → PBO 0; антикорельовані блоки → PBO 1; нічийні розбиття не рахуються; одна конфігурація → `undefined`; нерівна матриця й порожня матриця → помилка |
| `unit/test_audit_fixes.py` | Регресії на знайдені аудитом помилки: `15m` ≠ `5m`, перпетуал у `bar_type`, невідомий інтервал → помилка, рекурсія Вайлдера в ATR, VaR-квантиль, недосяжний поріг funding, нульовий `index_price`, зсув GLFT від інвентарю. Деталі — [15](15-audit-vypravlennya.md) |
| `unit/test_alerts.py` | Нотифікатори: успіх, HTTP-помилка, виняток, композиція (з моками `httpx`) |
| `unit/test_hypothesis.py` | Контракт гіпотези: `FEATURE_NAMES` не розходиться з порядком виходу `FormulaicAlphaEngine`, обов'язкові поля, межі горизонту, нормалізація знаку, лінтер вигаданих ознак |
| `unit/test_propose_alphas.py` | Офлайн-цикл без мережі (фейковий completer): рендер плейсхолдерів, екстракція JSON із фенсів і прози, provenance артефакта, унікальність імені файлу, ліквідація облікових даних з `endpoint_host` |
| `unit/test_llm_client.py` | Клієнт: fail-closed без ключа, тіло й заголовки запиту (`monkeypatch` на `urlopen`), нормалізація `base_url`, HTTP/мережеві помилки, шість непридатних форм відповіді, відсутність сторонніх SDK |
| `unit/test_journal.py` | Журнал: форматування рядка (числа, `n/a`, екранування `|`, обрізання), дописування без перезапису, збереження ручного рішення, fail-closed без маркерів і з перевернутими маркерами, round-trip JSONL, відмова від недовірених записів |
| `unit/test_cli_propose_journal.py` | CLI без мережі (фейковий `llm_completer`): `propose --dry-run`, fail-closed без ключа, артефакт + рядок `pending` у журналі, `--journal` вимкнено типово, `JOURNAL_ENABLED=true`, помилка при втрачених маркерах |
| `unit/test_orderbook_microstructure.py` | OBI (скаляр і список рівнів), micro-price, Polars-трансформація |
| `integration/test_research_backtest.py` | Реальний рушій Nautilus: синтетичний прогін, roundtrip каталогу, pairs, порожній каталог → fail closed; повторний ingest перекритого вікна замінює дані, а не дублює їх; `load()` дедуплікує каталог, у якому вже лежать перекриті файли |
| `integration/test_tearsheet_generation.py` | Генерація HTML-тиршита: файл створюється, непорожній, шлях повертається у звіті |

Запуск:

```bash
uv run pytest                                      # усі 333 тести
uv run pytest tests/unit -q                        # лише швидкі
uv run pytest tests/integration -q                 # лише рушій (локально, без мережі)
uv run pytest --cov --cov-report=term-missing      # з покриттям (порог 80%; поточне — 82.35%)
```

---

## Кореневе

| Файл | Призначення |
|------|-------------|
| `README.md` | Короткий вступ і швидкий старт |
| `Стратегії MFT Криптоторгівлі 2026.md` | Вихідний дослідницький документ: ідеї, математика, інфраструктура, податки |
| `docs/` | Ця документація, включно з [uml/](uml/README.md) |
| `pyproject.toml` | Залежності, extras (`dev`, `ml`, `research`, `visualization`, `alerts`), налаштування ruff/mypy/pytest/coverage |
| `.env.example` | Шаблон усіх змінних з коментарями |
| `.env` | Ваші локальні налаштування (у `.gitignore`) |
| `uv.lock` | Зафіксовані версії залежностей |
| `catalog/` | Parquet-каталог даних (у `.gitignore`) |
| `scripts/` | Одноразові та офлайн-скрипти: `train_formulaic_lgbm.py`, `propose_alphas.py` (тонка обгортка над `lab propose`) |
| `research/` | Офлайн-контур: промпти, артефакти гіпотез, журнал рішень (див. [research/README.md](../research/README.md)) |
| `models/` | Збережені бустери LightGBM, напр. `formulaic_lgbm.txt` |

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
| Промпт або гіпотезу для офлайн-циклу | `research/prompts/` і `research/hypotheses/` | Дослідницькі дані живуть поза кодом; модель ніколи не викликається з гарячого шляху |

## Куди йти далі

- Створити свою стратегію → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
- UML-діаграми → [uml/README.md](uml/README.md)
- Повернутися до змісту → [README.md](README.md)
