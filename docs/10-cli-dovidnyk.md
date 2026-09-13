# 10. Довідник CLI

Точний синтаксис усіх команд. Команда `lab` — єдина точка входу проєкту.

```bash
uv run lab <команда> [прапорці]
```

Якщо `uv` не має доступу до свого кеша — `.venv/bin/lab <команда>`.

| Команда | Що робить | Код виходу при помилці |
|---------|-----------|------------------------|
| `lab ingest` | Завантажує публічні klines Binance у Parquet-каталог | 1 |
| `lab research` | Бектест/симуляція (основний шлях; за замовчуванням walk-forward) | 1 |
| `lab paper` | Лог гіпотетичних ордерів, без виконання | 1 |
| `lab scan` | Дослідницькі сканери (трикутний арбітраж) | 1 |
| `lab live` | **Завжди помилка** (жива торгівля вимкнена) | 1 завжди |

Успіх будь-якої команди → код виходу `0`, повідомлення про помилки друкуються в `stderr`.

---

## `lab ingest`

```
usage: lab ingest [-h] [--start START] [--end END] [--catalog CATALOG] [--symbols SYMBOLS]
```

| Прапорець | Типово | Опис |
|-----------|--------|------|
| `--start` | 365 днів тому | Початок вікна (UTC, `YYYY-MM-DD`) |
| `--end` | зараз | Кінець вікна (**виключно**, UTC) |
| `--catalog` | `CATALOG_PATH` з `.env` (`catalog`) | Тека каталогу |
| `--symbols` | `BINANCE_SYMBOLS` з `.env` (`ETHUSDT,BTCUSDT`) | Символи через кому |

Що робить: публічний REST `https://api.binance.com/api/v3/klines`, пагінація по 1000 свічок,
без API-ключів. Інтервал беруть із `BAR_INTERVAL` (типово `1h`). Записує бари й опис інструмента в каталог.

Приклади:

```bash
uv run lab ingest --start 2025-01-01
uv run lab ingest --start 2025-01-01 --end 2025-08-01 --symbols ETHUSDT
uv run lab ingest --start 2019-01-01 --end 2025-01-01 --symbols ETHUSDT,BTCUSDT --catalog catalog_long
```

Вивід:

```
symbol=ETHUSDT wrote=5088 first=2025-01-01T00:59:59.999000+00:00 last=2025-07-31T23:59:59.999000+00:00 catalog=/.../catalog
```

Помилки:
- `binance klines error: {...}` — біржа повернула помилку (невідомий символ, обмеження).
- `unsupported binance symbol: XXX` — символ не закінчується на `USDT` (підтримуються лише `*USDT`).
- `no public klines for SYMBOL ... in [start, end)` — у вікні немає даних.

