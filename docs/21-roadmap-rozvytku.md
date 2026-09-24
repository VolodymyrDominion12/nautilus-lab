# 21. Стратегічний роудмап розвитку Nautilus Lab

> **Призначення документу:** Комплексний план еволюції дослідницької лабораторії торгових роботів `nautilus-lab` на 2026 рік. Документ містить чесний аудит поточних Out-of-Sample результатів, розкриває фундаментальні причини відставання стратегій від Buy & Hold, визначає 5 фаз розвитку, пріоритизовану матрицю задач та жорсткі критерії переведення торгових роботів зі статусу `candidate` у `validated`.

---

## 1. Чесний аудит поточного стану (вересень 2026)

### 1.1. Що вже реалізовано на рівні інфраструктури та архітектури ✅

Платформа `nautilus-lab` має міцний інженерний фундамент, побудований за стандартами квант-досліджень інституційного рівня:

| Компонент / Механізм | Стан у коді | Призначення та надійність |
|---|---|---|
| **Event-Driven Engine** | NautilusTrader (Rust core) | Високоточна симуляція виконання барів із затримкою 50 мс, комісіями та проковзуванням. |
| **Чиста 4-рівнева архітектура** | `domain` / `application` / `infrastructure` / `interfaces` | Повна ізоляція бізнес-правил (`domain/` не залежить від Nautilus, не читає `.env`, не використовує `float`). |
| **Spec-Driven Development** | `specs/strategies/*.yaml`, `_validator.py` | Жорстка верифікація параметрів, мінімальних барів і джерел сіток до запуску коду. |
| **Walk-Forward з Embargo** | `domain/walk_forward.py`, `application/run_walk_forward.py` | Запобігання витоку інформації у майбутнє (data leakage) за рахунок ізоляції OOS та буферних барів. |
| **Аудит перенавчання (PBO & DSR)** | `domain/overfitting.py`, `domain/deflated_sharpe.py`, `--pbo` | Розрахунок CSCV ймовірності перенавчання (PBO) та дефльованого коефіцієнта Шарпа (DSR). |
| **Байєсівська оптимізація** | `application/optuna_optimizer.py`, `--optuna` | Підбір гіперпараметрів алгоритмом Tree-structured Parzen Estimator (TPE). |
| **Стрес-тестування на слайсах** | `domain/stress_slices.py`: `covid2020`, `ftx2022`, `etf2024` | Перевірка поведінки системи під час структурних шоків ліквідності та волатильності. |
| **Ризик-оверлеї** | `domain/portfolio_risk.py`, `application/risk.py` | Волатильне масштабування (vol-scaling), VaR/CVaR запобіжники, трейлінг-стопи, денний ліміт збитків. |
| **Звітність та моніторинг** | HTML-тиршити (`--tearsheet`), сповіщення (`--notify`), Web UI | Повна візуалізація метрик у React+FastAPI дашборді та інтерактивних звітах. |
| **Офлайн Alpha Proposer** | `lab propose`, Factor DSL, AST Guard | Генерація гіпотез мовною моделлю виключно в офлайн-контурі (без LLM на гарячому шляху бектесту). |

Поза цим переліком у коді вже є механізми, яких роудмап не згадує взагалі, — і це
теж частина чесного аудиту стану: попередньо зареєстровані **ворота допуску**
(`application/promotion_gate.py`, друкуються як `promotion_gate=...` у `lab research
--folds`/`--pbo` і `lab xsmom --pbo`; пороги й результат — `docs/25` §4–6),
крос-секційний momentum з власним симулятором (`domain/xsmom.py`,
`application/xsmom_backtest.py`, `lab xsmom`), paper-сесії з журналом
(`infrastructure/paper_sessions.py`, `lab paper`), живий paper-контур у дашборді
(`api/live_sessions.py`, `infrastructure/live_bar_feed.py`), ingest тіків і глибини
книги (`lab ingest --trades`, `--live-ticks`, `--depth`) та деплой
(`deploy/docker-compose.yml`, `docs/26`). Перевіряти їхній стан треба по коду, а не
по цьому документу.

---

### 1.1.1. Стан реалізації фаз (звірено з кодом)

Таблиця вище описує `✅` як «є в коді». Нижче — стан саме пунктів **плану** (§3–§7):
що з них уже зроблено, а що ні. Посилання ведуть на файли, за якими це видно.

