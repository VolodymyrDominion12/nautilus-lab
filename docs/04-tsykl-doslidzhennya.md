# 04. Повний цикл дослідження

Це головний практичний документ: від сирих даних до чесного висновку «стратегія працює / не працює».
Усі команди можна копіювати як є. Числа в прикладах — реальний вивід із цієї машини,
щоб було з чим порівнювати свої результати.

```
 (0) Підготовка       →  .env, синтетичний smoke-тест
 (1) Ingest           →  завантажити історію один раз
 (2) Sanity check     →  перевірити, що дані цілі (немає дублікатів!)
 (3) Baseline         →  walk-forward найпростішої стратегії
 (4) Основний прогін  →  walk-forward робота, який вас цікавить
 (5) Читання звіту    →  IS окремо, OOS окремо, метрики
 (6) Стрес-слайси     →  як поводиться в паніці
 (7) Явні вікна       →  перевірити на конкретному ринковому періоді
 (8) Чутливість       →  embargo, частка IS, фільтри
 (9) Висновок         →  журнал результатів і критерій прийняття
```

---

## Крок 0. Підготовка

```bash
cp .env.example .env
uv sync --extra dev
uv run lab research --synthetic --bars 3000   # smoke-тест: мережа не потрібна
```

`--synthetic` — детерміновані згенеровані бари (той самий seed → той самий результат).
Це перевірка «чи живий код», **а не** перевірка стратегії: дохідність на синтетиці нічого не означає.
Приклад із цієї машини (щоб ви не злякалися числа):

```
fills=132 positions=53 ending=3351101.12843644        <-- +3251%! І це повний артефакт синтетики
fees_paid=254875.71 max_dd=0.0603719386 turnover=253132507.51 sharpe_like=0.0141
```

Синтетичний random walk має занадто «чисті» тренди й не має реальної мікроструктури.
Запам'ятайте це число як приклад того, як виглядає **неправдоподібний** результат.

## Крок 1. Ingest — завантаження історії

```bash
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
```

Що відбувається: публічний REST Binance (`/api/v3/klines`, без API-ключів) → доменні бари →
Parquet-каталог Nautilus. Запити пагінуються по 1000 свічок.

Реальний вивід:

```
symbol=ETHUSDT wrote=5088 first=2025-01-01T00:59:59.999000+00:00 last=2025-07-31T23:59:59.999000+00:00 catalog=/.../catalog
symbol=BTCUSDT wrote=5088 first=2025-01-01T00:59:59.999000+00:00 last=2025-07-31T23:59:59.999000+00:00 catalog=/.../catalog
```

Корисні варіанти:

```bash
uv run lab ingest --start 2025-01-01 --end 2025-08-01 --symbols ETHUSDT   # вузьке вікно
uv run lab ingest --start 2025-01-01 --catalog catalog_2025               # окрема тека каталогу
uv run lab ingest --start 2025-01-01 --symbols ETHUSDT --catalog .cache/eth_1h
```

> ### ⚠️ Найважливіше правило цього кроку
> **Не запускайте `lab ingest` двічі в один і той самий каталог із вікнами, що перекриваються.**
> Кожен запуск пише **новий** parquet-файл. Два файли з перекриттям = дублікати барів,
> і всі наступні `lab research` впадуть з помилкою `bar timestamps must be strictly increasing`.
>
> Правильно:
> ```bash
> rm -rf catalog && uv run lab ingest --start 2025-01-01 --symbols ETHUSDT,BTCUSDT
> ```
> **Один каталог = один ingest.** Потрібне інше вікно — нова тека через `--catalog`.

## Крок 2. Sanity check — перевірка цілісності даних

Обов'язковий крок перед будь-якими висновками. Перевіряємо кількість барів і наявність дублікатів:

```bash
.venv/bin/python - <<'PY'
from collections import Counter
from datetime import UTC, datetime

from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog("catalog")
for bar_type in ("ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL", "BTC/USDT.SIM-1-HOUR-LAST-EXTERNAL"):
    try:
        bars = catalog.bars(bar_types=[bar_type])
    except Exception as exc:                      # серії може не бути в каталозі
        print(f"{bar_type}: НЕ ЗНАЙДЕНО ({exc})")
        continue
    counts = Counter(bar.ts_event for bar in bars)
    dups = sum(value - 1 for value in counts.values() if value > 1)
    start = datetime.fromtimestamp(bars[0].ts_event / 1_000_000_000, tz=UTC)
    end = datetime.fromtimestamp(bars[-1].ts_event / 1_000_000_000, tz=UTC)
    print(f"{bar_type}: bars={len(bars)} unique={len(counts)} duplicates={dups}")
    print(f"    {start} .. {end}")
PY
```

> Порада: якщо такий код потрібен часто, покладіть його у файл `tools/catalog_health.py`
> і запускайте `.venv/bin/python tools/catalog_health.py catalog`.

