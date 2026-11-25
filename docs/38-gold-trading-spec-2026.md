# 38. Специфікація інтеграції торгівлі золотом у `nautilus-lab` та кращі алгоритмічні практики 2026 року

> **Статус:** `active` (Фази G1, G2 і G3 — Трек A Binance Gold/Silver, сесії DST / `gold_session_orb` / Kalman `pairs` / `meta_label` контекст і Трек B COMEX через Databento — реалізовані й покриті тестами; попереду — емпірична валідація на реальних золотих даних за §6). Машинно-перевірюваний контракт компонента —
> [`specs/components/gold-trading.yaml`](../specs/components/gold-trading.yaml).
>
> **Дисципліна проєкту не змінюється:** `lab live` лишається **fail closed** (код 1);
> жодних LLM на гарячому шляху; лише закриті бари й `Decimal`; OOS-звіт порівнюється
> з **buy&hold золота** за той самий період; жодних вигаданих чисел — усі гіпотези
> проходять преєстрацію, walk-forward, PBO/DSR і `PromotionGate` v2.

---

## 1. Навіщо два треки інтеграції (архітектурне рішення)

Станом на кінець 2026 року ринок біржового золота розділився на дві сумісні, але
мікроструктурно різні екосистеми: **крипто-нативне золото на Binance** (`PAXGUSDT`,
`XAUTUSDT`, `XAUUSDT-PERP`) і **класичні ф'ючерси CME/COMEX** (`GC`, `MGC`, `1OZ`).

Для `nautilus-lab` оптимальною є **двотрекова архітектура**:

| Трек | Інструменти | Джерело даних | Коли використовувати | Головне обмеження |
|---|---|---|---|---|
| **Трек A — Binance Gold** *(Фази G0–G2)* | `PAXG/USDT.SIM`, `PAXGUSDT-PERP.SIM`, `XAUT/USDT.SIM`, `XAUTUSDT-PERP.SIM`, `XAUUSDT-PERP.SIM` | Публічні REST/WS Binance + `data.binance.vision` (**без API-ключів**) | Швидкий запуск досліджень і 24/7 live paper на існуючій інфраструктурі `nautilus-lab` | Спот-комісія 15 bps RT вбиває інтрадей; `PAXG` має tracking error ~0.24%; `XAUUSDT-PERP` запущений 05.01.2026 (< 1 року історії) |
| **Трек B — COMEX Futures** *(Фаза G3)* | `GC` (100 oz), `MGC` (10 oz), `1OZ` (1 oz, 24/7 з липня 2026) | **Databento** (`GLBX.MDP3`, `.dbn.zst` → `ParquetDataCatalog`) | Інституційна валідація на 10–15 роках історії, низькі комісії (~0.5–1.5 bps екв.), справжній CLOB L1/L2 | Платні дані (стартовий кредит Databento \$125), потрібна підтримка `USD`-акаунта, `FuturesContract`, 23×5 календаря й roll-логіки |

**Чому не одразу тільки COMEX і не тільки Binance:**
- Трек A дає змогу перевірити гіпотези на золоті за лічені години без зміни білінгу,
  вендорів чи інфраструктури VPS paper-термінала.
- Трек B усуває головний ризик Треку A — **малий горизонт історії і вищі комісії**:
  `PAXG` на Binance має історію лише з серпня 2020 (а `XAUUSDT-PERP` — з січня 2026),
  тоді як для 6+ walk-forward фолдів через різні макрорежими (флет 2015–2019, COVID
  2020, цикл ставок ФРС 2022–2023, ралі та обвал 2025–2026) потрібен багаторічний ряд
  із низьким тертям.

---

## 2. Біржова мікроструктура золота у 2026 році

2025–2026 роки докорінно змінили торгівлю золотом. Після зростання з ~\$4 341/oz на
прикінці 2025 року до історичного піку ~\$5 627/oz у січні 2026 року та корекції понад
20% (до ~\$3 560–\$3 650/oz у листопаді 2026 року) статичні алгоритми з фіксованими
стопами й високим плечем масово зламалися.

### 2.1. Порівняння майданчиків і контрактів (2026)

| Параметр | COMEX `GC` | COMEX `MGC` | COMEX `1OZ` | Binance `PAXGUSDT` / `XAUTUSDT` (Perp) | Binance `XAUUSDT` (TradFi Perp) |
|---|---|---|---|---|---|
| **Біржа** | CME Group (COMEX) | CME Group (COMEX) | CME Group (COMEX) | Binance Futures (USDⓈ-M) | Binance Futures (TradFi / ADGM) |
| **Базовий актив / розрахунок** | 100 троїцьких унцій, фіз. поставка | 10 oz, фіз. поставка | 1 oz, cash-settled до `GC` | 1:1 ERC-20 токени золота, USDT | Синтетичний індекс спот-золота (Dxfeed/Massive/Pyth по 33% + 1% PAXG), USDT |
| **Крок ціни / обсягу** | \$0.10/oz (\$10/тік) | \$0.10/oz (\$1/тік) | Дробовий USD/oz | `tickSize=0.01`, `stepSize=0.001` (спот PAXG `0.0001`) | `tickSize=0.01`, `stepSize=0.001`, `minNotional=5 USDT` (практ. мін. `0.002 oz`) |
| **Графік торгів** | 23×5 (Нд 18:00 – Пт 17:00 ET, 1h перерва) | 23×5 | **24/7** з 24–26 липня 2026 (коротка техперерва в суботу) | **24/7/365** | 24/7 (з верес. 2026 24/5 базовий індекс + EWMA mark ±3% у вихідні) |
| **Ліквідність (2026)** | ~\$100B/день по комплексу `GC`; якір price discovery | Рекордний бум: 53% обсягу CME Metals; ADV 300k–690k+ | ~90k ADV; >\$219M у перші 24/7 вікенд-сесії | ~\$52–95M/день (`PAXG`), ~\$35M/день (`XAUT`) | Найглибший стакан золота на Binance (~\$397M/день, ~10× від PAXG+XAUT) |
| **Комісії (орієнтир)** | ~\$2.0–2.5/сторону (~0.5–1 bps екв.) | ~\$0.6–1.2/сторону (~1.5–3 bps екв.) | Низька per-contract | VIP0 BNB: 2 bps maker / 5 bps taker (спот: **7.5 / 7.5 bps**) | VIP0 BNB: 2 bps maker / 5 bps taker |
| **Специфіка `exchangeInfo`** | `FuturesContract` (`XCEC`/`GLBX`) | `FuturesContract` | `FuturesContract` | `contractType: "PERPETUAL"` | **`contractType: "TRADIFI_PERPETUAL"`**, `underlyingType: "COMMODITY"`, **немає на споті** |

### 2.2. Чотири критичні ефекти мікроструктури 2026 року

1. **Процентна маржа CME (січень 2026):** 13 січня 2026 CME перейшла з фіксованої
   доларової маржі на **відсоток від номіналу** (5% → підвищено до 9% після обвалу на
   початку лютого 2026 → 7% у березні 2026). Для бектесту це означає: будь-які моделі з
   плечем повинні враховувати динамічні вимоги маржі під час спалахів волатильності.
2. **Вікенд-ліквідність і зсув режиму:** У першій половині 2026 крипто-золото (`PAXG`,
   `XAUT`, `XAUUSDT`) було єдиним публічним 24/7 каналом ціноутворення під час
   геополітичних шоків на вихідних, після чого COMEX гепив у неділю ввечері. Із липня
   2026 `1OZ` на CME теж перейшов на 24/7, але на Binance `XAUUSDT` під час закриття
   TradFi-оракулів застосовує EWMA Mark Price із обмеженням відхилення ±3% від індексу
   та має тонший стакан — каскадні ліквідації на тонкій книзі створюють широкі тіні (wicks).
3. **Похибка відстеження токенізованого золота:** За емпіричними вимірами 2026 року
   (245 денних закриттів, січ–жовт 2026) `PAXG` тримає спот щільніше (середній абсолютний
   розрив **0.235%–0.251%**), ніж `XAUT` (**0.371%–0.402%**, стійкий невеликий дисконт
   через комісію мінту/викупу Tether 0.25% і поріг 430 токенів).