| Пункт роудмапу | Заявлений у плані стан | Фактичний стан у коді |
|---|---|---|
| §3.1 Cost-Aware Selection | «проблема: ранжує лише за капіталом» | ✅ **виконано**: `application/score.py:22-59` (штраф `turnover_haircut`, метрики `pnl`/`sharpe`/`calmar`), `SELECTION_METRIC` у `.env.example` |
| §3.2 Активація фракційного Келлі | «викликається без статистики, no-op» | ✅ **виконано (opt-in)**: `application/risk.py:83-160`, `TradeStats` у `signal_strategy.py:171,410` і `spread_strategy.py:103,161`; виміру на OOS **немає** (`USE_FRACTIONAL_KELLY=false` типово) |
| §3.3 GJR-GARCH поряд з EGARCH | «треба додати» | ✅ **виконано**: `infrastructure/egarch_forecast.py:17` (`gjr_garch_forecast_volatility`), вибір моделі в `infrastructure/vol_forecast.py:117-121`, `VOL_MODEL`/`VOL_REFIT_EVERY` у `settings.py` та `.env.example:65-74` |
| §3.4 Real-time сповіщення при спрацюванні Circuit Breakers | «викликати нотифікатор у момент спрацювання» | ❌ **не виконано**: є лише підрахунок блокованих входів (`RiskBreachTally`, `application/risk.py:50-80`) і підсумок **після** прогону (`risk_breaches blocked=...`, `cli.py:964,1227,1263`); усі виклики `AlertNotifier` — завершальні (`cli.py:646-857`, `api/research_runner.py:285-462`), у момент спрацювання не сповіщає ніщо |
| §3.5 Емпіричні квантилі z-score | «замінити фіксовані пороги» | ✅ **виконано (opt-in)**: `domain/quantiles.py`, гілка в `pairs_trading.py:107-131`, `PAIRS_Z_ENTRY_QUANTILE` (типово `0` = старі фіксовані пороги) |
| §4.1 Funding Cash-and-Carry | «повна інтеграція» | 🟡 **частково**: шар даних є (`lab ingest --funding`, `infrastructure/funding_catalog.py`, `application/ingest_funding_history.py`), спека v1.1 — теж; адаптера немає (`funding` **не** в `BACKTEST_WIRED_ROBOTS`, `domain/regime.py:35-45`) і нарахування фандингу в рушії немає → статус робота `blocked` |
| §4.2 Фільтр Калмана для β (Pairs) | «реалізувати» | ❌ **не виконано**: `grep -rn kalman src/` порожній; β рахується рефітом (`PAIRS_REFIT_EVERY`) |
| §4.3 Тест Йогансена (3+ активи) | «новий файл `domain/pairs/johansen.py`» | ❌ **не виконано**: файла немає, `grep -rn johansen src/` порожній; у `domain/pairs/` є лише `cointegration.py` (ADF), `ou.py`, `pairs_trading.py`, `params.py` |
| §4.4 ML Pipeline OBI + LightGBM | «кроки 1–4» | ✅ **виконано, виміру немає**: навчання `lab ml train --model-type obi` (`application/train_obi.py`, `train_classifier.py`), TBM у `domain/triple_barrier.py`, purged K-fold; робот `ml_obi` у `BACKTEST_WIRED_ROBOTS`; знімки книги — `lab ingest --depth` + `infrastructure/orderbook_catalog.py`. `specs/strategies/ml_obi.yaml`: `evidence.measured: false` |
| §4.5 Ансамблевий роутер сигналів | «новий файл `domain/ensemble_router.py`» | ❌ **не виконано**: файла немає; `domain/regime_router.py` — це перемикання підстратегій за режимом, а не зважене голосування кількох роботів |
| §5.1 Перехід на 5m/15m | «всі симуляції на `1h`» | ❌ **не виконано**: `infrastructure/timeframe.py` уже знає `1m/5m/15m/1h/4h/1d`, але в каталозі лежать лише серії `-1-HOUR-` і `-1-DAY-` (`catalog/data/bar/`); прапорця `--interval` у `lab ingest` немає — інтервал береться з `BAR_INTERVAL` |
| §5.2 Публічний WS фід для paper | «новий файл `binance_ws.py`» | ✅ **виконано**: `infrastructure/binance_ws.py` (лише закриті бари, реконект із backoff), `infrastructure/live_bar_feed.py`, `lab paper --source live [--live-bars N]` |
| §5.3 Збір L2 стакану | «опитування `GET /api/v3/depth?limit=50`» | ✅ **виконано, але інакше**: не REST-полінг, а WebSocket-потік `@depth20@100ms` (`infrastructure/binance_orderbook.py`), запис у `infrastructure/orderbook_catalog.py`, команда `lab ingest --depth` |
| §6.1 GLFT з моделлю черги | «вимоги для запуску» | ❌ **не виконано**: домен є (`domain/glft.py`), але споживача `QuoteIntent` немає і рушій не моделює чергу лімітних ордерів — `specs/strategies/glft.yaml` → `status: blocked`, `lab research --robot glft` падає з кодом 1 |
| §6.2 Багатовимірний Hawkes | «перехід до двовимірної системи» | 🟡 **частково**: двовимірне взаємне збудження вже в домені (`domain/hawkes.py:52-53`, параметр `cross_alpha`), але він **не виведений у `Settings`/`.env`** і типово `0.0`, тобто в прогонах процес лишається одновимірним |
| §7.1 Покриття 80% → 90% | «підвищити» | ❌ **не виконано як ціль 90%**, але попередній борг закрито: виміряно зараз — `pytest --cov` дає **80.50%** при `fail_under = 80` (було 76.7%); адаптери далі виключені з покриття (`pyproject.toml:144-148`) |
| §7.2 Автоматична верифікація docs↔код | «розширити `_validator.py`» | ✅ **виконано у вужчому обсязі**: `specs/_validator.py:569+` (`check_docs_alignment`) звіряє таблицю `docs/05-roboty.md` з `BACKTEST_WIRED_ROBOTS` і `RobotName`; інші документи в `docs/` не парсяться |
| §7.3 Автоматичний аудит та CI/CD | «налаштувати GitHub Actions» | ✅ **виконано**: `.github/workflows/ci.yml` — ruff check, ruff format --check, mypy, валідатор спек, pytest, smoke-бектест, виконання зошита; крок `--cov` лишається `continue-on-error` |
| §10 Критерії приймання (DoD) | «ручний чекліст» | 🟡 **з'явився машинний гейт, але з іншими порогами**: `application/promotion_gate.py` (фолдів ≥ 6, прибуткових ≥ 83%, OOS-угод ≥ 30, PBO ≤ 0.3, DSR ≥ 0.95 — `docs/25` §4). Пороги чекліста §10 нижче (фолди ≥ 4, PBO < 0.25, DSR p < 0.05, breakeven > paid + 5 bps), тож чекліст лишається окремим, суворішим правилом research |

---

### 1.2. Реальні торгові результати: відсутність OOS переваги ⚠️

Попри якісну інфраструктуру, **жодна з існуючих торгових стратегій наразі не демонструє стійкої статистичної переваги над пасивним утриманням (Buy & Hold)** на валідаційних вибірках.

#### Результати тестування на 4 ковзних фолдах Walk-Forward (OOS: 2025-11-22 … 2026-09-14, ETH/USDT, 1h бари):

| Стратегія (Робот) | Статус у специфікаціях | OOS Mean Return | Baseline Buy&Hold Mean | Альфа проти Buy&Hold | Висновок аудиту |
|---|---|:---:|:---:|:---:|---|
| **Baseline (Buy & Hold)** | *Еталон* | **+2.50%** | **+2.50%** | 0.00% | Пасивне утримання інструменту на OOS інтервалі |
| `regime` | `candidate` | **+0.58%** | +2.50% | −1.92% | Торгує в плюс, але суттєво відстає від простого холду; високі транзакційні втрати |
| `ema` | `candidate` | **−4.05%** | +2.50% | −6.55% | Класичний перетин ковзних генерує збитки через запізнення сигналів у флеті |
| `pairs` | `candidate` | **−4.41%** | +2.50% | −6.91% | Статистичний арбітраж розпадається під час розходження трендів ETH/BTC |
| `adaptive_ema` | `rejected` | **Збитковий** | +2.50% | Відхилено | Гіпотезу динамічного згладжування спростовано прямим виміром (`docs/18 §3`); числа A/B-контролю — у `rejection_reason` спеки: ETH selectivity 0 → −3.80%, 0.5 → −3.83%, 1 → −3.38% при buy&hold +2.44% |
| `vpin_momentum` | `candidate` | **0.00%** (0 філів) | +1.67% *(свій OOS-набір)* | Від'ємна | Вимір **є** (`specs/strategies/vpin_momentum.yaml`, v1.1): на справжньому потоці тейкерів робот не торгує взагалі (`oos_fills=0`), на tick-rule-проксі тієї ж серії — OOS mean −5.44%. Поріг токсичності 0.7 на реальних даних не досягається (максимум 0.694) |
| `formulaic_lgbm` | `candidate` | **Виміряно, від'ємний** | — | Від'ємна | Вимір **є**: 0/4 прибуткових фолдів, середній OOS нижчий за buy&hold, вердикт `does not beat buy&hold` (`specs/strategies/formulaic_lgbm.yaml` → `evidence.measured: true`). Потрібен навчений бустер: `scripts/train_formulaic_lgbm.py` |
| `meta_label` | `candidate` | *Не виміряно* | +2.50% | — | Окремий фільтр первинних сигналів, залежить від базового робота. `evidence.measured: false` — чисел немає й не вигадуються |
| `ml_obi` | `candidate` | *Не виміряно* | — | — | Підключений до рушія (`BACKTEST_WIRED_ROBOTS`), фід книги є (`lab ingest --depth`), але в каталозі 1 доба знімків: `evidence.measured: false` |