Здоровий вивід (реальний приклад для 7 місяців погодинних даних):

```
ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL: bars=5088 unique=5088 duplicates=0
    2025-01-01 00:59:59 .. 2025-07-31 23:59:59
BTC/USDT.SIM-1-HOUR-LAST-EXTERNAL: bars=5088 unique=5088 duplicates=0
    2025-01-01 00:59:59 .. 2025-07-31 23:59:59
```

Хворий вивід (саме такий стан був у робочому каталозі цього репозиторію після двох ingest):

```
ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL: bars=17519 unique=8769 duplicates=8750   <-- СТОП. Перезавантажте каталог
```

**Правило перевірки:** `duplicates` мусить бути `0`, а `bars` — приблизно дорівнювати
`кількість_годин_у_вікні` (для `1h`) чи `кількість_хвилин` (для `1m`).
Для пар (`ETH` і `BTC`) кількості барів мають збігатися — інакше inner-join відкине розбіжні мітки часу.

## Крок 3. Baseline — з чим порівнювати

Ніколи не оцінюйте стратегію у вакуумі. Спочатку прогоніть найпростішу:

```bash
uv run lab research --robot ema
```

Реальний вивід (ETH/USDT, 1h, 2025-01-01 … 2025-08-01, 5088 барів, ризик 0.5%/угода, комісія 0.0002/0.0005):

```
walk-forward: parameters selected on in-sample only; report out-of-sample. tried=4
  selected=fast_ema=5 slow_ema=20 donchian=20 bb_k=2 z_entry=2
  IS=[2025-01-01T00:59:59.999, 2025-05-29T09:59:59.999)
  OOS=[2025-05-29T19:59:59.999, 2025-07-31T23:59:59.999+1µs)
in-sample (selection only) fills=66 ending=107207.70357440
out-of-sample (report this) fills=103 ending=97139.24799012
```

Читаємо: на in-sample підбір дав +7.2%, але на незнайомій частині історії — **−2.9%**.
Ось воно, перенавчання в чистому вигляді. Це нормальний, корисний baseline: тепер у нас є планка.

## Крок 4. Основний прогін

```bash
uv run lab research                    # робот за замовчуванням = regime, каталог, walk-forward
uv run lab research --robot regime
uv run lab research --robot pairs
```

Реальний вивід для `regime` на тих самих даних:

```
walk-forward: parameters selected on in-sample only; report out-of-sample. tried=6
  selected=fast_ema=10 slow_ema=20 donchian=10 bb_k=2.5 z_entry=2
  IS=[2025-01-01T00:59:59.999, 2025-05-29T09:59:59.999)
  OOS=[2025-05-29T19:59:59.999, 2025-07-31T23:59:59.999+1µs)
in-sample (selection only) fills=117 ending=109331.62479635
out-of-sample (report this) fills=51 ending=100814.86162670
```

Що сталося по кроках:

1. Каталог віддав 5088 барів ETH/USDT (1h).
2. `anchored_window` розрізав: IS — перші 70% (бар 0 … 3561), далі 10 барів embargo, далі OOS.
3. Перебрано 6 комбінацій: `DONCHIAN_PERIOD ∈ {10,20,40} × BB_K ∈ {2, 2.5}`.
4. Найкраща на IS — `donchian=10, bb_k=2.5` (IS: +9.3%).
5. Саме цю комбінацію запущено **один раз** на OOS: 51 філ, +0.8%.

**Висновок цього прогону: переваги немає.** +0.8% за два місяці при просадці, яка в процесі
впиралася у 6-відсотковий circuit breaker, — це в межах шуму. Так виглядає чесний результат,
і саме тому in-sample (+9.3%) не можна показувати як досягнення.

Аналогічно для `pairs`:

```
walk-forward: ... tried=3 selected=z_entry=1.5 ...
in-sample (selection only) fills=0 ending=100000.00000000
out-of-sample (report this) fills=0 ending=100000.00000000
```

