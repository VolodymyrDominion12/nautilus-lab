# 11. Проблеми, помилки, часті питання

Спочатку — швидкий діагностичний набір:

```bash
uv run python -c "
from nautilus_lab.infrastructure.settings import Settings
s = Settings()
print('mode:', s.trading_mode, '| robot:', s.robot, '| interval:', s.bar_interval)
print('catalog:', s.catalog_path, '| instrument:', s.instrument_id)
print('fees maker/taker:', s.fee_schedule().maker, s.fee_schedule().taker)
print('risk/stop:', s.risk_limits().risk_per_trade, s.risk_limits().stop_pct)
print('embargo:', s.embargo_bars)
"
```

Якщо тут щось не так, як ви очікували — проблема в налаштуваннях, а не в коді.

---

## Помилки

### `bar timestamps must be strictly increasing`

Причина: у каталозі **дублікати барів** з однаковими мітками часу — тобто два parquet-файли
покривають ті самі години. Так бувало, коли `lab ingest` запускали двічі в один каталог із вікнами,
що перекриваються: кожен запуск створював **новий** файл, і завантажувач бачив обидва.

**Це вже виправлено.** `write()` більше не дописує з `skip_disjoint_check=True`: спершу він
викликає `delete_data_range` для свого діапазону (ідемпотентна заміна), а `load()` дедуплікує за
`ts_utc` і сортує. Тому повторний ingest із перекриттям більше не створює дублікатів, а каталог,
у якому файли-дублікати вже лежать, усе одно завантажиться — `load()` їх прибере. Якщо ви бачите
цю помилку, у вас код, старіший за виправлення. Лікування — або **оновитися** (новий `load()`
дедуплікує такий каталог), або **перезалити** дані: повторити `ingest` на тому вікні, яке
перекривалося (запис замінить свій діапазон), чи почати з чистої теки.

Діагностика (чи є дублікати зараз):

```bash
.venv/bin/python - <<'PY'
from collections import Counter
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog("catalog")
bars = catalog.bars(bar_types=["ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"])
counts = Counter(b.ts_event for b in bars)
print("bars:", len(bars), "unique:", len(counts),
      "duplicates:", sum(v - 1 for v in counts.values() if v > 1))
PY
```

Якщо `duplicates > 0` — каталог зібраний старим кодом, і найпростіше перезалити його:

```bash
rm -rf catalog
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
```

Або, якщо шкода видаляти: досліджуйте в іншій теці.

```bash
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT --catalog catalog_fresh
uv run lab research --catalog catalog_fresh
```