**Про числа в цій таблиці.** Рядки `regime`, `ema`, `pairs` і планка `+2.50%` — це фолд-таблиця
`docs/05-roboty.md` §4 за той самий OOS-період (2025-11-22 … 2026-09-14); спеки цих роботів
(`evidence.reproduce`) посилаються саме туди й навмисно не дублюють числа. Рядки
`vpin_momentum`, `formulaic_lgbm`, `ml_obi`, `meta_label`, `adaptive_ema` звірені з полями
`evidence` / `rejection_reason` у `specs/strategies/*.yaml` — це єдине місце, де числа про
результати зафіксовані разом зі статусом. OOS-набори в різних рядків **різні** (у
`vpin_momentum` buy&hold планка +1.67%), тому альфу між рядками порівнювати не можна.

---

### 1.3. Чому роботи відстають: фундаментальні причини

```
  1-годинний закритий бар (1h close)
 ├─────────────────────────────────────────► 
 [Початок бару]      [Рух ціни всередині]     [Закриття бару: СИГНАЛ] ──► [Виконання + 50ms лаг]
                                                                        ▲
                                                        Ціна вже реалізувала 80-90% руху;
                                                        стратегія заходить у хвіст імпульсу,
                                                        сплачуючи Taker Fee (0.05%) та спред.
```

1. **Інформаційне запізнення (Alpha Decay на 1h барах):**
   Роботи приймають рішення лише на закритті 1-годинної свічки (`RollingWindow.prior()`). До моменту генерації сигналу внутрішньоденний імпульс уже здебільшого відпрацьований ринком. Вхід відбувається на локальних екстремумах.
2. **Невідповідність цільової функції відбору (Cost-Agnostic Score):** *(на момент написання плану; закрито §3.1)*
   Функція `in_sample_score()` у `application/score.py` максимізувала кінцевий баланс (`result.ending_balance`), ігноруючи кількість угод та сплачену комісію (`fees_paid`). Тепер вона додатково штрафує оборот (`turnover_haircut`) і вміє ранжувати за `sharpe`/`calmar`, а комісії **не** віднімаються вдруге — вони вже в `ending_balance` (`docs/22` §2.1).
3. **Відсутність мікроструктурного контексту:**
   Стратегії не мають доступу до стакану лімітних заявок (L2 Order Book) та потоку ордерів. Сигнал опирається виключно на геометрію минулих цін. *(Поточний стан: потік тейкерів із klines читається й доходить до `BarVpin` — `docs/23` §6, фаза 4; знімки книги збираються `lab ingest --depth`, але їх поки що 1 доба на 2 символи, тому `ml_obi` лишається без виміру.)*
4. **Неактивні модулі:**
   У кодовій базі створені математичні моделі, споживача в CLI-циклі досі не мають **`domain/funding.py`** (`funding` не в `BACKTEST_WIRED_ROBOTS`, `specs/strategies/funding.yaml` → `blocked`) і **`domain/glft.py`** (немає споживача `QuoteIntent`, `specs/strategies/glft.yaml` → `blocked`). **`domain/ml_obi_strategy.py` із цього переліку вибув**: робот підключений до рушія й до paper, лишається тільки вимір.

---

## 2. Стратегічні фази розвитку

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   ФАЗА 1: Швидкі перемоги (1–4 тижні)                             │
│  Cost-Aware Selection • Активація Келлі • GJR-GARCH • Circuit Breakers • Z-квантилі│
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│                   ФАЗА 2: Нові роботи та інтеграція модулів (1–3 місяці)          │
│  Funding Cash&Carry • Фільтр Калмана (β) • Johansen (3+ пар) • ML-пайплайн • Ансамблі│
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│                   ФАЗА 3: Дані, таймфрейми та мікроструктура (2–4 місяці)         │
│  Перехід на 5m/15m • Багатотаймфреймові бари • Публічний WS фід • L2 Order Book   │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│                   ФАЗА 4: Просунутий маркет-мейкінг та моделі (3–6 місяців)       │
│  GLFT з моделлю черги • Multivariate Hawkes • Селективний DRL алокатор            │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
┌────────────────────────────────────────▼─────────────────────────────────────────┐
│                   ФАЗА 5: Інженерна якість, CI/CD та DevOps (Постійно)            │
│  Тестове покриття 90% • Автоматична валідація docs • Живі specs • CI пайплайн    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Схема вище — це **задум** фаз, не їхній стан. Стан на момент останньої звірки з кодом
(таблиця §1.1.1; посилання — на файли, за якими це видно):

| Фаза | Що з неї вже в коді | Що лишається |
|---|---|---|
| 1. Швидкі перемоги | Cost-Aware Selection (`score.py:22-59`), Z-квантилі (`domain/quantiles.py`), GJR-GARCH (`egarch_forecast.py:17` + `VOL_MODEL`), Келлі (opt-in: `risk.py:131-160`) | real-time алерти circuit breaker (`§3.4`); вимір Келлі на OOS |
| 2. Нові роботи та модулі | `ml_obi` підключено до рушія; дані фандингу й спека funding v1.1 | адаптер і нарахування фандингу в рушії; Калман; Johansen; ансамблевий роутер |
| 3. Дані, таймфрейми, мікроструктура | публічний WS-фід для paper (`binance_ws.py`, `lab paper --source live`), збір глибини книги (`lab ingest --depth`), потік тейкерів із klines (`taker_flow_catalog.py`) | перехід на 5m/15m (каталогу немає); обсяг даних книги для виміру `ml_obi` |
| 4. Просунутий ММ та моделі | двовимірне ядро Хоукса в домені (`hawkes.py:52-53`) | GLFT із моделлю черги; вмикання `cross_alpha`; DRL-алокатор |
| 5. Інженерна якість | CI-пайплайн (`.github/workflows/ci.yml`), валідатор docs↔код для `docs/05` (`specs/_validator.py:569+`), покриття 80.50% ≥ 80 | ціль 90%; машинна перевірка інших `docs/` |

---

## 3. Фаза 1: Швидкі перемоги (Quick Wins, 1–4 тижні)