4. **Сесійна сезонність і DST-пастка:** На 1-хвилинних даних XAU/USD (rolling 12 міс. до
   листопада 2026, Forge Strategy Lab):
   - **Азія (23:00–07:00 UK):** середній діапазон ~\$64.76 (\$8.09/год), найширша сесія дня у 38% днів.
   - **Лондон (07:00–13:00 UK):** ~\$45.37 (\$7.56/год); пробій азійського діапазону стається у **93%** торгових днів (медіанний час першого пробою — **08:45 UK**), але у **19% днів пробиваються обидві сторони** (двосторонні свіпи ліквідності).
   - **Перетин Лондон–Нью-Йорк (13:00–17:00 UK / 08:00–12:00 ET):** пік ліквідності та руху (14:00–15:00 UK — \$32–33/год, Нью-Йорк є найширшою сесією у 56% днів; виходи CPI/NFP/FOMC о 08:30 ET розширюють 15m-діапазон у 5×+).
   - **Пастка DST:** США та Велика Британія переводять годинники в різні тижні навесні та восени (у 2026: США 8 березня – 1 листопада, Британія 29 березня – 25 жовтня). Жорстко зашитий UTC-час двічі на рік зсуває сесійне вікно на 1 годину.

---

## 3. Аудит `nautilus-lab`: що вже працює і які 10 прогалин треба закрити

### 3.1. Що в проєкті вже готове «з коробки»

Перевірка кодової бази та встановленого `nautilus_trader==1.231.0` показала, що значна
частина фундаменту для золота вже існує:

- **Валюти та класи інструментів NautilusTrader:** `Currency.from_str("XAU")` (ISO 4217
  `959`, `COMMODITY_BACKED`), `Currency.from_str("XAG")` (`961`), `PAXG`, `XAUT`, `USD`
  підтримуються нативно. Доступні `CurrencyPair`, `CryptoPerpetual`, `FuturesContract`,
  `Commodity`.
- **Історичні дані Binance (спот + USD-M перп):**
  - [`BinancePublicKlines`](../src/nautilus_lab/infrastructure/binance_klines.py) вже
    автоматично перемикає URL на `https://fapi.binance.com/fapi/v1/klines` для символів
    із суфіксом `-PERP` та зберігає поле 9 (`takerBuyBaseAssetVolume`).
  - [`binance_vision.py`](../src/nautilus_lab/infrastructure/binance_vision.py) вже качає
    SHA256-перевірені архіви `spot` і `futures/um` (`klines`, `fundingRate`,
    `premiumIndexKlines`, `markPriceKlines`, `indexPriceKlines`) і вміє автоматично
    виводити точність через `register_instrument()` у `data/instruments.json`.
- **Доменні модулі ризику, режимів і фільтрів, що прямо відповідають практикам 2026 для золота:**
  - [`RiskOverlay`](../src/nautilus_lab/domain/risk_overlay.py): `use_vol_scaling` (HAR-RV /
    EGARCH volatility targeting), `use_fractional_kelly`, `use_cvar_breaker`,
    `use_chandelier_stop` (ATR-адаптивний трейлінг-стоп у
    [`chandelier_stop.py`](../src/nautilus_lab/domain/chandelier_stop.py)), `stop_cooldown_bars`.
  - [`EntryFilter`](../src/nautilus_lab/domain/entry_filters.py): `htf_trend`,
    `vol_expansion`, `no_instant_reverse`.
  - [`GlobalTrendGate`](../src/nautilus_lab/domain/global_trend.py): фільтр глобального
    тренду по завершених денних свічках (`SMA 200 1d` із гістерезисною смугою ±2%).
  - [`PairsTrading`](../src/nautilus_lab/domain/pairs/pairs_trading.py) (ADF + OU half-life),
    [`FundingRobot`](../src/nautilus_lab/infrastructure/nautilus/funding_strategy.py),
    [`MetaLabelStrategy`](../src/nautilus_lab/domain/meta_label_strategy.py),
    [`FormulaicLgbmStrategy`](../src/nautilus_lab/domain/formulaic_lgbm_strategy.py).
  - Повний контур валідації: rolling walk-forward, PBO/CSCV, DSR з обліком `trials.jsonl`,
    breakeven-cost, `CostProfile` (`stress_x1_5`), `PromotionGate` v2 та `DecisionTrace`.

### 3.2. Десять конкретних інженерних прогалин (з прив'язкою до файлів)

| # | Трек | Файл і місце в коді | Суть прогалини | Що зламається без виправлення |
|---|---|---|---|---|
| **G-01** | A | [`instrument.py`](../src/nautilus_lab/infrastructure/nautilus/instrument.py) (`_SPOT_SPECS`, `_PERP_SPECS`) | Немає `PAXG/USDT.SIM`, `PAXGUSDT-PERP.SIM`, `XAUT/USDT.SIM`, `XAUTUSDT-PERP.SIM`, `XAUUSDT-PERP.SIM` | `lab ingest --symbols PAXGUSDT` (REST-шлях) падає з `ValueError: unsupported instrument_id` |
| **G-02** | A | [`binance_ws.py`](../src/nautilus_lab/infrastructure/binance_ws.py) (`BINANCE_WS_BASE_URL`), [`market_feed.py`](../src/nautilus_lab/api/market_feed.py) | Хардкод спотового сокета `wss://stream.binance.com:9443/ws` | Неможливо запустити Live Paper Terminal для `XAUUSDT-PERP` і `PAXGUSDT-PERP` (а `XAUUSDT` взагалі існує лише як перп!) |
| **G-03** | A | [`universe.py`](../src/nautilus_lab/domain/universe.py) (`STABLE_OR_FIAT_BASES`, `is_tradeable_base`) | `PAXG` і `XAUT` проходять як звичайні крипто-токени | `lab xsmom` та архівні скани змішують золото з альткоїнами, псуючи крос-секційну статистику |
| **G-04** | A | [`stress_slices.py`](../src/nautilus_lab/domain/stress_slices.py) | Лише крипто-слайси (`covid2020`, `ftx2022`, `etf2024`) | `ftx2022` і `etf2024` не тестують золоті шоки (розрив EFP 2020, цикл ставок 2022, січень–березень 2026 blow-off/crash) |
| **G-05** | A | [`derivatives-data.yaml`](../specs/components/derivatives-data.yaml) прогалини (a)–(b), [`backtest_runner.py`](../src/nautilus_lab/infrastructure/nautilus/backtest_runner.py) (`interval=480`) | Фандинг-каденція зашита в 8h (`480`), а `mark_price`/`index_price` із `funding.parquet` не доходять до `FundingRobot` | Неточний carry/basis на перпах із 4h фандингом і неможливість коректно виміряти відхилення `XAUUSDT` mark vs index на вихідних |
| **G-06** | A/B | `domain/sessions.py` *(відсутній)* | Немає доменного визначення сесій Азія / Лондон / Нью-Йорк із IANA `zoneinfo` | Сесійні стратегії на золоті ламаються двічі на рік через розбіжність дат DST між UK та US |
| **G-07** | B | [`backtest_runner.py`](../src/nautilus_lab/infrastructure/nautilus/backtest_runner.py) (`usdt = Currency.from_str("USDT")`), [`instrument.py`](../src/nautilus_lab/infrastructure/nautilus/instrument.py) (`_split_instrument_id`) | Валюта рахунку зашита як `USDT`; парсер id знає лише `USDT/USDC/BUSD` і не створює `FuturesContract` | Неможливо симулювати COMEX `GC` / `MGC` / `1OZ` (котируються в `USD`, мають множник контракту 100/10/1) |
| **G-08** | B | [`data_quality.py`](../src/nautilus_lab/domain/data_quality.py) (`expected_bars = int(span / interval) + 1`) | QC припускає 24/7 неперервну серію; `missing_fail_share = 0.01` | На COMEX 23×5 вихідні (49 год) + 1h щоденна перерва дають ~32% «відсутніх» барів → QC завжди повертає `FAIL` і блокує бектест |
| **G-09** | B | [`metrics.py`](../src/nautilus_lab/domain/metrics.py) (`PERIODS_PER_YEAR`) | Хардкод 24/7 (`1h: 8760`, `1d: 365`) | На COMEX 23×5 річний Sharpe завищується в $\sqrt{8760 / 5796} \approx 1.23\times$ |
| **G-10** | B | [`fees.py`](../src/nautilus_lab/domain/fees.py), [`backtest_runner.py`](../src/nautilus_lab/infrastructure/nautilus/backtest_runner.py) (`MakerTakerFeeModel`) | Лише відсоткові bps-тарифи Binance (`spot_*` / `usdm_*`) | COMEX ф'ючерси мають фіксовану поконтрактну комісію (\$/контракт + кліринг) і фіксований тік \$0.10/oz |