`fills=0` — робот **не торгував зовсім**. Причина не в помилці: пара ETH/BTC 2025 року
не пройшла перевірку коінтеграції (спрощений ADF дає p-value 0.50 > порогу 0.05),
тож робот коректно відмовився відкривати позиції. Див. [05-roboty.md](05-roboty.md#3-pairs--статистичний-арбітраж-дві-ноги).

## Крок 5. Як читати звіт

Розберемо рядок за рядком.

```
walk-forward: parameters selected on in-sample only; report out-of-sample. tried=6 selected=donchian=10 bb_k=2.5 ...
```
- `tried=6` — скільки комбінацій перевірено. Що більше спроб, то вища ймовірність випадкової «перемоги»
  на IS (проблема PBO з MFT-документа, розділ 2.2). Сітка тут навмисно мала.
- `selected=...` — що саме вибрано. Завжди фіксуйте це в журналі.

```
IS=[start, end)   OOS=[start, end)
```
- Дужки `[` `)` означають «початок включно, кінець виключно».
- Між `IS end` і `OOS start` видно розрив — це embargo (10 барів), а не помилка.

```
in-sample (selection only) fills=117 ending=109331.62479635
```
- **Не результат.** Це те, на чому параметри підбиралися.

```
out-of-sample (report this) fills=51 ending=100814.86162670
```
- **Це результат.** Єдине число, яке має значення.

Для `--full-sample` або `--synthetic` рядки інші — там друкуються метрики:

```
fills=132 positions=53 ending=3351101.12843644
fees_paid=254875.71083357 max_dd=0.06037193860184920896654706057 turnover=253132507.51288 sharpe_like=0.01411781072007535550147682646
regime synthetic backtest with fees (maker=0.0002 taker=0.0005), 50ms latency, 25% one-tick slippage
```

| Поле | Як інтерпретувати |
|------|-------------------|
| `fills` | Кількість виконаних ордерів. Нуль = стратегія не торгувала. |
| `positions` | Скільки позицій відкривалося. |
| `ending_balance` | Баланс у квотній валюті (USDT). Старт — `STARTING_EQUITY`. |
| `fees_paid` | Сплачені комісії. Порівнюйте з різницею `ending_balance − STARTING_EQUITY`: якщо комісії більші — ви торгуєте на користь біржі. |
| `max_dd` | Максимальна просадка від піку. 0.06 = 6% — це той рівень, де вмикається circuit breaker. |
| `turnover` | Оборот (ціна × кількість по всіх надісланих ордерах). Показує, наскільки стратегія «метушлива». |
| `sharpe_like` | **Не** річний Sharpe: середня барна дохідність поділена на її стандартне відхилення. Дивіться на знак і на те, чи метрика взагалі є (для <3 точок кривої — `None`). |
| нотатка в кінці | Джерело даних (`regime synthetic backtest` / `... catalog backtest`), комісії, 50 мс затримки, 25% імовірність проковзування. |

## Крок 6. Стрес-слайси — перевірка на паніці

Замість усієї історії можна прогнати робота лише по «поганому» періоду:

```bash
uv run lab research --slice ftx2022      # 2022-05-01 … 2022-12-01, LUNA/FTX
uv run lab research --slice covid2020    # 2020-02-01 … 2020-05-01
uv run lab research --slice etf2024      # 2024-01-01 … 2024-06-01
```

**Обов'язкова умова:** ці періоди мають бути в каталозі. Якщо ні — буде чесна помилка:

```
$ uv run lab research --slice ftx2022
no bars in catalog /.../catalog_ok for ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL. Run `lab ingest` first.
$ echo $?
1
```

Тож для стрес-тестів потрібен окремий каталог із довгою історією:

```bash
uv run lab ingest --start 2019-01-01 --end 2025-01-01 --symbols ETHUSDT,BTCUSDT --catalog catalog_long
uv run lab research --slice covid2020 --catalog catalog_long
uv run lab research --slice ftx2022   --catalog catalog_long
uv run lab research --slice etf2024   --catalog catalog_long
```

Зауваження: `--slice` задає вікно завантаження барів, але walk-forward усе одно ділить його
на IS/OOS у пропорції `--is-fraction`. Тобто це «міні-історія» на один епізод, а не окремий звіт цілого року.

## Крок 7. Явні вікна IS/OOS

Найпотужніший інструмент: ви самі вирішуєте, на чому вчити й на чому перевіряти.

```bash
uv run lab research \
  --is-start 2025-01-01 --is-end 2025-05-01 \
  --oos-start 2025-05-15 --oos-end 2025-07-01 \
  --catalog catalog_ok
```

Реальний вивід:

```
IS=[2025-01-01T00:00:00+00:00, 2025-05-01T00:00:00+00:00)
OOS=[2025-05-15T00:00:00+00:00, 2025-07-01T00:00:00+00:00)
in-sample (selection only) fills=96 ending=104496.69450827
out-of-sample (report this) fills=44 ending=95404.68532305
```

Правила:
- Потрібні **всі чотири** дати. Якщо дати лише одну — помилка
  `walk-forward dates require --is-start --is-end --oos-start --oos-end`, код виходу 1.
- Дати парсяться як UTC-північ; кінець — **виключно**.
- IS і OOS не можуть перекриватися (`in-sample must not overlap out-of-sample`),
  але розрив між ними дозволений і рекомендований (тут 14 днів).
- Типовий сценарій: вчити на «бичачому» ринку, перевіряти на «ведмежому» (і навпаки).

## Крок 8. Чутливість результату

Гарний результат має бути стійким, а не «одноразовим». Три ручки для перевірки:

```bash
# 1. Скільки історії віддати на підбір: 0.5 (порівну) проти 0.7 і 0.8
uv run lab research --is-fraction 0.5
uv run lab research --is-fraction 0.8

# 2. Розрив між фолдами: 0 (без карантину) / 10 (типово) / 50 (жорстко)
uv run lab research --embargo-bars 0
uv run lab research --embargo-bars 50

# 3. VPIN-фільтр токсичного потоку на роботі regime
uv run lab research --bar-vpin
```

Реальні числа для наочності (той самий каталог, ETH/USDT 1h):

| Прогін | IS ending | OOS ending |
|--------|-----------|------------|
| типовий (`--is-fraction 0.7 --embargo-bars 10`) | 109 331.62 | **100 814.86** |
| `--is-fraction 0.5 --embargo-bars 0` | 102 907.75 | **105 026.32** |
| `--bar-vpin` | 117 586.32 | **102 438.21** |
| `--robot ema` (baseline) | 107 207.70 | **97 139.25** |

Як це читати (і чого **не** робити):

- Розкид OOS від 97k до 105k на різних налаштуваннях — сам по собі сигнал, що перевага слабка:
  результат чутливий до того, як саме ви нарізали історію.
- **Не можна** перебрати 10 варіантів `--is-fraction` і обрати найкращий OOS: OOS перестане бути out-of-sample.
  OOS дивляться **один раз** для остаточно обраної конфігурації. Для перебору налаштувань нарізки існує IS.
- Якщо хочете все ж порівняти кілька конфігурацій, діліть історію на три частини:
  IS (підбір) → validation (вибір конфігурації) → OOS (фінальний звіт, один раз). У CLI це робиться
  двома послідовними прогонами з різними явними вікнами.

## Крок 9. Paper-режим і фінальний чекліст

```bash
uv run lab paper --bars 500
uv run lab paper --robot ema --bars 500
```

Реальний вивід:

```
paper_orders=289 (no exchange submission)
2024-01-01T00:49:00+00:00 ETH/USDT.SIM buy qty=13.045 reason=donchian breakout long
...
```

Що важливо знати про `paper`:
- Це **не** бектест: немає рушія, немає виконання, немає оновлення капіталу.
  Просто «прожени сигнали й запиши, які ордери були б надіслані».
- Працює лише на синтетичних барах і лише для роботів `regime` та `ema`.
- Не веде стан позиції, тому може записати кілька «buy» підряд (як на виводі вище).
  Це очікувана спрощеність, а не сигнал до торгівлі.

### Чекліст «результату можна вірити»

- [ ] Каталог цілий: `duplicates=0` (крок 2).
- [ ] Є baseline (`--robot ema`) для порівняння.
- [ ] Названі `tried=` і `selected=` зафіксовані в журналі.
- [ ] OOS-вікно не використовувалося під час жодного підбору.
- [ ] Комісії задані як у реальності (`TAKER_FEE`), а не нулі.
- [ ] Прогін повторено на іншій нарізці (`--is-fraction`, `--embargo-bars`) і на стрес-слайсі.
- [ ] `fees_paid` не з'їдає весь прибуток; `turnover` не абсурдний.
- [ ] Результат OOS не «ідеально рівний» — ідеальна крива майже завжди означає підгляд у майбутнє.
- [ ] Результат відтворюваний: той самий прогін дає ті самі числа (`seed=42` для проковзування фіксований).

## Крок 10. Журнал досліджень

Ведіть простий файл (наприклад, `research-log.md` у себе, не в git, якщо не хочете ділитися):

```markdown
## 2025-08-01 regime / ETH-USDT 1h
- catalog: catalog_ok, 5088 барів, duplicates=0
- команда: lab research --catalog catalog_ok
- tried=6 selected=donchian=10 bb_k=2.5
- IS:[2025-01-01..2025-05-29) fills=117 ending=109331.62
- OOS:[2025-05-29..2025-07-31] fills=51 ending=100814.86  (+0.81%)
- baseline ema OOS: 97139.25 (-2.86%)
- висновок: перевага в межах шуму; повторна перевірка на 2024 році потрібна
- далі: --bar-vpin → OOS 102438.21; стрес-слайс ftx2022 (немає даних у каталозі)
```

Без журналу через два тижні ви не згадаєте, який саме прогін дав «той гарний результат»,
і неминуче почнете підбирати параметри, мимоволі дивлячись на OOS. Це найпоширеніший спосіб
обманути себе в кількісній торгівлі.

## Що далі

- Зрозуміти, як кожен робот ухвалює рішення → [05-roboty.md](05-roboty.md)
- Розібратися, звідки беруться розміри позицій → [06-ryzyk-metryky.md](06-ryzyk-metryky.md)
- Зробити свою стратегію → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
- Щось упало → [11-troubleshooting-faq.md](11-troubleshooting-faq.md)