*Фокус: максимальний приріст якості за мінімальних трудовитрат без зламу архітектури.*

### 3.1. Cost-Aware Selection Function у Walk-Forward
- **Стан: ✅ виконано.** `application/score.py:22-59` уже віднімає `turnover_haircut * metrics.turnover`
  (типово 5 б.п. обороту) і вміє ранжувати за `pnl`/`sharpe`/`calmar` (`SELECTION_METRIC`).
  Важливо: наведений нижче фрагмент плану **не можна** реалізовувати — `ending_balance` уже
  містить сплачені комісії, тож віднімання `fees_paid` вдруге штрафувало б їх двічі
  (розбір — `docs/22` §2.1, тест `tests/unit/test_factor_research.py::test_in_sample_score_does_not_double_count_fees`).
- **Файл:** [`src/nautilus_lab/application/score.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/application/score.py)
- **Проблема (станом на написання плану):** функція ранжувала конфігурації виключно за кінцевим капіталом:
  ```python
  def in_sample_score(result: BacktestResult) -> Decimal:
      return result.ending_balance
  ```
- **Рішення:** Впровадити штраф за надлишковий оборот і транзакційні витрати:
  ```python
  def in_sample_score(result: BacktestResult, turnover_penalty: Decimal = Decimal("2.0")) -> Decimal:
      net_pnl = result.ending_balance - result.starting_balance
      penalized_pnl = net_pnl - (turnover_penalty * result.fees_paid)
      return penalized_pnl
  ```
- **Результат:** Відсікання конфігурацій-«скальперів», які на папері генерують дохід, але повністю з'їдаються комісіями біржі.

### 3.2. Активація фракційного Келлі в розрахунку розміру позицій
- **Стан: ✅ виконано як код (opt-in), виміру на OOS немає.** `TradeStats` накопичується в
  `signal_strategy.py:171,303` і передається як `stats=` у `resolve_risk_fraction()`
  (`signal_strategy.py:407-410`); те саме на спредовому шляху — `spread_strategy.py:103,158-161`.
  Керується `USE_FRACTIONAL_KELLY` і `KELLY_MIN_TRADES` (`.env.example:75-76`), типово **вимкнено**,
  тому задокументовані прогони не змінилися. Чи дає це щось на OOS — відкрите питання
  (`docs/22` §7, спринт S5).
- **Файл:** [`src/nautilus_lab/application/risk.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/application/risk.py)
- **Проблема (так було на момент написання плану; вище — що зроблено насправді):** Метод `fractional_kelly_cap()` у `domain/portfolio_risk.py` вже реалізований, проте `evaluate_entry()` викликає його без фактичної статистики угод (win_rate та payoff_ratio не передаються, залишаючись no-op).
- **Рішення:** 
  1. Накопичувати в стані ризик-менеджера вікно останніх $N$ закритих угод (`RollingTradesWindow`).
  2. Передавати емпіричний вінрейт і середнє співвідношення виграшу до програшу в `effective_risk_fraction()`.
- **Результат:** Динамічне зменшення розміру позиції в періоди серії збитків і збільшення при стабільному тренді.

### 3.3. Підключення GJR-GARCH поряд з EGARCH
- **Стан: ✅ виконано.** `infrastructure/egarch_forecast.py:12,17` містить і `egarch_forecast_volatility()`,
  і `gjr_garch_forecast_volatility()`; вибір моделі — `VolModel` (`domain/volatility.py:9-21`),
  `ArchVolForecaster` із каденцією рефіту (`infrastructure/vol_forecast.py:117-121`), налаштування
  `VOL_MODEL=har|egarch|gjr_garch` і `VOL_REFIT_EVERY` (`settings.py:66-67`, `.env.example:65-74`).
  Типово `har` — щоб уже задокументовані прогони не змінилися; без extra `research` моделі
  повертають `None`, а не ламають прогін.
- **Файл:** [`src/nautilus_lab/infrastructure/egarch_forecast.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/infrastructure/egarch_forecast.py)
- **Проблема (обґрунтування плану):** Пакет `arch` підтримує асиметричний GJR-GARCH, який точніше моделює різкі спади ліквідності у криптовалюті порівняно зі звичайним GARCH.
- **Рішення:** Додати функцію `gjr_garch_forecast()` та конфігураційний параметр `VOL_MODEL=egarch|gjr_garch`.
  (Реалізовано як `gjr_garch_forecast_volatility()`, а `VOL_MODEL` має ще третє значення `har`.)

### 3.4. Real-Time сповіщення при спрацюванні Circuit Breakers
- **Стан: ❌ не виконано.** Є підрахунок відмов (`RiskBreachTally`, `application/risk.py:50-80`) і
  рядок-підсумок після прогону (`cli.py:964,1227,1263`), але сповіщення, як і раніше, надсилаються
  **лише після** завершення прогону (`cli.py:646-857`, `api/research_runner.py:285-462`).
  Подієвого алерта в момент спрацювання денного ліміту / max drawdown / VaR у коді немає.
- **Файли:** [`src/nautilus_lab/application/risk.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/application/risk.py), [`src/nautilus_lab/infrastructure/alerts.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/infrastructure/alerts.py)
- **Рішення:** Викликати `AlertNotifier` у момент активації аварійного зупинення (денний ліміт збитку, VaR shock, max drawdown hit), а не лише наприкінці прогону.

### 3.5. Емпіричні квантилі для Z-score у Pairs Trading
- **Стан: ✅ виконано (opt-in).** `domain/quantiles.py` (інтерпольований квантиль, тип-7, чистий `Decimal`),
  гілка `_entry_thresholds()` у `domain/pairs/pairs_trading.py:107-131`, параметр
  `PairsParams.z_entry_quantile`, `PAIRS_Z_ENTRY_QUANTILE` (`.env.example:102-108`). Типово `0`, тобто
  поведінка лишається фіксованою `z_entry` — саме такою, за якої мірявся `docs/05` §4.
- **Файл:** [`src/nautilus_lab/domain/pairs/pairs_trading.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/domain/pairs/pairs_trading.py)
- **Рішення:** Замість фіксованих порогів входу (1.5 / 2.0 / 2.5), які спираються на припущення про нормальний розподіл, використовувати емпіричні квантилі $q_{0.025}$ та $q_{0.975}$ вікна спреду з урахуванням важких хвостів (fat tails).

---

## 4. Фаза 2: Нові роботи та підключення модулів (1–3 місяці)

*Фокус: монетизація неефективностей, не пов'язаних з класичним технічним аналізом 1-годинних свічок.*