> ⚠️ **Один каталог — один ingest.** Повторний запуск із вікном, що перекривається, створить
> дублікати барів і зламає всі наступні `lab research`. Деталі: [04](04-tsykl-doslidzhennya.md#крок-1-ingest--завантаження-історії).

---

## `lab research`

```
usage: lab research [-h] [--bars BARS]
                    [--robot {regime,ema,pairs,funding,ml_obi,glft,tri_scan}]
                    [--synthetic] [--full-sample] [--walk-forward]
                    [--is-start IS_START] [--is-end IS_END]
                    [--oos-start OOS_START] [--oos-end OOS_END]
                    [--is-fraction IS_FRACTION] [--catalog CATALOG]
                    [--slice SLICE] [--embargo-bars EMBARGO_BARS] [--bar-vpin]
```

| Прапорець | Типово | Опис |
|-----------|--------|------|
| `--bars` | `3000` | Кількість барів для синтетичного режиму |
| `--robot` | `ROBOT` з `.env` (`regime`) | Який робот запускати. **`funding`, `ml_obi`, `glft`, `tri_scan` мовчазно запускають `regime`** — див. [05](05-roboty.md#0-таблиця-стану-читати-першою) |
| `--synthetic` | вимкнено | Синтетичні бари замість каталогу (мережа не потрібна). Режим **повного прогону**, не walk-forward |
| `--full-sample` | вимкнено | Один прогін каталогу на всій серії. **Не** є out-of-sample звітом |
| `--walk-forward` | увімкнено для каталогу | Підбір на in-sample, звіт на out-of-sample |
| `--is-start`, `--is-end` | — | Вікно in-sample (UTC, `YYYY-MM-DD`, кінець виключно) |
| `--oos-start`, `--oos-end` | — | Вікно out-of-sample |
| `--is-fraction` | `0.7` | Частка історії на підбір, коли дати не задані |
| `--catalog` | `CATALOG_PATH` | Тека каталогу |
| `--slice` | — | Стрес-період: `covid2020`, `ftx2022`, `etf2024` |
| `--embargo-bars` | `EMBARGO_BARS` (`10`) | Розрив між IS і OOS |
| `--bar-vpin` | вимкнено | Увімкнути VPIN-фільтр режиму (робот `regime`) |

Логіка вибору режиму:

1. `--synthetic` → синтетичний прогін (повний, не walk-forward).
2. інакше, якщо `--full-sample` → один прогін по всьому каталогу.
3. інакше → walk-forward (типово).

Приклади:

```bash
uv run lab research --synthetic --bars 5000              # швидкий smoke-тест
uv run lab research                                     # walk-forward, regime, каталог
uv run lab research --robot ema                          # baseline
uv run lab research --robot pairs                        # дві ноги
uv run lab research --full-sample                        # вся вибірка, лише in-sample
uv run lab research --is-fraction 0.5 --embargo-bars 0   # інша нарізка
uv run lab research --bar-vpin                           # VPIN-фільтр
uv run lab research --slice etf2024 --catalog catalog_long
uv run lab research --is-start 2025-01-01 --is-end 2025-05-01 \
                    --oos-start 2025-05-15 --oos-end 2025-07-01 --catalog catalog_ok
```

Вивід walk-forward:

```
walk-forward: parameters selected on in-sample only; report out-of-sample. tried=6 selected=... IS=[...] OOS=[...]
in-sample (selection only) fills=117 ending=109331.62479635
out-of-sample (report this) fills=51 ending=100814.86162670
```

Вивід повного прогону / синтетики:

```
[full-sample catalog run (in-sample only; not an out-of-sample report)]
fills=132 positions=53 ending=3351101.12843644
fees_paid=254875.71083357 max_dd=0.06037193860184920896654706057 turnover=253132507.51288 sharpe_like=0.01411781072007535550147682646
regime synthetic backtest with fees (maker=0.0002 taker=0.0005), 50ms latency, 25% one-tick slippage
```

Помилки (усі → код виходу 1):

| Повідомлення | Причина |
|--------------|---------|
| `bar timestamps must be strictly increasing` | Дублікати в каталозі (повторний ingest) → див. [11](11-troubleshooting-faq.md#bar-timestamps-must-be-strictly-increasing) |
| `no bars in catalog ... Run 'lab ingest' first.` | Порожній каталог або вікно/слайс поза даними |
| `no bars in catalog ... in the requested window` | Вікно поза межами завантаженої історії |
| `bar_count must be >= 150 so indicators can warm up` | Замало барів (regime 150, pairs 200, решта 50) |
| `walk-forward dates require --is-start --is-end --oos-start --oos-end` | Задано не всі чотири дати |
| `in-sample must not overlap out-of-sample` | IS заходить у OOS |
| `unknown stress slice 'xxx'; use one of: covid2020, ftx2022, etf2024` | Друкарська помилка в `--slice` |
| `unsupported instrument_id: XXX` | Інструмент не в списку симуляції |
| `unsupported bar interval 'xx'` | `BAR_INTERVAL` не з набору `1m/5m/15m/1h/4h/1d` |
| `Live trading is disabled...` | `TRADING_MODE=live` |

---

## `lab paper`

```
usage: lab paper [-h] [--bars BARS] [--robot {regime,ema}]
```

| Прапорець | Типово | Опис |
|-----------|--------|------|
| `--bars` | `500` | Кількість синтетичних барів |
| `--robot` | `regime` | Лише `regime` або `ema` |

Що робить: проганяє синтетичні бари через вибраний робот і **записує** в лог ордери,
які були б надіслані. Жодного рушія, жодного виконання, жодного оновлення капіталу,
жодного стану позиції (тому може записати кілька `buy` підряд).

```bash
uv run lab paper --bars 500
uv run lab paper --robot ema --bars 200
```

```
paper_orders=289 (no exchange submission)
2024-01-01T00:49:00+00:00 ETH/USDT.SIM buy qty=13.045 reason=donchian breakout long
...
```

Друкує перші 10 ордерів; повний список — в об'єкті `PaperTradingLogger.orders`.

---

## `lab scan`

```
usage: lab scan [-h] [--triangular]
```

| Прапорець | Опис |
|-----------|------|
| `--triangular` | Шукає цикли від'ємної ваги серед курсів-зразків |

Без прапорця — помилка `Specify --triangular` (код 1).

```bash
uv run lab scan --triangular
triangular_opportunities=0
```

Курси зараз зашиті в `cli.py` (`USDT/BTC = 0.000015`, `BTC/ETH = 15`, `ETH/USDT = 3500`)
і дають нуль можливостей — це демонстрація, а не реальний сканер.
Для власних курсів використовуйте `scan_triangular_opportunities()`
(див. [09 §7](09-mft-moduli-pryklady.md#7-трикутний-арбітраж-зі-своїми-курсами)).

---

## `lab live`

```
usage: lab live [-h]
```

Завжди завершується помилкою:

```
$ uv run lab live
Live trading is disabled. This lab only runs research backtests.
$ echo $?
1
```

Це не «ще не налаштовано», а **свідомий запобіжник**: у коді немає жодного адаптера,
який може надіслати ордер на біржу. Прапорець `LIVE_ENABLED=true` у `.env` нічого не змінює.

---

## Змінні середовища: швидка шпаргалка

Повний опис — у [02-vstanovlennya.md](02-vstanovlennya.md#3-усі-змінні-налаштування).
Найуживаніші:

```dotenv
TRADING_MODE=research        # research | paper | live (live завжди блокується)
CATALOG_PATH=catalog
BAR_INTERVAL=1h              # 1m | 5m | 15m | 1h | 4h | 1d
INSTRUMENT_ID=ETH/USDT.SIM
BINANCE_SYMBOLS=["ETHUSDT","BTCUSDT"]
STARTING_EQUITY=100000
RISK_PER_TRADE=0.005
STOP_PCT=0.01
MAX_DAILY_LOSS=0.02
MAX_DRAWDOWN=0.06
KELLY_FRACTION=0.25
MAX_VAR_99=0.05
ROBOT=regime
EMBARGO_BARS=10
MAKER_FEE=0.001
TAKER_FEE=0.001
USE_BAR_VPIN=false
```

Пріоритет джерел: **змінні оболонки → `.env` → значення в коді**.
Перевірити, що реально бачить програма:

```bash
uv run python -c "
from nautilus_lab.infrastructure.settings import Settings
s = Settings()
print('mode:', s.trading_mode, 'robot:', s.robot, 'interval:', s.bar_interval)
print('fees:', s.fee_schedule(), 'risk:', s.risk_limits().risk_per_trade)
"
```

---

## Типові послідовності команд

**Перше знайомство (5 хвилин, без мережі):**

```bash
uv run lab research --synthetic --bars 3000
uv run lab paper --bars 500
uv run lab live            # переконатися, що жива торгівля заблокована
```

**Повний цикл на реальних даних:**

```bash
rm -rf catalog
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
uv run lab research --robot ema          # baseline
uv run lab research                      # основний прогін
uv run lab research --robot pairs
```

**Стрес-тести на довгій історії:**

```bash
uv run lab ingest --start 2019-01-01 --end 2025-01-01 --symbols ETHUSDT --catalog catalog_long
uv run lab research --slice covid2020 --catalog catalog_long
uv run lab research --slice ftx2022   --catalog catalog_long
uv run lab research --slice etf2024   --catalog catalog_long
```

**Перевірка якості після зміни коду:**

```bash
uv run pytest
uv run ruff check --fix && uv run ruff format
uv run mypy src tests
uv run lab research --synthetic --bars 3000
```

## Куди йти далі

- Щось не працює → [11-troubleshooting-faq.md](11-troubleshooting-faq.md)
- Що означає вивід → [04-tsykl-doslidzhennya.md](04-tsykl-doslidzhennya.md#крок-5-як-читати-звіт)