**Профілактика:** правило «один каталог = один ingest» більше не обов'язкове, але окрема тека на
кожне вікно (`--catalog`) лишається найпростішим способом тримати каталог передбачуваним.
Після кожного ingest запускайте перевірку з [04 §Крок 2](04-tsykl-doslidzhennya.md#крок-2-sanity-check--перевірка-цілісності-даних).

---

### `no bars in catalog ... Run 'lab ingest' first.`

```
CatalogEmptyError: no bars in catalog /.../catalog for ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL. Run `lab ingest` first.
```

Причини за частотою:

1. Каталог порожній (не робили `ingest`).
2. `--catalog` вказує не туди (відносний шлях рахується від робочої теки).
3. `--slice` або явні дати — поза межами завантаженої історії (типово: каталог на 2025 рік,
   а слайс `ftx2022`).
4. Інший `BAR_INTERVAL`: дані завантажені як `1h`, а `.env` тепер каже `5m`.
5. Інший `INSTRUMENT_ID` — серії з таким `bar_type` у каталозі немає.

Перевірити, що взагалі лежить у каталозі:

```bash
find catalog/data/bar -maxdepth 1 -type d
```

---

### `bar_count must be >= 150 so indicators can warm up`

Мінімум барів залежить від робота:

| Робот | Мінімум на фолд |
|-------|------------------|
| `regime` | 150 |
| `pairs` | 200 |
| `ema` та решта | 50 |

У walk-forward це стосується **кожного** фолда окремо: якщо на OOS припало 120 барів — буде ця помилка,
навіть якщо всього барів 5000. Лікування: довша історія, більший `--is-fraction` для OOS,
або коротший `--is-fraction` для IS.

---

### `walk-forward dates require --is-start --is-end --oos-start --oos-end`

Walk-forward з явними вікнами вимагає **всі чотири** дати. Задайте всі — або жодної
(тоді використається `--is-fraction`).

---

### `in-sample must not overlap out-of-sample`

`--is-end` пізніший за `--oos-start`. Вікна не можуть перетинатися (розрив між ними — можна й рекомендовано).

---

### `unknown stress slice 'xxx'; use one of: covid2020, ftx2022, etf2024`

Друкарська помилка або слайс, якого немає. Доступні три: `covid2020`, `ftx2022`, `etf2024`.

---

### `unsupported instrument_id: XXX`

Список інструментів симуляції жорстко заданий у `infrastructure/nautilus/instrument.py`:

| `instrument_id` | Тип | Крок ціни | Крок кількості |
|------------------|-----|-----------|----------------|
| `ETH/USDT.SIM` | спот | 0.01 | 0.001 |
| `BTC/USDT.SIM` | спот | 0.01 | 0.00001 |
| `ETHUSDT-PERP.SIM` | перпетуал | 0.01 | 0.001 |

Щоб додати свій, треба:
1. `infrastructure/nautilus/instrument.py` — запис у `_SPOT_SPECS` (або `_PERP_SPECS`);
2. `.env` — `INSTRUMENT_ID` і `BINANCE_SYMBOL`;
3. `lab ingest` (новий каталог).

Підтримуються лише символи, що закінчуються на `USDT` (`binance_symbol_to_instrument_id`).

---

### `unsupported bar interval 'xx'; use one of: 1m, 5m, 15m, 1h, 4h, 1d`

`BAR_INTERVAL` поза набором. Пам'ятайте: зміна інтервалу вимагає **нового ingest**
(у каталозі серії `-1-HOUR-` і `-5-MINUTE-` — це різні набори даних).

---

### `uv run` падає з `Permission denied` на кеш uv

```
error: failed to open file `/home/.../.cache/uv/sdists-v9/.git`: Permission denied (os error 13)
```

Це обмеження середовища (немає доступу до кеша `uv`), а не помилка проєкту.
Запускайте команди напряму з віртуального середовища:

```bash
.venv/bin/lab research --synthetic --bars 3000
.venv/bin/pytest -q
.venv/bin/python -c "import nautilus_lab; print('ok')"
```

Для нової інсталяції залежностей тоді знадобиться доступ до кеша — інакше `uv sync` не спрацює.

---

### `lightgbm extra not installed; use HeuristicDirectionClassifier`

`LightGBMDirectionClassifier` доступний лише після:

```bash
uv sync --extra dev --extra ml
```

Для досліджень використовуйте `HeuristicDirectionClassifier` (rule-based) — він не потребує нічого.

---

### EGARCH повертає `None` або `ConvergenceWarning`

- `None` — не встановлено пакет `arch` (`uv sync --extra research`) або менше 60 точок.
- `ConvergenceWarning: The optimizer returned code 4` — оптимізатор не зійшовся
  (типово на синтетичних/коротких рядах). Значення все одно повертається; для серйозних
  висновків краще довша історія з реальною кластеризацією волатильності.

---

### `optuna is not installed; run: uv sync --extra research`

Прапорець `--optuna` потребує пакета `optuna`:

```bash
uv sync --extra dev --extra research
```

Перевірка: `uv run python -c "import optuna; print(optuna.__version__)"`.

---

### Тиршит не створюється (`--tearsheet`), але прогін завершується успішно

Дві можливі причини, обидві видно в логі як попередження:

| Повідомлення | Причина | Лікування |
|--------------|---------|-----------|
| `Cannot generate tearsheet: plotly is missing.` | Не встановлено extra `visualization` | `uv sync --extra dev --extra visualization` |
| `Failed to generate tearsheet: <деталі>` | Помилка всередині Nautilus (наприклад, немає даних для графіків) | Подивіться деталі; тиршит не є критичним для дослідження |

Генерація тиршита **ніколи не ламає прогін**: помилка ловиться, `tearsheet_path` у звіті лишається `None`,
і рядок `tearsheet_saved=` не друкується. Також пам'ятайте: файл важкий (реальний приклад — 4.3 МБ),
і `.gitignore` уже містить `reports/` та `*.html`.

---

### `--notify` не надсилає повідомлення (і команда все одно завершується з кодом 0)

Перевірте:

1. Змінні задані саме там, де їх бачить процес: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
   (потрібні **обидві**) або `ALERT_WEBHOOK_URL`.
2. Встановлено extra `alerts` (пакет `httpx`).
3. У лозі немає рядка на кшталт `Telegram notification failed with HTTP 404`.
   Реальний випадок із неправильним токеном:

```
Telegram notification failed with HTTP 404: {"ok":false,"error_code":404,"description":"Not Found"}
```

Це очікувана поведінка: **збій сповіщення не є помилкою дослідження**, тому код виходу лишається `0`.
Якщо потрібно, щоб відсутність сповіщення «валила» процес, перевіряйте це у своєму скрипті-обгортці.

---

### `Pandas4Warning: Timestamp.utcnow is deprecated` під час тестів

Це попередження зсередини NautilusTrader (`nautilus_trader/backtest/engine.pyx`), не з нашого коду:
Nautilus оголошує `pandas>=2.3.3`, але досі використовує API до pandas 3.0.

Воно **вже заглушене** точковим фільтром у `pyproject.toml` → `[tool.pytest.ini_options] → filterwarnings`,
разом із коментарем, чому саме це повідомлення. Фільтр навмисно вузький (одне конкретне повідомлення
з `DeprecationWarning`), щоб попередження **з нашого** коду лишалися видимими. Якщо воно знову
з'явиться — значить, змінився текст повідомлення в Nautilus; оновіть фільтр, а не вимикайте
попередження глобально.

---

### `multi-window walk-forward needs folds >= 2`

`--folds` приймає `0`, `1` або від'ємне значення. Багатовіконний режим вмикається з `--folds N`, де
`N >= 2`; `--folds 1` — це звичайний єдиний спліт, а `--folds 0` і від'ємні значення відхиляються
CLI (код виходу 1), щоб запит не виконався «частково» з іншим змістом.

```bash
uv run lab research --robot regime --folds 4   # багатовіконний
uv run lab research --robot regime --folds 1   # звичайний єдиний спліт
uv run lab research --robot regime --folds 0   # помилка, код 1
```

---

### `multi-window runs derive their own windows; drop --is-start/--oos-start`

Ви передали явні дати (`--is-start`, `--is-end`, `--oos-start`, `--oos-end`) разом із `--folds N >= 2`.
Ці два способи задати вікна взаємовиключні: багатовіконний режим сам нарізає `N` ковзних фолдів,
і явне вікно зробило б його безглуздим. Приберіть дати — і за потреби керуйте розкладкою через
`--is-fraction` та `--embargo-bars`.

---

### `<N> bars cannot fill <F> folds at in_sample_fraction=...; use fewer folds...`

Серії барів не вистачає на замовлену кількість фолдів. Розкладка така:
`in_sample_bars = int(усього * in_sample_fraction)`, далі проміжок embargo, а решта ділиться на
`per_fold = (усього - in_sample_bars - embargo) // folds`. Якщо `per_fold` виходить `< 1` — помилка.

Що робити: зменшити `--folds`, зменшити `--is-fraction` (коротший in-sample лишає більше барів на
фолди) або завантажити більше історії через `lab ingest`. Наприклад, на 23 697 годинах і типовій
частці `0.7` чотири фолди дають близько 1 777 барів на фолд — із запасом.

---

### Тести падають на покритті (`fail_under = 80`)

У `pyproject.toml` задано мінімальне покриття 80%. Якщо ви додали код без тестів і запускаєте
`pytest --cov`, покриття впаде. Додайте тести — це не формальність: саме unit-тести
ловлять підглядання в майбутнє й помилки в індикаторах.

---

### `cmd | tail` показує код виходу 0, хоча команда впала

Код виходу в конвеєрі — це код останньої команди (`tail`). Щоб побачити справжній:

```bash
uv run lab research --slice ftx2022; echo "exit=$?"
# або
uv run lab research --slice ftx2022 >/dev/null 2>&1; echo "exit=$?"
```

Усі помилки CLI дають `1`.

---

## Дивна поведінка (не помилки)

### `robot 'funding' has no backtest adapter yet; use one of: ema, pairs, regime`

Так і задумано. `funding`, `ml_obi`, `glft`, `tri_scan` існують лише як доменні модулі
й не підключені до рушія бектесту, тому команда завершується помилкою (код виходу 1),
а не тихим запуском іншої стратегії.

Раніше ці імена **мовчки** запускали `regime` і давали звіт, який виглядав правдоподібно,
але стосувався зовсім іншого робота. Тепер це fail closed — безпечніше отримати помилку,
ніж неправдивий результат.

Щоб використати такий модуль:
- напряму з коду — приклади в [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md);
- або підключити його до рушія за інструкцією [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
  (перелік підключених роботів — `BACKTEST_WIRED_ROBOTS` у `domain/regime.py`).

Деталі — [05 §0](05-roboty.md#0-таблиця-стану-читати-першою).

### `--robot pairs` дає `fills=0`

Ворота коінтеграції тепер **справжні** (розбір баґу — [07 §5](07-yak-stvoryty-strategiyu.md#5-приклад-2-замінити-спрощений-adf-на-справжній)),
тому `fills=0` більше **не** означає «зламаний ADF». Реальних причин три:

| # | Причина | Поріг |
|---|---------|-------|
| 1 | Пара не проходить ворота коінтеграції: справжній ADF p-value **вищий** за поріг | `adf_pvalue_max` (типово `0.05`) |
| 2 | Підігнаний період напіврозпаду **довший** за поріг | `max_half_life_bars` (типово `240`) |
| 3 | Z-оцінка за весь прогін жодного разу не досягла порогу входу | `z_entry` (типово `2.0`) |

Перевірте, чи ворота взагалі можуть відкритися на вашому каталозі:

```bash
.venv/bin/python - <<'PY'
from decimal import Decimal
from pathlib import Path

from nautilus_lab.domain.pairs.cointegration import fit_cointegration
from nautilus_lab.domain.pairs.ou import fit_ou_half_life
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog

LOOKBACK = 120
store = NautilusParquetCatalog(Path("catalog"))
a = store.load(bar_type="ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL")
b = store.load(bar_type="BTC/USDT.SIM-1-HOUR-LAST-EXTERNAL")


def gate(start: int) -> tuple[Decimal, Decimal]:
    y = tuple(bar.close for bar in a[start : start + LOOKBACK])
    x = tuple(bar.close for bar in b[start : start + LOOKBACK])
    coint = fit_cointegration(y, x)
    spread = tuple(i - coint.intercept - coint.hedge_ratio * j for i, j in zip(y, x, strict=True))
    return coint.adf_pvalue, fit_ou_half_life(spread).half_life_bars


p, half_life = gate(0)
print(f"перше вікно: p={p} half-life={half_life}")

for start in range(len(a) - LOOKBACK + 1):
    p, half_life = gate(start)
    if p <= Decimal("0.05") and half_life <= Decimal("240"):
        print(f"ворота відкрилися на вікні, що закінчується баром {start + LOOKBACK - 1}")
        break
else:
    print("ворота не відкрилися жодного разу")
PY
```

Як читати вивід:

- `перше вікно ... ` — це ще **не** діагноз: робот пробує зсунуті вікна далі (див. нижче);
- `ворота відкрилися на вікні ...` — ворота працюють, і `fills=0` найімовірніше означає причину 3:
  `z_entry` не досягався. Робот коректно чекав — це не помилка;
- `ворота не відкрилися жодного разу` — причини 1 або 2: пара на цьому вікні справді
  некоінтегрована або повертається надто повільно. Це **не** баґ — ворота fail closed. Послаблювати
  `adf_pvalue_max` «щоб заторгувало» не можна: ви вимкнете саме ту перевірку, яка й робить
  пару-стратегію осмисленою.

> **Відоме обмеження.** Фіт коінтеграції робиться **не** один раз на фіксованому вікні: якщо ворота
> не відкрилися, робот пробує знову на наступному барі зі зсунутим на один бар вікном `lookback` —
> і так до першого успіху. Але після першого успішного фіту β, μ і σ **заморожуються назавжди**:
> коінтеграція більше ніколи не переоцінюється. Тому «пара була коінтегрована весь час» і «пара
> проходить ворота зараз» — різні твердження: якщо зв'язок зламався пізніше, робот цього не
> побачить. Деталі — [05 §3.4](05-roboty.md#34-ворота-якості-чому-робот-може-не-торгувати-взагалі).

### Синтетичний прогін дає +3251% прибутку

Це **артефакт синтетичних даних**, не перевага стратегії:

```
fills=132 positions=53 ending=3351101.12   # з 100 000
```

Синтетика — це random walk без реальної мікроструктури, з ідеальними трендами й без впливу
на ціну. Використовуйте її лише як smoke-тест («код не падає, сигнали генеруються»).
Результати — тільки з каталогу реальних даних.

### `lab paper` записує кілька `buy` підряд

Paper-режим не веде стан позиції: він лише логує сигнали. Три послідовні сигнали «купити»
дадуть три записи в лозі, хоча в реальності це була б одна позиція. Це спрощення, а не баг.

### `max_dd` дорівнює `MAX_DRAWDOWN` (0.06) майже завжди

Просадка впирається в запобіжник, який блокує нові входи. Це означає або занадто агресивний
ризик для цього ринку, або слабку стратегію. Див. [06 §8](06-ryzyk-metryky.md#8-як-читати-результат-очима-ризик-менеджера).

### `fees_paid` порівнянний з прибутком

Класика: стратегія з великим `turnover` платить біржі стільки ж, скільки заробляє.
Перевірте `turnover` і кількість `fills`. Для роботів, які торгують кожен бар (`ema`),
це очікувано — саме тому `ema` тут потрібен лише як baseline.

### Результат змінюється, коли я змінюю `.env`, але деякі змінні «не слухаються»

**Змінні середовища оболонки мають вищий пріоритет за `.env`.** Перевірте:

```bash
env | grep -iE "maker|taker|risk|robot|trading"
```

Якщо там щось є — саме воно переможе файл `.env`. Приберіть змінну (`unset TAKER_FEE`)
або запускайте в чистій оболонці. Наприклад, на цій машині в середовищі задані
`MAKER_FEE=0.0002` і `TAKER_FEE=0.0005`, тому в нотатці звіту видно саме їх, а не значення з `.env`.

---

## Часті питання

### Чи потрібні API-ключі Binance?

**Ні.** Усе, що проєкт завантажує (`/api/v3/klines`, `/fapi/v1/fundingRate`), — публічні ендпоінти.
Поля `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` існують, але код їх **не читає** —
живого адаптера виконання немає. Якщо у вашому `.env` лежать справжні ключі — видаліть їх
і перевипустіть на біржі: вони не потрібні для research і створюють зайвий ризик.

### Чи можна торгувати реально?

Ні, і це свідоме рішення. `lab live` падає, адаптера виконання немає, `.env` цього не змінює.
Порядок у проєкті: research → (окреме рішення) paper на живих даних → лише потім live.
Перші два кроки тут і реалізовані.

### Чому роботи ставлять ринкові ордери, а не лімітні?

Бо симуляція лімітних ордерів потребує моделі черги книги (queue position) — без неї результати
будуть оптимістичними й оманливими. Ринковий ордер завжди виконується, і його комісія (тейкерська)
консервативна. `QuoteIntent` для лімітних котировок уже є в домені (GLFT) — його підключення
потребує окремої роботи ([08 §4.1](08-mft-2026-vidpovidnist.md)).

### Як змінити таймфрейм?

```dotenv
BAR_INTERVAL=5m
```

Потім **новий** каталог і новий ingest (серії різних таймфреймів не змішуються):

```bash
uv run lab ingest --start 2025-06-01 --symbols ETHUSDT --catalog catalog_5m
uv run lab research --catalog catalog_5m
```

Пам'ятайте: на дрібнішому таймфреймі комісії стають вирішальним фактором, а мінімум барів
для прогріву (150) накриває вже кілька днів історії, а не тижнів.

### Як довго триває прогін?

Орієнтири з цієї машини:

| Прогін | Час |
|--------|-----|
| `--synthetic --bars 5000` | ~2.4 с |
| `--synthetic --bars 2000` (ema) | ~1 с |
| Walk-forward, 5088 барів, сітка 6 | ~8.5 с |
| Walk-forward, 5088 барів, сітка 4 (`ema`) | ~5 с |
| Walk-forward, 5088 барів, `--optuna --trials 5` | ~9 с |
| `--synthetic --bars 800 --tearsheet …` | ~2 с + генерація HTML (файл ~4 МБ) |
| `ingest` 7 місяців по 1h, два символи | ~6.5 с |
| `--folds 4` на 23 697 барах 1h (сітка 6, `regime`) | ~86 с |
| `pytest` (167 тестів, разом із рушієм) | ~7 с |

Час зростає лінійно з кількістю кандидатів у сітці (кожен кандидат — окремий прогін рушія на IS).
Багатовіконний режим множить це на кількість фолдів: `N` фолдів — це приблизно `N` окремих
walk-forward, тому `--folds 4` із сіткою 6 — це близько 28 прогонів рушія.

### Де фізично лежать дані?

```
catalog/data/bar/<INSTRUMENT>-<TIMEFRAME>-LAST-EXTERNAL/<період>.parquet   # свічки
catalog/data/currency_pair/<INSTRUMENT>/<...>.parquet                      # опис інструмента
```

Тека `catalog/` у `.gitignore` — дані не потрапляють у git. Файли можна копіювати між машинами,
а повторний запис у той самий каталог із перекриттям тепер безпечний: `write()` замінює свій
діапазон, а `load()` дедуплікує (див. першу помилку вище).

### Як додати новий інструмент (наприклад SOLUSDT)?

1. `infrastructure/nautilus/instrument.py` → додати `"SOL/USDT.SIM": ("SOL", "USDT", 2, "0.01", "0.001")` у `_SPOT_SPECS`.
2. `.env` → `BINANCE_SYMBOLS=["SOLUSDT"]` або `--symbols SOLUSDT` у команді.
3. `INSTRUMENT_ID=SOL/USDT.SIM` (якщо хочете зробити його основним).
4. `uv run lab ingest --start 2025-01-01 --symbols SOLUSDT --catalog catalog_sol`.
5. `uv run lab research --catalog catalog_sol`.

### Чому в звіті немає `max_dd`, `fees_paid` і `sharpe_like`?

Бо walk-forward друкує лише `fills` і `ending_balance` для кожного фолда. Метрики (`max_dd`,
`fees_paid`, `turnover`, `sharpe_like`) показуються у `--full-sample` і `--synthetic`.
Хочете метрики для конкретної конфігурації — прогоніть її окремо з `--full-sample`
на тому вікні, яке вас цікавить.

### Чи можна зробити walk-forward на синтетичних даних?

Так — додайте `--walk-forward` (або `--optuna`):

```bash
uv run lab research --synthetic --bars 1200 --walk-forward
```

Синтетика використовує **1-хвилинні** бари починаючи з 2024-01-01, тож 1200 барів — це лише 20 годин.
Приклад виводу показує, наскільки оманливим може бути такий результат:

```
in-sample (selection only) fills=17 ending=272625.25800441     (+172%!)
out-of-sample (report this) fills=2 ending=99900.20080881      (-0.1%)
```

Використовуйте це як перевірку механіки (чи працює розріз IS/OOS), а не як дослідження стратегії.

### Чи можна порівнювати `sharpe_like` з річним Sharpe?

Ні. Це середнє/стандартне відхилення **барних** дохідностей equity. Річний Sharpe буде відрізнятися
на множник, що залежить від таймфрейму. Використовуйте його для порівняння прогонів **між собою**
на тому самому таймфреймі.

### Що робити, якщо стратегія «не працює»?

Порядок дій:
1. Перевірте, що `fills > 0` (інакше дивіться причину вище).
2. Прогоніть baseline `--robot ema`. Якщо ваша стратегія гірша за перетин EMA — шукайте помилку в логіці.
3. Перевірте, чи не «з'їдені» комісіями (`fees_paid` проти прибутку).
4. Перевірте різні нарізки (`--is-fraction`, `--embargo-bars`) — результат не має бути крихким.
5. Перевірте стрес-слайс.
6. Якщо все одно ні — ймовірно, переваги немає. Це нормальний, очікуваний результат більшості ідей.

### Де знайти відповідь на питання «а чому код зроблено саме так»?

Кожен модуль має docstring із поясненням наміру (наприклад, `RegimeClassifier`:
«Trend vs range from Kaufman efficiency ratio and EMA slope. No look-ahead.»).
Читайте код разом із [03-arhitektura.md](03-arhitektura.md) і [12-karta-fayliv.md](12-karta-fayliv.md).

## Куди йти далі

- Карта всіх модулів → [12-karta-fayliv.md](12-karta-fayliv.md)
- Повний цикл дослідження → [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md)