### 4.1. Повна інтеграція робота Funding Cash-and-Carry
- **Файли:** [`domain/funding.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/domain/funding.py), [`infrastructure/binance_funding.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/infrastructure/binance_funding.py), `infrastructure/nautilus/spread_strategy.py`
- **Суть стратегії:** Одночасне утримання лонгу на споті та шорту на перпетуалі для безризикового отримання ставки фінансування (Funding Rate), коли ставка є аномально високою.
- **Архітектурні кроки:**
  1. ✅ **Виконано.** Завантаження історичних ставок фандингу Binance (`/fapi/v1/fundingRate`) у Parquet-каталог:
     пагінований `infrastructure/binance_funding.py`, `infrastructure/funding_catalog.py`
     (`catalog/data/funding/<SYMBOL>/funding.parquet`), `application/ingest_funding_history.py`,
     команда `lab ingest --funding`. `index_price` тепер із `fapi/v1/indexPriceKlines`, а не
     підміняється `markPrice` (виміри й дефект D1 — `docs/23` §3, §6).
  2. ❌ **Не виконано.** Додавання P&L оверлею для нарахування фандингу кожні 8 годин у Nautilus Backtest рушії:
     `backtest_runner._execute()` додає лише бари (`bar_execution=True`), нарахування фандингу на
     утримувану перпетуал-позицію немає ніде в `src/`.
  3. ❌ **Не виконано.** Включення `RobotName.FUNDING` у `BACKTEST_WIRED_ROBOTS`: робота там немає
     (`domain/regime.py:35-45`), `lab research --robot funding` падає fail closed із кодом 1
     (перевірено).
  4. 🟡 **Виконано частково.** Специфікація `specs/strategies/funding.yaml` **є** (v1.1), але зі
     `wired_in_backtest: false` і `status: blocked`, а не `true`: адаптера немає, тож
     `true` тут було б неправдою. Розрив «даних» у ній позначено закритим, лишились адаптер і
     нарахування фандингу.

### 4.2. Динамічний розрахунок $\beta$ через фільтр Калмана (Pairs Trading)
- **Стан: ❌ не виконано.** `grep -rn -i kalman src/` порожній: β перераховується OLS-рефітом
  (`PAIRS_REFIT_EVERY`, `domain/pairs/pairs_trading.py::_maybe_refit`), рекурсивного оновлення стану немає.
- **Файл:** [`src/nautilus_lab/domain/pairs/pairs_trading.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/domain/pairs/pairs_trading.py)
- **Суть:** Зараз коефіцієнт хеджування $\beta$ перераховується через OLS-регресію з вікном `PAIRS_REFIT_EVERY`. Це створює східчасту зміну параметрів та хибні сигнали на межах перерахунку.
- **Рішення:** Реалізувати фільтр Калмана для безперервного рекурсивного оновлення станів:
  $$\beta_t = \beta_{t-1} + w_t, \quad w_t \sim \mathcal{N}(0, W)$$
  $$y_t = \beta_t x_t + v_t, \quad v_t \sim \mathcal{N}(0, V)$$
- **Ефект:** Миттєва адаптація до зміни співвідношення цін ETH та BTC без запізнення ковзного вікна.

### 4.3. Тест Йогансена для кошиків з трьох і більше активів
- **Стан: ❌ не виконано.** Файла `src/nautilus_lab/domain/pairs/johansen.py` не існує
  (`grep -rn -i johansen src/` порожній); у `domain/pairs/` є `cointegration.py` (ADF),
  `ou.py`, `pairs_trading.py`, `params.py`. Ingest додаткових символів, утім, уже відбувся
  де-факто: у каталозі є серії `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT`,
  `ADAUSDT`, `DOGEUSDT` (`catalog/data/bar/`), тож друга половина кроку закрита.
- **Файл:** `src/nautilus_lab/domain/pairs/johansen.py` (новий)
- **Суть:** Двокроковий метод Енгла-Грейнджера обмежений лише парою активів. Тест Йогансена дозволяє знаходити коінтегровані вектори для портфелів (наприклад, ETH - BTC - SOL).
- **Кроки:** Додати підтримку додаткових символів у `lab ingest` та розрахунок матриці власних значень у доменному шарі.

### 4.4. ML Pipeline: Order Book Imbalance (OBI) + LightGBM
- **Стан: ✅ код і дані готові, виміру немає.** Робот `ml_obi` **у** `BACKTEST_WIRED_ROBOTS`
  (`domain/regime.py:35-45`) і в paper-наборі; навчання — `lab ml train --model-type obi`
  (`application/train_obi.py`, `application/train_classifier.py`, `domain/triple_barrier.py`,
  purged K-fold); знімки книги пишуться `lab ingest --depth` через
  `infrastructure/binance_orderbook.py` і `orderbook_catalog.py`. Лишається вимір:
  `specs/strategies/ml_obi.yaml` → `evidence.measured: false` (у каталозі — 1 доба ETHUSDT).
- **Файли:** `application/train_classifier.py`, `domain/ml_obi_strategy.py`
- **Суть:** Використання мікроструктурного дисбалансу стакану (OBI) для короткострокового передбачення напрямку руху ціни.
- **Кроки:**
  1. Збір датасету снепшотів глибини ринку через Binance REST API. (Реалізовано через публічний **WebSocket** `@depth20@100ms`, а не REST-полінг.)
  2. Розмітка барів через Triple Barrier Method (TBM).
  3. Purged K-Fold валідація та тренування градієнтного бустингу.
  4. Експорт ваг моделі та запуск робота `ml_obi` у бектесті.

### 4.5. Ансамблевий роутер сигналів (Ensemble Voting)
- **Стан: ❌ не виконано.** Файла `src/nautilus_lab/domain/ensemble_router.py` не існує, і
  жодного зваженого голосування кількох роботів у коді немає. `domain/regime_router.py` —
  інше: він перемикає підстратегії **всередині** одного робота за режимом ринку.
- **Файл:** `src/nautilus_lab/domain/ensemble_router.py` (новий)
- **Суть:** Об'єднання слабких некорельованих сигналів від різних роботів (`regime`, `vpin_momentum`, `funding`) за допомогою зваженого мажоритарного голосування:
  $$Signal = \operatorname{sign}\left(\sum_{i=1}^N w_i \cdot s_i\right)$$

---

## 5. Фаза 3: Дані, таймфрейми та мікроструктура (2–4 місяці)

*Фокус: розв'язання проблеми запізнення сигналів через перехід на нижчі таймфрейми та живі потоки даних.*

### 5.1. Перехід на менші таймфрейми (5m / 15m)
- **Стан: ❌ не виконано.** `infrastructure/timeframe.py` уже вміє `1m/5m/15m/1h/4h/1d`, але в
  каталозі лежать лише серії `-1-HOUR-` і `-1-DAY-` (`catalog/data/bar/`), а окремого прапорця
  інтервалу в `lab ingest` немає: інтервал береться з `BAR_INTERVAL`. Кілька інтервалів одночасно
  читаються через `CATALOG_PATHS` (`.env.example:46-47`) — один каталог на інтервал.
- **Поточний стан:** Всі симуляції налаштовані на `BAR_INTERVAL=1h` (типове значення `settings.py`, `.env.example:48`).
- **Кроки реалізації:**
  1. Завантаження історичних даних (інтервал задається змінною, а не прапорцем):
     ```bash
     BAR_INTERVAL=5m uv run lab ingest --start 2024-01-01 --symbols ETHUSDT,BTCUSDT --catalog catalog_5m
     ```
  2. Перерахунок конфігурацій `minimum_bars` у `run_research_backtest.py` з урахуванням зростання кількості барів у 12 разів.
  3. Калібрування розміру сіток `param_grid.py` для 5-хвилинного горизонту.
  4. Аудит комісій: на 5m кількість угод зростає експоненційно, тому перевірка breakeven-cost стає критичною.

### 5.2. Публічний WebSocket фід для режиму Paper Trading
- **Стан: ✅ виконано.** `infrastructure/binance_ws.py` (лише закриті бари: `k.x == false`
  відкидається, реконект із обмеженим експоненційним backoff, лише публічні дані),
  `infrastructure/live_bar_feed.py` (прогрів історією з каталогу + живі закриті бари),
  CLI: `lab paper --source live [--live-bars N] [--live-timeout S]`, журнал — `--journal`
  у `reports/paper/sessions.jsonl`. Живий контур є і в дашборді (`api/live_sessions.py`,
  `api/live_paper_boot.py`, `LIVE_PAPER_*` у `.env.example`).
- **Файл:** [`src/nautilus_lab/infrastructure/binance_ws.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/infrastructure/binance_ws.py)
- **Призначення:** Забезпечити режим `lab paper` живими ринковими котируваннями без залучення приватних API-ключів біржі:
  - Підключення до `wss://stream.binance.com:9443/ws/ethusdt@kline_1m`.
  - Автоматична підтримка з'єднання (Ping/Pong раз на 3 хвилини).
  - Накопичення тіків та агрегація в закриті бари обраного інтервалу.
  - Генерація та логування гіпотетичних ордерів у реальному часі.