---

## 4. Які алгоритми торгівлі золотом працюють краще у 2026 році (і що провалюється)

Нижче — синтез академічних і практичних досліджень 2025–2026 років, спроєктований
безпосередньо на реалії комісій і валідаційних воріт `nautilus-lab`.

### 4.1. Матриця пріоритетів стратегій для `nautilus-lab`

| Пріоритет | Сімейство стратегій | Економічне джерело переваги | Де працює найкраще | Відображення в `nautilus-lab` |
|---|---|---|---|---|
| **Tier 1 (№1)** | **Forecast-to-Fill Trend + Volatility-Targeted Momentum** | Тривалі макротренди золота (ЦБ-попит, реальні ставки, геополітика) + контроль ризику під змінні режими волатильності | `PAXGUSDT-PERP` `1h`/`4h` (Трек A); COMEX `MGC`/`GC` `1h`/`4h`/`1d` (Трек B) | Існуючий `regime` (лише тренд-лег або `REGIME_RANGE_ALLOW_SHORT=false`) + `use_vol_scaling=true` + `use_chandelier_stop=true` + `entry_filter_global_trend=true` |
| **Tier 1 (№2)** | **Regime-Filtered Asian/London Session Breakout (`gold_session_orb`)** | Інституційна концентрація ордерів на відкритті Лондона й перетині Лондон–Нью-Йорк після нічної азійської консолідації | `PAXGUSDT-PERP` / `XAUUSDT-PERP` `15m`/`1h` (Трек A); `MGC`/`GC` `5m`/`15m`/`1h` (Трек B) | **Новий робот** `gold_session_orb` + доменний модуль `domain/sessions.py` (IANA DST) |
| **Tier 1 (№3)** | **Dynamic Gold–Silver StatArb (Kalman Hedge Ratio + Regime Gate)** | Стійка фундаментальна коінтеграція дорогоцінних металів (`XAU`/`XAG` або `GC`/`SI`) із динамічним коефіцієнтом хеджування | COMEX `GC`–`SI` / `MGC`–`SIL` (Трек B) або `XAUUSDT-PERP`–`XAGUSDT-PERP` (коли/якщо доступний ліквідний срібло-перп) | Апгрейд існуючого `pairs`: заміна статичного OLS на **Kalman Filter** + гейт режиму волатильності |
| **Tier 2** | **Cross-Asset Interpretable Meta-Labeling (`LightGBM` + SHAP)** | Фільтрація хибних входів базового робота за ендогенними ознаками базису (`premium_index`) і крос-активними сигналами (срібло, VIX, WTI, BTC) | `1h`/`4h`/`1d` поверх Tier 1 роботів | Існуючий `meta_label` + розширення вектора ознак (`premium_index`, крос-актив) |
| **Tier 2** | **Tokenized Gold Spot–Perp Basis / Carry** | Періодичний позитивний фандинг і розбіжність токен↔перп (`PAXG` vs `PAXGUSDT-PERP` / `XAUUSDT-PERP`) | Трек A (`PAXG/USDT` + `PAXGUSDT-PERP`) | Існуючий `funding` після закриття прогалин (a)–(b) `derivatives-data.yaml` + tail-risk circuit breaker |
| **Tier 3 (НЕ робити)** | Наївний 1m–15m OHLCV mean-reversion, нефільтровані London/NY ORB, фіксовані \$-стопи, LLM на гарячому шляху | Експериментально фальсифіковані ($H \approx 0.5$ на коротких горизонтах, від'ємне нетто після витрат) | — | Відхиляємо до коду |

### 4.2. Детальний розбір алгоритмів Tier 1 і Tier 2

#### Алгоритм 1: Forecast-to-Fill Trend + Volatility-Targeted Momentum
- **Емпірична основа (2025–2026):** Singha, Aguilera-Toste & Lahiri (*arXiv:2511.08571*,
  листопад 2025, rolling walk-forward COMEX `GC` 2015–2025) показали, що стійка OOS-альфа
  на золоті приходить не від складних «чорних скриньок», а від інженерії контуру
  **forecast-to-fill**: інтерпретовані сигнали тренду/моментуму + **volatility targeting**
  (розмір позиції обернено пропорційний реалізованій волатильності) + **дробовий Келлі** +
  **ATR-виходи (Chandelier)** + чесна модель тертя й проковзування.
- **Чому це ідеальний перший експеримент для `nautilus-lab`:**
  Усі будівельні блоки **вже є в коді**! Потрібна не нова чорна скринька, а правильна
  пререєстрована комбінація під волатильність золота:
  - **Інструмент:** `PAXGUSDT-PERP.SIM` (5 bps taker проти 7.5 bps на споті — економія 5 bps
    на кожному round-trip!) на `1h` і `4h`.
  - **Базова гіпотеза (до прогону):**
    - `ROBOT=regime`, `REGIME_LEGS=uptrend,downtrend` або `REGIME_RANGE_ALLOW_SHORT=false`
      (на золоті з довгостроковим висхідним дрейфом range-шорти так само збиткові, як і в H3
      на BTC/ETH).
    - `USE_VOL_SCALING=true`, `VOL_MODEL=har`, `VOL_SCALING_TARGET=0.01` (нижче за криптовий
      `0.02`, бо реалізована волатильність золота в ~2.5× нижча).
    - `USE_CHANDELIER_STOP=true`, `CHANDELIER_ATR_MULTIPLE=3.0`, `CHANDELIER_LOOKBACK=22`
      (замість фіксованого `STOP_PCT=0.03`, який занадто широкий у спокійні роки й завузький у
      шокові дні 2026!).
    - `ENTRY_FILTER_GLOBAL_TREND=true` (`1d`, `SMA 200`, `band_pct=0.02`) +
      `NO_INSTANT_REVERSE=true`.
    - `COST_PROFILE=binance_vip0_bnb`, а потім обов'язковий стрес-прогін
      `COST_PROFILE=stress_x1_5`.
- **Головна перевірка:** чи обганяє стратегія **buy&hold золота** (і volatility-matched
  buy&hold) на 6+ rolling-фолдах за 2020–2026, чи принаймні суттєво знижує `max_dd` за
  порівнянної доходності без провалу `PBO > 0.30`.

#### Алгоритм 2: Regime-Filtered Session Breakout (`gold_session_orb`)
- **Емпірична основа (2025–2026):**
  - *Wicko Strategy Lab* (листопад 2026, XAUUSD 5m, 2021–2026): чистий London Breakout дає
    **−0.04R net**, NY ORB — **−0.04R net**, не фільтрований Asian Range Breakout — лише
    **+0.02R net** (плоский 0.00R у 2021–2024). Додавання лише одного **тренд-фільтра
    (1H 200 EMA)** піднімає нетто-очікування до **+0.05R** (+0.10R у 2025–2026).
  - *RelaxedTrader COMEX `@GC` ORB* (OOS 2016–2026, 531 угода): лонговий пробій з виходом на
    наступному відкритті (сер. утримання ~1.5 доби) показав Profit Factor 1.69 — ключове
    відрізнення від 5m скальпінгу в тому, що **позиція утримується досить довго, щоб рух
    покрив комісії й спред**, замість 83% виходів по 4-годинному тайм-стопу.
  - *Forge Strategy Lab* (2026): 19% днів пробивають обидва краї азійського діапазону — отже
    потрібні: (а) фільтр напрямку по старшому тренду, (б) фільтр ширини азійського боксу
    відносно `ATR(14d)` (відсікати дні, де бокс уже > 0.8–1.0 денного ATR — рух вичерпано),
    (в) закриття за межами боксу (лише закриті бари, без look-ahead).
- **Проєкт нового робота `gold_session_orb` (чернетка для Фази G2, SDD):**
  - **Доменний модуль:** `src/nautilus_lab/domain/gold_session_orb.py` (`GoldSessionOrb`),
    використовує новий чистий модуль `src/nautilus_lab/domain/sessions.py` (IANA `zoneinfo`).
  - **Таймфрейм:** `15m` або `1h` (на Binance перп `1h` пріоритетний через 10 bps RT taker;
    `15m` тестується лише при `breakeven > paid + 5 bps` або на COMEX у Треку B).
  - **Логіка сигналу (лише закриті бари, `Decimal`):**
    1. **Фаза боксу (Asia Window):** накопичує `box_high` і `box_low` по закритих барах у
       вікні `00:00–07:00 Europe/London` (запобігає DST-зсуву).
    2. **Фільтр ширини боксу:** `box_width = box_high - box_low`; пропуск дня, якщо
       `box_width / atr < min_box_atr` (мертвий ринок) або `box_width / atr > max_box_atr`
       (волатильність уже витрачена в Азії).
    3. **Вікно входу (London + London/NY Overlap):** `07:00–16:00 Europe/London` (або
       перетин `Europe/London` та `America/New_York`). Максимум 1 вхід на день (без
       повторних входів після стопу в той самий день — лікує 19% двохсторонніх свіпів).
    4. **Сигнал пробою:** перший закритий бар із `close > box_high + buffer_atr * atr` →
       `BUY` (або `close < box_low - buffer_atr * atr` → `SELL`, якщо дозволено
       `allow_short` і узгоджено з `GlobalTrendGate` / `htf_trend`).
    5. **Вихід:** захисний стоп через `RiskLimits` / `ChandelierStop` + обов'язковий
       часовий вихід (`max_hold_bars`, напр. кінець NY-сесії або 24–36 барів на `1h`).
  - **Мала сітка підбору (`explicit` у `param_grid.py` — 9–12 точок, щоб не накрутити DSR):**
    - `GOLD_ORB_MAX_BOX_ATR`: `[0.6, 0.8, 1.0]`
    - `GOLD_ORB_BUFFER_ATR`: `[0.0, 0.15, 0.30]`
    - `GOLD_ORB_MAX_HOLD_BARS`: фіксований або `[8, 16, 24]` (не більше 2 вимірів у сітці одночасно!)
  - **`minimum_bars`:** `200` (достатньо для розігріву ATR + старшої EMA).

#### Алгоритм 3: Dynamic Gold–Silver StatArb (`pairs` + Kalman Filter)
- **Емпірична основа (2025–2026):** Mittal & Mittal (*SSRN / Authorea*, кін. 2025,
  COMEX `GC–SI` та `GLD–SLV` 2015–2025) показали, що класичний статичний OLS на золоті–сріблі
  рветься під час макро-змін співвідношення Gold/Silver ratio, тоді як **динамічний
  фільтр Калмана** для оцінки hedge ratio $\beta_t$ у поєднанні з **режимним фільтром**
  (блокування входу при трендовому розходженні спреду) радикально зменшує просадки.
- **Як лягає на `nautilus-lab`:**
  - Існуючий [`PairsTrading`](../src/nautilus_lab/domain/pairs/pairs_trading.py) вже має
    ворота коінтеграції (ADF `p <= 0.05`, fail closed!), оцінку OU half-life і двоногий
    адаптер [`SpreadRobot`](../src/nautilus_lab/infrastructure/nautilus/spread_strategy.py).
  - Потрібно додати опційний `hedge_estimator: Literal["ols", "kalman"] = "ols"` у
    `domain/pairs/` (чистий `Decimal` або 1D state-space Калман без look-ahead) і тестувати
    на зв'язках:
    - Трек B: `MGC`–`SIL` / `GC`–`SI` (найсильніша економічна коінтеграція).
    - Трек A (експеримент): `PAXGUSDT-PERP`–`XAUUSDT-PERP` (арбітраж tracking-gap
      токенізованого золота проти індексного перпа; ризик — короткий ряд `XAUUSDT-PERP`)
      або `PAXG/USDT`–`BTC/USDT` (лише якщо пройде ADF-гейт — скоріш за все чесно дасть
      `fills=0`, і це нормальна відповідь).

#### Алгоритм 4 (Tier 2): Interpretable ML (`meta_label` + Basis / Cross-Asset Features)
- **Емпірична основа (2025–2026):**
  - Дослідження GBDT + SHAP на COMEX `GC` (листопад 2026): **LightGBM** переміг XGBoost і
    CatBoost за OOS-стійкістю. Найважливіші фічі за SHAP: **(1) ф'ючерсний базис** і
    **(2) середньостроковий моментум**; вторинні — **срібло, спот-золото, VIX, WTI**.
  - Дослідження MDPI (липень 2026, 32 моделі на золоті 2020–2026): точний прогноз ціни
    (низький MAPE) **не конвертується автоматично в чисту альфу** без виконання і ризик-шару.
- **Висновок для `nautilus-lab`:** Не будувати автономний прогнозатор напрямку ціни на
  золоті (`formulaic_lgbm` на голому OHLCV), а використовувати існуючий
  **`meta_label` (`LightGBM` + purged K-fold + triple barrier)** як **фільтр якості сигналу**
  поверх Tier 1 стратегії (`regime` або `gold_session_orb`), додавши до фіч:
  1. `premium_index` / spot–perp basis (уже інгеститься через `binance_premium_index.py`!);
  2. сесійну ознаку (година Лондона / прапорець London–NY overlap);
  3. відношення поточної волатильності до 20-денної (HAR-RV ratio);
  4. у Треку B — крос-активні ретурни `SI` (срібло) і базис ф'ючерсної кривої.

#### Алгоритм 5 (Tier 2): Spot–Perp Basis / Cash-and-Carry (`funding`)
- **Емпірична основа:** Barzykin, Bergault & Guéant (*arXiv / Risk.net*) довели сильну
  коінтеграцію спот-золота та ф'ючерсів із поверненням базису за nested OU-процесом, але
  окремо підкреслили **хвостовий ризик фізичних дислокацій** (у березні 2020 спред EFP
  розірвався на десятки доларів, ліквідувавши плечові позиції).
- **Висновок для `nautilus-lab`:** Прогнати існуючий `funding` на `PAXG/USDT.SIM` +
  `PAXGUSDT-PERP.SIM` **після** закриття прогалин (a) та (b) у
  [`specs/components/derivatives-data.yaml`](../specs/components/derivatives-data.yaml)
  (єдиний каталог / per-leg каталоги + прокидання справжніх `mark_price`/`index_price` у
  `FundingRobot`) і з жорстким обмеженням `default_leverage=1` та `funding_basis_max`.

### 4.3. Анти-патерни (що свідомо НЕ реалізуємо)

1. **Чистий інтрадей OHLCV mean-reversion / скальпінг (`1m–15m`):** систематична
   фальсифікація на `MGC` показала, що короткостроковий експонент Херста золота
   $H \approx 0.5$ — після 0.50 pt проковзування (і тим більше після 10–15 bps на Binance)
   перевага відсутня.
2. **Нефільтровані пробої Лондона / Нью-Йорка:** −0.04R net за 5.4 роки.
3. **Фіксовані доларові або піпсові стопи/буфери:** при зміні ціни золота з \$1 800 до
   \$5 600 і \$3 600 фіксовані \$10 — це то 0.55%, то 0.18%. Усі пороги в домені —
   **лише у частках ціни або кратних ATR**.
4. **Плече > 3–5× без моделі ліквідації:** у `nautilus-lab` моделі ліквідації немає
   (`derivatives-data.yaml` прогалина d), тож бектести йдуть при `1×` із контролем
   волатильності.
5. **LLM/FinBERT на гарячому шляху:** суперечить правилу №6 `AGENTS.md`. Офлайн-генерація
   гіпотез через `lab propose` — дозволена й вітається.

---

## 5. Поетапна специфікація реалізації (Фази G0 → G3)

### Фаза G0 — Пререєстрація та перевірка даних (0 змін коду)

Перед написанням коду перевірити реальні біржові фільтри та доступність архівів:

```bash
# 1. Перевірити актуальні PRICE_FILTER.tickSize і LOT_SIZE.stepSize на Binance
curl -s 'https://api.binance.com/api/v3/exchangeInfo?symbols=%5B%22PAXGUSDT%22,%22XAUTUSDT%22%5D'
curl -s 'https://fapi.binance.com/fapi/v1/exchangeInfo' | jq '.symbols[] | select(.symbol | IN("PAXGUSDT","XAUTUSDT","XAUUSDT")) | {symbol, contractType, pricePrecision, quantityPrecision, filters}'

# 2. Перевірити, чи вже працює архівний інгест PAXGUSDT-PERP (через register_instrument)
uv run lab ingest-archive --market um --symbols PAXGUSDT --interval 1h --start 2023-01-01 --catalog catalog_gold_1h
```

> **Примітка:** `XAUUSDT` в `fapi/v1/exchangeInfo` має `contractType == "TRADIFI_PERPETUAL"`,
> а не `"PERPETUAL"`, і відсутній на споті. Будь-яка утиліта відкриття списку символів
> повинна враховувати обидва типи контрактів.

---

### Фаза G1 — Трек A: Першокласна підтримка Binance Gold/Silver (Research + Live Paper) ✅ Реалізовано

**Мета:** `PAXGUSDT`, `PAXGUSDT-PERP`, `XAUTUSDT`, `XAUTUSDT-PERP`, `XAUUSDT-PERP`, `XAGUSDT-PERP`
працюють наскрізно через `lab ingest`, `lab ingest-archive`, `lab research`, `lab paper`
і Live Paper Terminal.

#### Реалізовані зміни за файлами (підтверджено `exchangeInfo` та юніт-тестами):

1. **`src/nautilus_lab/infrastructure/nautilus/instrument.py`**
   - Додано в `_SPOT_SPECS` (звірено з `api/v3/exchangeInfo`):
     - `"PAXG/USDT.SIM": ("PAXG", "USDT", 2, "0.01", "0.0001")`
     - `"XAUT/USDT.SIM": ("XAUT", "USDT", 2, "0.01", "0.0001")`
     - `XAU/USDT.SIM` і `XAG/USDT.SIM` **свідомо відсутні** (fail closed: на Binance вони
       існують лише як `TRADIFI_PERPETUAL` на USD-M ф'ючерсах).
   - Додано в `_PERP_SPECS` (звірено з `fapi/v1/exchangeInfo`):
     - `"PAXGUSDT-PERP.SIM": ("PAXG", "USDT", 2, "0.01", "0.001")`
     - `"XAUTUSDT-PERP.SIM": ("XAUT", "USDT", 2, "0.01", "0.001")`
     - `"XAUUSDT-PERP.SIM": ("XAU", "USDT", 2, "0.01", "0.001")`
     - `"XAGUSDT-PERP.SIM": ("XAG", "USDT", 2, "0.01", "0.001")` *(відкриває нативну пару Gold–Silver на Binance)*
   - Тести: [`tests/unit/test_gold_phase_g1.py`](../tests/unit/test_gold_phase_g1.py) та
     `tests/unit/test_component_invariants.py::test_instrument_specs_match_declared_increments`.

2. **`src/nautilus_lab/infrastructure/binance_ws.py`, `src/nautilus_lab/api/market_feed.py`, `src/nautilus_lab/api/paper_streamer.py`**
   - Додано `BINANCE_FAPI_WS_BASE_URL = "wss://fstream.binance.com/ws"`.
   - `binance_stream_url()`, `agg_trade_stream_url()`, `BinanceKlineStream`, `BinanceAggTradeStream`,
     `MarketFeed.url` та `LivePaperSession._run_binance_stream` автоматично маршрутизують
     `-PERP` на `fstream` зі зрізанням `-PERP` у назві стріму й збереженням
     `instrument_id = "<SYMBOL>-PERP.SIM"` для вхідних кадрів (`k.s == "XAUUSDT"`).
   - `paper_streamer.py::binance_history_loader` використовує `BinancePublicKlines`, який уже
     маршрутизує `-PERP` на `fapi/v1/klines`.
   - Інваріант `k.x == true` (лише закриті бари) збережено для обох сокетів.

3. **`src/nautilus_lab/domain/universe.py`**
   - Додано `METAL_BASES = frozenset({"PAXG", "XAUT", "XAU", "XAG"})`.
   - `is_tradeable_base(..., include_metals=False)` і `candidate_symbols(..., include_metals=False)`
     за замовчуванням виключають метали з крипто-всесвіту `xsmom`; додано `metal_symbols()`.

4. **`src/nautilus_lab/domain/stress_slices.py`**
   - Додано золоті стрес-слайси у `StressSliceName` і `STRESS_SLICES`:
     - `GOLD_COVID_EFP_2020 = "gold_efp2020"` (`2020-02-15` → `2020-05-15`: COVID-ліквідність і дислокація EFP).
     - `GOLD_RATE_HIKE_2022 = "gold_rates2022"` (`2022-03-01` → `2022-11-15`: цикл підвищення ставок ФРС).
     - `GOLD_BLOWOFF_2026 = "gold_blowoff2026"` (`2026-01-01` → `2026-04-01`: параболічне зростання >\$5 580/oz, обвал >20% і підвищення маржі CME до 9%).

5. **`src/nautilus_lab/infrastructure/nautilus/backtest_runner.py`**
   - Додано `_infer_funding_interval_minutes()` — виводить медіанну каденцію виплат фандингу
     (4h → `240` або 8h → `480`, фолбек `480`) замість хардкоду `480`.
   - *(Залишок для подальшого кроку: закриття прогалин (a)–(b) у `specs/components/derivatives-data.yaml` — передача справжніх `mark_price` / `index_price` у `FundingRobot`.)*

**Наступний дослідницький крок на готовій Фазі G1:**
- `uv run lab ingest --symbols PAXGUSDT,PAXGUSDT-PERP,XAUUSDT-PERP,XAGUSDT-PERP --start 2024-01-01 --catalog catalog_gold_1h`
- Перший **пререєстрований** walk-forward прогін Tier 1 Алгоритму №1 (`regime` + `use_vol_scaling` + `use_chandelier_stop` + `entry_filter_global_trend` + `REGIME_RANGE_ALLOW_SHORT=false`) на `PAXGUSDT-PERP` (`1h`, 6 фолдів, `binance_vip0_bnb` і `stress_x1_5`) задокументовано в `research/journal.md`.

---

### Фаза G2 — Золото-специфічні доменні алгоритми (SDD: Spec → Code) — ✅ Реалізовано

**Мета:** Додати спеціалізовані алгоритми, які враховують унікальну фізику золота.

1. **✅ Реалізовано — Новий чистий доменний модуль `src/nautilus_lab/domain/sessions.py`**
   - Використовує стандартну бібліотеку Python 3.12+ `zoneinfo.ZoneInfo` (без зовнішніх
     залежностей, чистий домен, детерміновано).
   - `GoldSession(StrEnum)`: `ASIA`, `LONDON`, `LONDON_NY_OVERLAP`, `NY_AFTERNOON`, `OFF_HOURS`, `WEEKEND`.
   - `classify_gold_session(ts_utc: datetime) -> GoldSession`, `london_trading_date()`, `is_gold_entry_session()`:
     - визначає локальний час у `Europe/London` і `America/New_York`;
     - коректно обробляє перехідні тижні DST у березні та жовтні/листопаді;
     - повертає `WEEKEND` для пт 17:00 ET – нд 18:00 ET і `OFF_HOURS` для щоденної перерви 17:00–18:00 ET;
     - наївні `datetime` відхиляються fail closed (`ValueError`).
   - Покрито тестами: [`tests/unit/test_sessions.py`](../tests/unit/test_sessions.py).

2. **✅ Реалізовано — Новий робот `gold_session_orb` (суворо за протоколом SDD з `AGENTS.md`):**
   - Специфікація (до коду): [`specs/strategies/gold_session_orb.yaml`](../specs/strategies/gold_session_orb.yaml)
     (`status: candidate`, `grid_source: explicit`, `minimum_bars: 200`, 3 `edge_conditions`,
     4 `known_failure_modes`, `evidence.measured: false`).
   - Домен: [`src/nautilus_lab/domain/gold_session_orb.py`](../src/nautilus_lab/domain/gold_session_orb.py)
     (`GoldSessionOrb`, `GoldSessionOrbParams`, закриті бари, `Decimal`, `sync_holding`, `last_trace`).
   - Повне підключення: `RobotName.GOLD_SESSION_ORB` і `BACKTEST_WIRED_ROBOTS` (`domain/regime.py`),
     `SignalRobotConfig` / `_build_robot()` (`signal_strategy.py`), `param_grid.py` (3×3 `explicit`),
     `optuna_optimizer.py`, `minimum_bars()` / `_require_warmup()` (200), `run_paper.py`, `paper_streamer.py`,
     `batch_plan.py`, `promotion_gate.py`, `leaderboard.py`, `settings_schema.py`, ланцюг параметрів
     `settings.py → .env.example → dtos.py → composition.py → backtest_runner.py`.
   - Тести: [`tests/unit/test_gold_session_orb.py`](../tests/unit/test_gold_session_orb.py) та
     [`tests/integration/test_gold_session_orb_backtest.py`](../tests/integration/test_gold_session_orb_backtest.py).

3. **✅ Реалізовано — Апгрейд `pairs` → Kalman Filter hedge ratio (`domain/pairs/kalman.py`)**
   - Чистий причинний 2-становий експоненційно-забуваючий фільтр Калмана (`Decimal`,
     `KalmanHedgeFilter`, `fit_kalman_cointegration`) для оцінки $(\alpha_t, \beta_t)$ та
     1-крокових інновацій без look-ahead; обов'язково проходить fail-closed ворота ADF і
     half-life на інноваціях (непов'язані випадкові блукання відхиляються).
   - Перемикач `PAIRS_HEDGE_ESTIMATOR=ols|kalman` (типово `ols`, щоб золоті бектести
     `tests/golden/backtests.json` лишалися без змін) та `PAIRS_KALMAN_DELTA=0.005`
     через `Settings`, `.env.example` і дашборд (`settings_schema.py`).
   - Тести: [`tests/unit/test_pairs_kalman.py`](../tests/unit/test_pairs_kalman.py) та
     [`tests/integration/test_pairs_kalman_backtest.py`](../tests/integration/test_pairs_kalman_backtest.py).

4. **✅ Реалізовано — Розширення `meta_label` ознаками базису (`premium_index`) та сесії**
   - `OhlcvBar.premium_index_close: Decimal | None` (`domain/bars.py`) і `PremiumIndexCatalog`
     (`domain/ports.py`), безшовно приєднані за `ts_utc` у `ResearchBarFeed` (`bar_feed.py`) і
     передані через `premium_index_by_ns` у `SignalRobot` (`backtest_runner.py` / `signal_strategy.py`).
   - Причинний екстрактор `MetaContextExtractor` (`domain/meta_label_strategy.py`, чистий `Decimal`)
     додає 8 ознак (`premium_close`, `premium_zscore`, `premium_delta`, `has_premium_index`,
     `session_asia`, `session_london`, `session_overlap`, `session_ny_afternoon` — разом 21 ознака)
     і відрізняє відсутній базис (`None`) від істинно нульового через `has_premium_index`.
   - Прапорець `META_LABEL_CONTEXT_FEATURES=false|true` (`settings.py`, `.env.example`, `dtos.py`,
     `composition.py`, `settings_schema.py`) та `--context-features` у `lab ml train` /
     `scripts/train_meta_label.py` / `api/ml_runner.py`; при невідповідності `classifier.num_features`
     `MetaLabelStrategy` падає fail closed.
   - Тести: [`tests/unit/test_meta_label.py`](../tests/unit/test_meta_label.py) та
     [`tests/integration/test_meta_label_context_backtest.py`](../tests/integration/test_meta_label_context_backtest.py).

---

### Фаза G3 — Трек B: Біржові ф'ючерси COMEX (`GC` / `MGC` / `1OZ`) через Databento — ✅ Реалізовано

**Мета:** Дозволити бектест на 10–15 роках інституційних даних CME/COMEX у `nautilus-lab`
із чесним QC, чесною ануалізацією і чесними per-contract витратами.

1. **✅ Реалізовано — Торгові календарі в домені (`src/nautilus_lab/domain/calendar.py`)**
   - `TradingCalendar(StrEnum)`:
     - `CRYPTO_24_7` (типово — 100% зворотна сумісність)
     - `CME_GLOBEX_23_5` (Нд 18:00 ET – Пт 17:00 ET, щоденна перерва 17:00–18:00 ET, свята CME)
     - `CME_1OZ_24_7` (24/7 з липня 2026 окрім короткої суботньої техперерви 02:00–03:45 CT)
   - [`domain/data_quality.py`](../src/nautilus_lab/domain/data_quality.py): `check_bars(..., calendar=TradingCalendar.CRYPTO_24_7, roll_timestamps=...)` — інтервали поза торговим календарем не рахуються в `missing_bars` і не тригерять `QualityStatus.FAIL`.
   - [`domain/metrics.py`](../src/nautilus_lab/domain/metrics.py): функція `periods_per_year(interval, calendar)` (`CME_GLOBEX_23_5`: `1d → 252`, `1h → 5796`, `4h → 1449`, `15m → 23184`).
   - Тести: [`tests/unit/test_data_quality.py`](../tests/unit/test_data_quality.py), [`tests/unit/test_metrics.py`](../tests/unit/test_metrics.py).

2. **✅ Реалізовано — Підтримка `FuturesContract` і валюти `USD` (`instrument.py`, `backtest_runner.py`, `risk.py`, `marking.py`)**
   - У `instrument.py`: додано специфікації COMEX (`GC`, `MGC`, `1OZ`) із
     `FuturesContract` (`AssetClass.COMMODITY`, `currency=USD`, `multiplier=100|10|1`,
     `price_increment=0.10` для `GC`/`MGC`, `0.25` для `1OZ`, `venue=XCEC` або `GLBX`),
     плюс `instrument_multiplier()` і динамічний розбір тікерів COMEX.
   - У `backtest_runner.py`: `venue` і `base_currency` беруться з `instruments[0].quote_currency`
     (`USDT` або `USD`) із fail-closed перевіркою змішування валют/бірж/типів контрактів;
     `multiplier` враховується в `size_position()`, `size_spread()`, `OpenLot` і `_traded_notional`.

3. **✅ Реалізовано — Per-contract модель комісій (`domain/fees.py`, `settings.py`, `backtest_runner.py`)**
   - Додано `FuturesFeeSchedule` та реєстр `FUTURES_COST_PROFILES`:
     - `comex_mgc_ibkr`: \$0.85/контракт/сторону + 1 тік проковзування
     - `comex_gc_ibkr`: \$2.47/контракт/сторону + 1 тік проковзування
     - `comex_1oz_ibkr`: \$0.50/контракт/сторону + 1 тік проковзування
     - `comex_stress_x2`: подвоєні витрати й проковзування (\$1.70/контракт + 2 тіки)
   - У `backtest_runner.py`: для `FuturesContract` застосовується `PerContractFeeModel`.
   - Тести: [`tests/integration/test_gold_futures_backtest.py`](../tests/integration/test_gold_futures_backtest.py), [`tests/unit/test_cost_profiles.py`](../tests/unit/test_cost_profiles.py), [`tests/unit/test_risk.py`](../tests/unit/test_risk.py).

4. **✅ Реалізовано — Інгест Databento (`infrastructure/databento_feed.py`, CLI `lab ingest-databento`)**
   - Опційна екстра в `pyproject.toml`: `databento` (`databento>=0.40`), а офлайн-імпорт `.dbn`/`.dbn.zst` працює нативно через `nautilus_trader.adapters.databento.loaders.DatabentoDataLoader`.
   - Обов'язковий інваріант: `bars_timestamp_on_close=True` (`False` блокується fail closed проти look-ahead bias).
   - Узгодження кодів року (`futures_year_digits=2`), детектор роловерів контрактів (`detect_contract_rolls`), збереження таблиці рол-дат (`JsonRollStore` → `roll_dates.json`) та ізоляція роловерів у `check_bars`.
   - **API-ключ Databento** (`DATABENTO_API_KEY`) — лише у `.env` (маскується в `/api/settings`), ніколи не потрапляє в логи чи помилки; `lab live` лишається fail closed.
   - Тести: [`tests/unit/test_databento_feed.py`](../tests/unit/test_databento_feed.py).

---

## 6. Протокол валідації золота (`PromotionGate` v2 + пререєстрація)

Будь-який робот на золоті вважається `candidate` (не `validated`), доки не пройде **всі**
перевірки нижче за один пререєстрований прогін (`lab research --register`):

1. **Walk-forward мінімум 6 rolling-фолдів** (`min_folds = 6`) із `embargo_bars >= 10`
   (для `1h` — ≥10 годин розриву; для `4h`/`1d` — мінімум 2–5 барів без перекриття).
   - **Увага до `XAUUSDT-PERP`:** поки історія коротша за ~2 роки (запуск 05.01.2026),
     робот на `XAUUSDT-PERP` **не може** отримати статус `validated` — використовуйте
     `PAXGUSDT-PERP` (2020–2026) або COMEX `MGC` (2015–2026) для багаторічного walk-forward,
     а `XAUUSDT-PERP` — для перевірки виконання й live paper.
2. **Чесний бенчмарк:** OOS-доходність має перевершити **buy&hold золота** (і
   volatility-matched buy&hold) за той самий OOS-період. Плюсові +15% у 2025–2026, коли
   золото виросло на +60%, **не є перевагою**.
3. **Кількість угод і стабільність:** `oos_fills >= 30`, частка прибуткових OOS-фолдів
   `>= 83%` (5 з 6).
4. **Анти-перенавчання:** `PBO <= 0.30` (CSCV, `--pbo`) і `DSR >= 0.95` із урахуванням
   **усіх** попередніх спроб у `research/trials.jsonl`.
5. **Запас по витратах:** `breakeven_cost_bps > paid_cost_bps + 5 bps` і позитивний OOS
   під `COST_PROFILE=stress_x1_5` (для COMEX — `comex_stress_x2`).
6. **Стрес-слайси:** жодного маржин-колу чи пробою `MAX_DRAWDOWN` на `gold_rates2022`
   (боковик/зниження) і `gold_blowoff2026` (екстремальний спалах волатильності +20%/−20%).
7. **Регресія існуючого проєкту:** `pytest` (вкл. `test_golden_backtest.py`,
   `test_specs.py`, `test_status_doc.py`), `ruff`, `mypy --strict`, покриття `>= 80%`,
   `lab live` повертає код `1`.

---

## 7. Джерела (2025–2026)

1. Singha, Aguilera-Toste & Lahiri (Nov 2025), *Forecast-to-Fill Quantitative Trend–Momentum
   on COMEX Gold Futures (2015–2025)*, `arXiv:2511.08571`.
2. GBDT + SHAP Feature Importance Study on Daily COMEX Gold Futures 2010–2025 (Nov 2026):
   LightGBM robustness; futures basis & medium-term momentum as primary drivers, silver /
   VIX / WTI as secondary drivers.
3. Mittal & Mittal (Nov–Dec 2025), *Dynamic Statistical Arbitrage on Gold–Silver (`GC–SI` /
   `GLD–SLV`) via Kalman Filtering and ML Regime Classifiers*, SSRN / Authorea.
4. Barzykin, Bergault & Guéant (*arXiv / Risk.net*), *Spot–Futures Gold Cointegration and
   Nested Ornstein-Uhlenbeck EFP Basis Modeling*.
5. MDPI Study (Jul 2026), *32 Regularized Regression & PCA Models on Gold (2020–2026)*:
   forecast accuracy (MAPE) vs net trading alpha gap.
6. Wicko Strategy Lab (Nov 2026), *Standardized XAUUSD Session Breakout Backtests
   (2021–2026)* & Forge Strategy Lab (Nov 2026), *XAUUSD Intraday Session Range & Asian Break
   Statistics*.
7. CME Group (2026): percentage-of-notional gold margining (Jan 2026) & 24/7 continuous
   trading for 1-Ounce Gold Futures (`1OZ`, Jul 2026).
8. Binance Announcements & API Specs (2026): `XAUUSDT` TradFi Perpetual (`TRADIFI_PERPETUAL`,
   Jan 5, 2026), `XAUTUSDT` Spot & Perpetual (Mar 26, 2026), `PAXGUSDT` Spot & Perpetual.
9. NautilusTrader Docs (2025–2026): Databento (`GLBX.MDP3`, `bars_timestamp_on_close=True`,
   `use_exchange_as_venue=True`, `futures_year_digits`) & Interactive Brokers adapters.

---

## 8. Емпіричні результати Треку A (Binance Gold/Silver, `catalog_gold_1h`)

Усі прогони нижче виконані на реальному публічному каталозі `catalog_gold_1h/` (`1h`)
за єдиним протоколом [`PromotionGate`](../src/nautilus_lab/application/promotion_gate.py)
проти `buy&hold` золота та `vol_matched_buy_hold` за ідентичні OOS-вікна (`binance_vip0_bnb`
типово; окремо перевірено `stress_x1_5`).

### 8.1 Зведена таблиця на `PAXGUSDT-PERP.SIM` (6 rolling-фолдів, OOS `2026-05-27..2026-11-25`)

| Стратегія | Фолдів | Fills | Gross | Net OOS | `buy&hold` | `vol_matched` | Breakeven | PBO / DSR (`--pbo`) | `stress_x1_5` OOS | Вердикт Promotion Gate v2 |
|---|---|---|---|---|---|---|---|---|---|---|
| `ema` (baseline) | 4/6 | 150 | +0.30% | **-0.54%** | -3.58% | -2.00% | 1.18 bps | — | — | ❌ `REJECT` (`alpha_breakeven=fail`) |
| `H-GOLD-01` (`regime` gold F2F) | 2/6 | 74 | +0.81% | **+0.41%** | -3.58% | -1.13% | **10.28 bps** | `0.5143` / `0.4219` | **+0.21%** (`2/6`) | ❌ `REJECT` (`profitable_folds=fail`, `pbo=fail`) |
| `H-GOLD-02` (`gold_session_orb` до фіксу ATR) | 0/6 | **0** | 0.00% | **0.00%** | -3.58% | — | — | — | — | ❌ `REJECT` (несоосність 1h vs daily ATR) |
| `H-GOLD-02B` (`gold_session_orb` SDD `[2.5..4.5]`) | 1/6 | 32 | -0.12% | **-0.31%** | -3.58% | +0.10% | -11.88 bps | `0.5714` / `0.0555` | **-0.40%** (`1/6`) | ❌ `REJECT` (`alpha_gross`, `pbo`, `dsr`, `folds`) |
| `pairs` `XAUUSDT–XAGUSDT` (OLS) | 0/6 | 40 | -0.18% | **-0.38%** | -3.97% | -0.17% | -3.84 bps | — | — | ❌ `REJECT` (`alpha_gross=fail`) |
| `pairs` `XAUUSDT–XAGUSDT` (Kalman `δ=0.005`) | 0/6 | **0** | 0.00% | **0.00%** | -3.97% | — | — | — | — | ❌ `REJECT` (ворота ADF чесно заблокували) |
| `pairs` `PAXGUSDT–XAUUSDT` (Kalman `δ=0.005`) | 0/6 | 12 | +0.02% | **-0.06%** | -3.51% | — | 1.46 bps | — | — | ❌ `REJECT` (`oos_fills < 30`, `folds=fail`) |
| `meta_label` 13 ознак (`paxg_meta_base`) | 3/6 | 68 | +0.93% | **+0.45%** | -3.58% | -0.72% | 9.78 bps | — | — | ⚠️ `INCOMPLETE` (без PBO/DSR, `folds 3/6 < 5/6`) |
| `meta_label` 21 ознака (`paxg_meta_ctx`: basis+DST) | 2/6 | 42 | +1.24% | **+0.92%** | -3.58% | -0.04% | **13.73 bps** | `0.4143` / `0.0223` (`days=180`) | **+0.83%** (`2/6`) | ❌ `REJECT` (`profitable_folds`, `pbo=0.414 > 0.30`) |
| `funding` carry (`PAXG/USDT`–`PAXGUSDT-PERP`) | 2/6 | **8** | +0.17% | **+0.10%** | -3.58% | -0.18% | **14.88 bps** | — | — | ❌ `REJECT` (`oos_fills=8 < 30`, `folds=2/6`) |

> [!NOTE]
> Обидві моделі `meta_label` навчено **строго** на історії `<= 2026-05-26` (404 події, 5-fold
> purged CV: 13 ознак — `accuracy=64.75%`, 21 ознака — `accuracy=66.50%`), перед тим як
> оцінювати їх на OOS-вікні `2026-05-27..2026-11-25` (нульовий витік перевірено `require_clean_model`).

### 8.2 Стрес-слайси та багаторічний `PAXG/USDT.SIM`

- **`H-GOLD-01` (`regime` gold forecast-to-fill):**
  - `gold_rates2022` (`PAXG/USDT.SIM`, `2022-03-01..2022-11-15`, 4 фолди): `1/4`, `mean_oos = -0.04%` (`+0.18%` gross, `16 fills`, `BE = 0.79 bps`) проти `buy&hold = +0.32%` — мінімальні втрати в циклі підняття ставок ФРС.
  - `gold_blowoff2026` (`PAXGUSDT-PERP.SIM`, `2026-01-01..2026-04-01`, 4 фолди): `3/4`, `mean_oos = +0.43%` (`+0.62%` gross, `30 fills`, **`BE = 18.35 bps`**) проти `buy&hold = -2.54%` і `vol_matched = -0.60%`.
  - **4-річний багатоциклічний прогін** `PAXG/USDT.SIM` (`--days 1460 --folds 2`, `2022-11-26..2026-11-25`, 150 OOS fills): `profitable = 2/2`, `mean_gross = +9.46%`, **`mean_oos = +5.74%`** (`fold 0 +11.17%` vs `+31.97%`; `fold 1 +0.32%` vs **`-26.26%`**), обійшов `buy&hold (+2.85%)` і `vol_matched (+0.25%)` із **`BE = 17.60 bps`** (`donchian=120, bb_k=3` на обох фолдах; але `folds=2 < 6`, тому `REJECT`).
- **`gold_session_orb` (`H-GOLD-02B`, SDD `[2.5, 3.5, 4.5]`):**
  - `gold_rates2022` (`PAXG/USDT.SIM`, 4 фолди): `2/4`, `mean_oos = -0.35%` (`+0.17%` gross, `34 fills`, `BE = 1.57 bps`).
  - `gold_blowoff2026` (`PAXGUSDT-PERP.SIM`, 3 фолди): `0/3`, `mean_oos = -0.48%` (`6 fills`, `BE = -42.40 bps`).
  - **Повний 6.25-річний цикл** `PAXG/USDT.SIM` (`2020-08-28..2026-11-25`, 54 697 барів, 3 фолди, OOS `2025-01..2026-11`, **250 fills**): `profitable = 0/3`, **`mean_gross = +2.43%`**, **`mean_oos = -2.29%`**, `breakeven = 3.46 bps` (< 7.5 bps спот-комісії Binance), проти `buy&hold = +13.48%`.

### 8.3 Ключові інженерні й дослідницькі висновки

1. **Емпірична перевага алгоритмів збігається з прогнозом літератури (§4), але жоден не має `validated`:**
   - Наївні `ema` та пробійні `gold_session_orb` на `1h` Binance втрачають на витратах (breakeven `1.18–3.46 bps` < 5–7.5 bps комісій).
   - **Forecast-to-Fill `regime`** і **Context `meta_label` (21 ознака)** дають стабільно плюсовий грос- і нетто-OOS із `breakeven = 10.28–17.60 bps` та переживають `stress_x1_5`, а на багаторічному `PAXG/USDT.SIM` `H-GOLD-01` захищає капітал при падінні золота `-26.26%`. Водночас на короткій 1.6-річній вибірці перпу вони проходять лише `2/6` фолдів та мають `PBO > 0.30`.
2. **Виявлені баги, закриті в процесі валідації:**
   - *Spot fractional `PAXG` qty quantization* у [`bar_feed.py`](../src/nautilus_lab/infrastructure/nautilus/bar_feed.py): `size_precision=4` для спотового `PAXG/USDT.SIM` замість `8`, що раніше обнуляло/відхиляло ордери.
   - *Несоосність шкали ATR у `gold_session_orb`*: денні значення `GOLD_ORB_MAX_BOX_ATR=[0.6, 0.8, 1.0]` на `1h ATR(14)` (`med(box/ATR) = 2.96`) давали `0 fills`; після SDD-фіксу на `[2.5, 3.5, 4.5]` робот генерує репрезентативні 32–250 угод.
3. **Справжня перевірка Трек B (COMEX `MGC`/`GC`/`1OZ`):** рушій Фази G3 повністю готовий (`lab ingest-databento`), тому наступний чесний крок — 10–15-річний багатоциклічний walk-forward для `H-GOLD-01`, `meta_label` 21-feat і `gold_session_orb` на ф'ючерсах COMEX з нижчими інституційними витратами.

### 8.4 Багаторічний `4h` (`2020–2026`), `XAUUSDT-PERP` та paper-сесія (`catalog_gold_4h` / `catalog_gold_1h`)

- **6.25-річний `4h` `PAXG/USDT.SIM` (`catalog_gold_4h/`, `13 679` барів, `2020-08-28..2026-11-25`, 6 rolling-фолдів OOS `2025-01-12..2026-11-25`):**
  - `H-GOLD-4H-01` (`regime` gold F2F, пререєстрація `93d8c06721a4` `matched`): `profitable = 4/6`, `mean_gross = +1.03%`, **`mean_oos = +0.55%`**, `118 fills`, **`breakeven = 12.12 bps`**, `exposure = 18.59%`, але програє `buy&hold = +5.82%` і `vol_matched = +1.06%` → `REJECT`. Натомість аудит PBO/CSCV (8 блоків × 15 конфігів) показав **`PBO = 0.0571` (`PASS <= 0.30`)** (`DSR = 0.1024 < 0.95` через боковий ринок 2020–2023 при `15 bps` спот-RT витратах).
  - `ema` baseline (`4h`, `6` фолдів): дав привабливий OOS `+4.17%` (`4/6`, `160 fills`, `breakeven = 71.84 bps`), але PBO/CSCV викрив класичне перенавчання: **`PBO = 0.7286`** (> 0.50), `DSR = 0.4712` → ❌ `REJECT`.
- **Binance TradFi `XAUUSDT-PERP.SIM` (`1h`, `8 377` барів, `2025-12-11..2026-11-25`, 6 rolling-фолдів):**
  - `H-GOLD-01` (`regime` gold F2F): `profitable = 4/6`, `mean_gross = +0.94%`, **`mean_oos = +0.71%`**, `42 fills`, **`breakeven = 26.78 bps`** (>5× від taker fee `5 bps`), випередив `buy&hold (-3.50%)` і `vol_matched (-0.91%)`, `donchian=120` у всіх 6 фолдах (історія < 2 років — слугує перевіркою виконання, не промоції).
  - `gold_session_orb` (`H-GOLD-02B`): `profitable = 1/6`, `mean_oos = -0.14%`, `20 fills`, `breakeven = -18.49 bps` vs `vol_matched = -0.12%` → ❌ `REJECT`.
- **Контрольна paper-репетиція (`lab paper --robot regime --bars 1000 --journal`, `2026-10-14..2026-11-25`):**
  - `PAXGUSDT-PERP.SIM`: `18 fills` (9 позицій), точність квантизації `0.001`, комісії `\$574.33`, `max_dd = 1.32%`, `open_position = flat`.
  - `XAUUSDT-PERP.SIM`: `18 fills` (9 позицій), комісії `\$502.31`, `max_dd = 1.36%`, `open_position = flat`. Зафіксовано в `reports/paper/sessions.jsonl` без жодної відправки ордерів на біржу.