### 5.3. Збір та збереження L2 стакану ордерів
- **Стан: ✅ виконано, технічно інакше, ніж планувалось.** Замість REST-полінгу
  `GET /api/v3/depth?limit=50` використано WebSocket-потік часткової книги
  `wss://stream.binance.com:9443/ws/<symbol>@depth20@100ms`
  (`infrastructure/binance_orderbook.py`), записи лягають у Parquet через
  `infrastructure/orderbook_catalog.py` (`catalog/data/orderbook/<SYMBOL>/<YYYY-MM-DD>.parquet`),
  команда — `lab ingest --depth` (працює, доки не перервуть). Обсяг поки що іграшковий:
  по одній добі на BTCUSDT і ETHUSDT, тому `ml_obi` лишається без виміру
  (`specs/strategies/ml_obi.yaml`).
- **Файл:** [`src/nautilus_lab/infrastructure/binance_orderbook.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/infrastructure/binance_orderbook.py)
- Регулярне опитування ендпоінту `GET /api/v3/depth?limit=50` та збереження снепшотів глибини у форматі Apache Parquet для мікроструктурних досліджень.

---

## 6. Фаза 4: Просунуті моделі та маркет-мейкінг (3–6 місяців)

*Фокус: перехід від спрямованої торгівлі (directional trading) до ліквідних та високочастотних стратегій.*

### 6.1. Маркет-мейкінг за моделлю Гере-Лекера-Фая-Тама (GLFT)
- **Стан: ❌ не виконано, і не може бути виміряним у поточному рушії.** Домен `domain/glft.py`
  існує, але споживача `QuoteIntent` немає (`grep -rn QuoteIntent src/` → лише `signals.py` і
  `glft.py`), а рушій виконує ордери як ринкові; `specs/strategies/glft.yaml` → `status: blocked`,
  `lab research --robot glft` падає з кодом 1.
- **Файл:** [`src/nautilus_lab/domain/glft.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/domain/glft.py)
- **Проблема:** Поточний бектестер Nautilus використовує спрощену модель виконання барів, яка не враховує чергу лімітних заявок у стакані.
- **Вимоги для запуску:**
  1. Реалізація ймовірнісної моделі заповнення лімітних ордерів на основі відстані до mid-price та обсягу торгів у барі:
     $$P(\text{fill}) = 1 - e^{-\kappa \delta t}$$
  2. Облік накопиченого інвентарю ($q$) та динамічне коригування асиметрії котирувань bid/ask для повернення позиції до нейтралі.

### 6.2. Багатовимірний процес Хоукса (Multivariate Hawkes)
- **Стан: 🟡 частково.** Двовимірне взаємне збудження вже є в домені:
  `domain/hawkes.py:52-53` додає `cross_alpha * sell_volume` у buy-інтенсивність і навпаки,
  тож математика з цього пункту реалізована. Але `cross_alpha` типово `Decimal("0.0")`, у
  `Settings` його немає (`grep -n HAWKES .env.example` → лише `HAWKES_BASELINE/ALPHA/BETA/TOXIC_THRESHOLD`),
  тобто в прогонах працює одновимірний випадок. Фільтр доступний як `--hawkes`
  (`HAWKES_ROBOTS` — `regime`, `meta_label`) і потребує серії aggTrades у каталозі.
- **Файл:** [`src/nautilus_lab/domain/hawkes.py`](file:///home/volodymyr/PycharmProjects/nautilus-lab/src/nautilus_lab/domain/hawkes.py)
- **Розвиток:** Перехід від одновимірного самозбуджуваного процесу до двовимірної системи взаємного збудження між агресивними покупками та продажами:
  $$\lambda_{\text{buy}}(t) = \mu_{\text{buy}} + \int_0^t \alpha_{bb} e^{-\beta_{bb}(t-s)} dN_b(s) + \int_0^t \alpha_{sb} e^{-\beta_{sb}(t-s)} dN_s(s)$$
- **Застосування:** Передбачення короткострокових каскадів ліквідацій та фільтрація помилкових імпульсів у роботі `vpin_momentum`.

### 6.3. DRL (Deep Reinforcement Learning) для динамічної алокації ваг
- **Позиція проєкту:** Ніякого DRL для безпосереднього виставлення ордерів на сирих цінах (високий ризик вивчення артефактів симулятора).
- **Допустиме використання:** Агент верхнього рівня (PPO/SAC) для динамічного перерозподілу капіталу між верифікованими низькокорельованими стратегіями на основі поточного макрорежиму ринку.

---

## 7. Фаза 5: Інженерна якість, CI/CD та DevOps (Постійно)

### 7.1. Підвищення покриття тестами (80% → 90%)
- **Стан: ❌ ціль 90% не досягнута; борг «нижче 80» закрито.** Виміряно зараз:
  `.venv/bin/python -m pytest --cov` → **80.50%** (було 76.7%), тобто `fail_under = 80`
  проходить; 825 тестів, 0 падінь. Адаптери далі виключені з покриття
  (`pyproject.toml:144-148`).
- Написання тестів на інтеграційні Nautilus-адаптери (`infrastructure/nautilus/backtest_runner.py`, `signal_strategy.py`), які зараз виключені з розрахунку покриття у `pyproject.toml`.
- Тестування крайових випадків поведінки під час відсутності даних у каталозі.

### 7.2. Автоматична верифікація синхронізації документації з кодом
- **Стан: ✅ виконано для `docs/05`.** `specs/_validator.py:569+` (`check_docs_alignment`)
  парсить таблицю роботів у `docs/05-roboty.md` і падає, якщо вона розходиться з
  `BACKTEST_WIRED_ROBOTS` і `RobotName`. Решта документів у `docs/` (зокрема цей роудмап
  і `docs/22`) машинно **не** перевіряється — саме тому статуси тут доводиться звіряти вручну.
- Розширення скрипта `specs/_validator.py` можливістю парсингу Markdown-таблиць у папці `docs/` та їх автоматичного звіряння з константами в коді (наприклад, перевірка збігу списку роботів між `docs/05-roboty.md` та `BACKTEST_WIRED_ROBOTS`).

### 7.3. Автоматичний аудит та CI/CD
- **Стан: ✅ виконано.** `.github/workflows/ci.yml` запускається на push/PR і виконує
  `ruff check`, `ruff format --check`, `mypy src tests`, `specs/_validator.py`, `pytest`,
  smoke-бектест `lab research --synthetic --bars 3000` і виконання зошита
  (`scripts/check_notebook.py`). Єдиний необлокувальний крок — `pytest --cov`
  (`continue-on-error`), і станом на зараз він проходить (80.50% ≥ 80).
- Налаштування GitHub Actions для автоматичного прогону перевірок на кожен Pull Request:
  ```bash
  uv run ruff check --fix
  uv run ruff format --check
  uv run mypy src tests
  .venv/bin/python specs/_validator.py
  uv run pytest --cov --cov-report=term-missing
  uv run lab research --synthetic --bars 3000   # smoke backtest
  ```

---

## 8. Пріоритизована матриця завдань

| # | Завдання / Ініціатива | Фаза | Очікуваний ефект (Impact) | Складність реалізації | Залежності та передумови | Стан у коді (звірено) |
|:---:|---|:---:|:---:|:---:|---|---|
| **1** | **Cost-Aware Score Function** у Walk-Forward | 1 | 🔥 **Критичний** | 🟢 Дуже низька (~15 рядків) | Немає, готова до реалізації | ✅ `application/score.py:22-59` |
| **2** | **Активація фракційного Келлі** в `risk.py` | 1 | 🔥 **Критичний** | 🟢 Низька (~40 рядків) | Наявність `domain/portfolio_risk.py` | ✅ код (opt-in, `USE_FRACTIONAL_KELLY`); ⏳ вимір на OOS |
| **3** | **Підключення Funding робота** до бектесту | 2 | 🔥 **Критичний** | 🟠 Середня | Завантаження funding rates | ⏳ дані й спека є (`lab ingest --funding`); адаптера немає |
| **4** | **Фільтр Калмана** для динамічного $\beta$ (Pairs) | 2 | 🟢 **Високий** | 🟠 Середня | Математичний модуль у домені | ⏳ не почато |
| **5** | **Перехід на 5m / 15m таймфрейми** | 3 | 🟢 **Високий** | 🟠 Середня | Ingest 5m каталогу, оптимізація RAM | ⏳ не почато; `timeframe.py` інтервали вже знає |
| **6** | **Емпіричні квантилі z-score** (Pairs) | 1 | 🟡 **Середній** | 🟢 Низька (~25 рядків) | Доопрацювання `PairsTrading.on_bar` | ✅ `domain/quantiles.py`, `PAIRS_Z_ENTRY_QUANTILE` |
| **7** | **GJR-GARCH поряд з EGARCH** | 1 | 🟡 **Середній** | 🟢 Дуже низька (~20 рядків) | Пакет `arch` | ✅ `infrastructure/egarch_forecast.py:17`, `VOL_MODEL` |
| **8** | **Circuit Breaker real-time alerts** | 1 | 🟡 **Середній** | 🟢 Низька (~30 рядків) | Модуль `alerts.py` | ⏳ не почато (є лише підрахунок після прогону) |
| **9** | **ML Pipeline (OBI + LightGBM)** | 2 | 🟢 **Високий** | 🔴 Висока | Збір L2 даних стакану | ✅ код і фід книги; ⏳ виміру немає (`evidence.measured: false`) |
| **10** | **Ансамблевий роутер голосування** | 2 | 🟢 **Високий** | 🟠 Середня | Мінімум 2 прибуткові роботи | ⏳ не почато |
| **11** | **Публічний WebSocket для Paper Mode** | 3 | 🟡 **Середній** | 🔴 Висока | Asyncio WS клієнт Binance | ✅ `infrastructure/binance_ws.py`, `lab paper --source live` |
| **12** | **GLFT маркет-мейкінг з моделлю черги** | 4 | 🟢 **Високий** | 🔴 Найвища | Реалістична симуляція виконання | ⏳ не почато (`specs/strategies/glft.yaml` → `blocked`) |
| **13** | **Multivariate Hawkes процес** | 4 | 🟡 **Середній** | 🟠 Середня | Доменна реалізація матриці ядра | 🟡 `cross_alpha` є в домені, але не виведений у `Settings` |
| **14** | **Johansen коінтеграція для 3+ активів** | 2 | 🟡 **Середній** | 🟠 Середня | Ingest додаткових пар (SOL, BNB) | ⏳ не почато (символи в каталозі вже є) |
| **15** | **Синхронізація документації з кодом** | 5 | 🟡 **Середній** | 🟢 Низька | Розширення `specs/_validator.py` | ✅ `specs/_validator.py::check_docs_alignment` (лише `docs/05`) |
| **16** | **GitHub Actions CI/CD пайплайн** | 5 | 🟡 **Середній** | 🟢 Низька | Конфігурація `.github/workflows` | ✅ `.github/workflows/ci.yml` |
| **17** | **DRL алокатор портфеля** | 4 | ⚪ **Низький зараз** | 🔴 Найвища | Наявність перевірених альф | ⏳ не почато (і заборонено §9.2 у формі «на сирих барах») |

---

## 9. Антипатерни та зони заборони (Що НЕ робити)

> [!WARNING]
> Нижченаведені дії створюють ілюзію прогресу, але статистично ведуть до перенавчання або порушення ключових гарантій надійності лабораторії:

1. **Заборона спроб реалізувати Live Trading адаптер:**
   - Режим `lab live` **повинен залишатися fail-closed**. Поки жоден робот не довів стійкої переваги на реальному OOS, вихід у реальний ринок є категорично неприпустимим.
2. **Заборона застосування DRL для прогнозу цін на свічках:**
   - Нейромережеві агенти підкріплення на сирих барах без змодельованого стакану вивчають локальний шум та артефакти симулятора, генеруючи катастрофічні збитки на нових даних.
3. **Заборона збільшення кількості ітерацій Optuna без подовження OOS:**
   - Збільшення кількості trials з 30 до 200 на незмінному розмірі вибірки лише гарантовано збільшує ймовірність перенавчання (PBO) та знижує Deflated Sharpe Ratio.
4. **Заборона реанімації робота `adaptive_ema`:**
   - Гіпотеза динамічного згладжування Кауфмана вже офіційно відхилена прямим науковим виміром (`docs/18 §3`). Подальші спроби тюнінгу її параметрів — це марнування обчислювальних ресурсів. Проте сам робот залишається в `BACKTEST_WIRED_ROBOTS` зі статусом `rejected` для відтворюваності негативного результату згідно з культурою чесного research (див. `AGENTS.md` §4).
5. **Заборона виклику LLM усередині бектесту:**
   - Моделі штучного інтелекту мають працювати виключно в **офлайн-контурі гіпотез** (`lab propose`). Виклик LLM API під час циклу симуляції барів — грубий архітектурний баг.

---

## 10. Критерії приймання та валідації (Definition of Done)

Стратегія **НЕ може** отримати статус `validated` у специфікаціях `specs/strategies/<robot>.yaml` без проходження повного аудиторського чекліста:

```
                  Вхід нової ідеї (Гіпотеза / Специфікація)
                                     │
                                     ▼
                ┌────────────────────────────────────────┐
                │  Walk-Forward Бектест (Folds ≥ 4, OOS) │
                └────────────────────┬───────────────────┘
                                     │
                     OOS Mean Return > Buy & Hold Mean?
                                     │
                        ┌────────────┴────────────┐
                        │ ТАК                     │ НІ
                        ▼                         ▼
            ┌──────────────────────┐      ┌────────────────────────┐
            │ Аудит перенавчання   │      │ СТАТУС: REJECTED       │
            │  PBO < 0.25 & DSR p<0.05    │ (Запис причини в specs)│
            └───────────┬──────────┘      └────────────────────────┘
                        │
                  Критерій виконано?
                        │
            ┌───────────┴───────────┐
            │ ТАК                   │ НІ
            ▼                       ▼
┌────────────────────────┐  ┌────────────────────────┐
│ Breakeven-cost > Fees  │  │ СТАТУС: CANDIDATE      │
│     на 3-х стрес-слайсах│  │ (Потребує доопрацювання│
└───────────┬────────────┘  └────────────────────────┘
            │
            ▼ ТАК
┌────────────────────────────────────────┐
│           СТАТУС: VALIDATED            │
│  (Офіційно доведена торгова перевага)  │
└────────────────────────────────────────┘
```

### Чекліст валідації:
1. **Walk-Forward:** Мінімум 4 послідовні ковзні фолди з буфером-ембарго.
2. **Перевага над Buy & Hold:** Середня OOS прибутковість ($\text{Mean Return}_{\text{OOS}}$) вища за середню прибутковість пасивного утримання на тому ж часовому інтервалі.
3. **Ймовірність перенавчання (PBO):** Значення PBO розраховане через CSCV складає $< 0.25$.
4. **Дефльований коефіцієнт Шарпа (DSR):** Значення $p$-value для DSR $< 0.05$ (з урахуванням загальної кількості протестованих конфігурацій сітки).
5. **Стійкість до витрат (Breakeven Cost):** Поріг беззбитковості стратегії $\text{breakeven\_cost\_bps} > \text{paid\_cost\_bps} + 5.0\text{ bps}$.
6. **Стрес-тести:** Жодного маржин-колу або спрацювання максимального стоп-ауту капіталу на кризових слайсах `covid2020` та `ftx2022`.

---

## 11. Інженерний фундамент: E/R-серія (додано 2026-09-24)

Фази 1–5 вище описують, **які** роботи й моделі будувати. Аудит відповідності
практикам 2026 року ([27-audyt-praktyk-2026-ta-roadmap-E.md](27-audyt-praktyk-2026-ta-roadmap-E.md))
показав, що вузьке місце зараз — периметр: деплой, спостережуваність,
відтворюваність і фронтенд. Тому перед новими роботами Фази 2+ виконуються хвилі:

| Хвиля | Терміни | Суть | Ключові задачі |
|---|---|---|---|
| 0 — стабілізація | 28.09 – 04.10.2026 | закомітити й повністю прогнати поточну роботу, закрити дірки деплою | E-0.1 коміт + повна перевірка, E-0.2 `LAB_UID` у compose, E-0.3 обов'язковий замок на публічному домені, E-0.4 TS `strict` |
| 1 — довіра до paper | 05.10 – 25.10.2026 | зробити 8-тижневий paper-прогін перевірним | E-1.4 `RunManifest` (git SHA, lock, дані, налаштування), E-1.5/1.6 health + метрики + алерти, E-1.7 бекапи, E-1.1–1.3 CI фронтенду/Docker/ланцюга постачання, E-1.9 покриття з адаптерами |
| 2 — підтримуваність | 26.10 – 29.11.2026 | розібрати моноліти, прибрати ручний дрейф | E-2.1/2.2 роутери + `JobManager`, E-2.3 типи з OpenAPI, E-2.4 тести фронтенду, E-2.6 золотий бектест, E-2.8 одна згенерована таблиця стану |
| 3 — дослідження | 12.2026 – 01.2027 | нові виміри лише на перевірному фундаменті | R-1 паритет бектест↔paper, R-2 попередня реєстрація, R-3 глобальний облік спроб для DSR, R-4 vol-matched B&H, §4.1 funding (спершу перевірити нативну підтримку Nautilus), S5 Келлі |
| 4 — розширення | I кв. 2027 | за результатами хвилі 3 | R-5 рішення по paper-сесіях, R-6 емпіричні витрати, далі матриця §8 (#5, #4, #10, #14) |

Нове правило до §9: **жоден новий робот і жоден новий OOS-вимір не стартують до
E-1.4 (маніфест прогону)** — результат без маніфесту неможливо переперевірити.
Розбіжність порогів §10 і `application/promotion_gate.py` розв'язується в E-2.8:
джерело правди — код, ця таблиця — його відображення.
