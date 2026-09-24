# 13. Відповідність «Алгоритми ШІ У Криптоторгівлі 2026 (1).md» і коду

Цей документ відповідає на питання: **що з оглядового ШІ-дослідження 2026 можна
безпечно застосувати в nautilus-lab**, не ламаючи існуючі роботи `regime`, `ema`, `pairs`.

Джерело: [Алгоритми ШІ У Криптоторгівлі 2026 (1).md](../Алгоритми%20ШІ%20У%20Криптоторгівлі%202026%20(1).md).

Пов’язаний, але **інший** документ — [Стратегії MFT Криптоторгівлі 2026.md](../Стратегії%20MFT%20Криптоторгівлі%202026.md)
(мапа в [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md)).

Легенда:

| Позначка | Значення |
|----------|----------|
| ✅ | Реалізовано **і підключено** |
| 🟡 | Реалізовано як **бібліотека/блок** або opt-in шар |
| 🔴 | Не реалізовано / поза скоупом lab |
| ⚪ | Поза кодом (інфраструктура, DeFi, TEE) |

---

## 0. Позиціонування

ШІ-документ описує індустріальний арсенал 2026: LLM-альфи, PatchTST/Mamba, Deep Hawkes,
PPO-портфелі, автономні агенти на Uniswap v4. **nautilus-lab** — research-пісочниця на
годинних барах, де до рушія підключено вісім роботів (`regime`, `ema`, `pairs`,
`vpin_momentum`, `formulaic_lgbm`, `meta_label`, `adaptive_ema`, `ml_obi` —
`domain/regime.py::BACKTEST_WIRED_ROBOTS`) і з fail-closed live.

Корисне ядро документа для цього проєкту:

1. **Багато простих альф → динамічне зважування → жорсткий ризик** (не глибина мережі).
2. **Періодична переоцінка коінтеграції** (хибна кореляція vs структурний зв’язок).
3. **Комісії та оборот** важливіші за Sharpe в бектесті без реалістичного FillModel.

Усе нове — **opt-in** (`--robot`, прапорці `.env`). Дефолт лишається `regime`.

---

## 1. LLM / LRM (DeepSeek-R1, formulaic alphas)

| Що в документі | Стан у коді |
|----------------|-------------|
| LLM генерує formulaic alphas | 🔴 у торговому циклі (немає мережі в domain) |
| PPO зважує альфи в портфелі | 🔴 немає й замінника: функції `ensemble_vote` у коді **не існує** (згадка в цьому документі була хибною). Найближче, що є — гейт `meta_label` поверх `regime`, але це фільтр входів однієї підстратегії, а не зважування альф у портфелі |
| Офлайн дослідження гіпотез | ✅ `application/propose_alphas.py` (+ `lab propose`, `scripts/propose_alphas.py`) і контракт гіпотези `domain/hypothesis.py`; DSL-оцінка — `application/evaluate_recipe.py` над `domain/factor_dsl.py` |
| Робот на формульних ознаках + LightGBM | ✅ `formulaic_lgbm` (потрібен `FORMULAIC_MODEL_PATH`) |

**Правило:** LLM не викликається з `on_bar`. Модель навчається офлайн, у бектест
завантажується файл бустера (як `LightGBMDirectionClassifier`).

---

## 2. Часові ряди: Transformers / Mamba / PatchTST

| Що в документі | Стан |
|----------------|------|
| PatchTST, Informer, PMformer | 🔴 |
| Mamba-2/3 для LOB | 🔴 (потрібні L3 тіки + GPU) |
| Meta-RL-Crypto | 🔴 |

На `bar_execution` + 1h без L2 ці моделі навчаться на артефактах симулятора.

---

## 3. Мікроструктура: Hawkes, OBI, LightGBM

| Що в документі | Стан |
|----------------|------|
| LightGBM + OBI/WOFI | ✅ підключено, виміру немає: `ml_obi` у `BACKTEST_WIRED_ROBOTS`, книга ордерів пишеться `lab ingest --depth`, навчання — `lab ml train --model-type obi` |
| Deep Multivariate Hawkes | 🟡 `ExponentialHawkes` — підключений лише як **фільтр режиму** (`--hawkes`), і оцінка в ньому одновимірна: терм взаємного збудження `cross_alpha` у класі є, але `Settings` його не виставляє |
| VPIN як фільтр режиму | ✅ `RegimeRouter` + `--bar-vpin` (барові кошики) / `--tick-vpin` (кошики з aggTrades) |
| VPIN momentum робот | ✅ `vpin_momentum` |

---

## 4. DRL (PPO, SAC, DDPG)

| Що в документі | Стан |
|----------------|------|
| PPO для зважування альф | 🔴 |
| PPO/SAC як виконавець ордерів | 🔴 |
| Обмеження turnover / геометричні TC | 🟡 Kelly + vol-scaling + CVaR breaker (opt-in) |

Документ сам попереджає: DRL без реалістичних комісій дає overtrading. У lab спочатку
увімкнені **ризик-оверлеї**, а не RL-агент.

---

## 5. DeFi, MEV, TEE, автономні агенти

| Розділ | Стан |
|--------|------|
| Uniswap v4 hooks | ⚪ |
| MEV / Flashbots | ⚪ |
| TEE / Phala | ⚪ |
| GOAT SDK / copy-trade боти | ⚪ |

Поза скоупом: lab — Binance spot/perp research, не on-chain execution.

---

## 6. Ризик і нестаціонарність

| Що в документі | Стан |
|----------------|------|
| Engle–Granger / Johansen | ✅ ADF у `pairs`; Johansen 🔴 |
| Rolling refit β | ✅ `PAIRS_REFIT_EVERY` (0 = стара поведінка) |
| VaR circuit breaker | ✅ `evaluate_entry` |
| CVaR breaker | ✅ opt-in `USE_CVAR_BREAKER` |
| Fractional Kelly | ✅ opt-in `USE_FRACTIONAL_KELLY` |
| HAR-RV vol-scaling | ✅ opt-in `USE_VOL_SCALING` |
| CFA / ensemble | 🔴 жодного ансамблю й жодного `ensemble_vote` у коді немає — і це свідома позиція (див. [17 §3](17-ml-ansambli-vidpovidnist.md), [19 §5](19-ml-steking-vidpovidnist.md)): ансамбль знижує дисперсію навколо переваги, якої поки немає |
| PBO / CSCV | ✅ `domain/overfitting.py` + `application/run_overfitting_audit.py`, прапорець `--pbo` (див. [15](15-audit-vypravlennya.md), [08 §2.2](08-mft-2026-vidpovidnist.md)) |
| Turnover / cost-aware selection | ✅ частково: `application/score.py::in_sample_score()` віднімає `turnover_haircut * turnover` (`DEFAULT_TURNOVER_HAIRCUT = 0.0005`) від `ending_balance`, тож вибір параметрів на IS уже cost-aware. `fees_paid` при цьому **не** віднімається вдруге — комісії вже сидять у балансі. 🔴 Оборот не входить у саму метрику звіту як окремий вердикт: OOS-рішення ухвалюють OOS-дохідність проти buy&hold, PBO і DSR |

---

## 7. Підсумкова таблиця

| Розділ ШІ-документа | Статус | Ключовий файл |
|---------------------|--------|----------------|
| LLM formulaic alphas | 🟡 офлайн | `application/propose_alphas.py`, `domain/hypothesis.py` |
| PPO зважування | 🔴 | — |
| PatchTST / Mamba | 🔴 | — |
| LightGBM + OBI | ✅ підключено, виміру немає | `domain/ml_obi_strategy.py`, `application/train_obi.py` |
| VPIN | ✅ | `domain/vpin.py`, `vpin_momentum` |
| Hawkes | ✅ opt-in фільтр режиму | `domain/hawkes.py`, `--hawkes` |
| Коінтеграція + rolling refit | ✅ | `domain/pairs/pairs_trading.py` |
| DRL портфель | 🔴 | — |
| Kelly / vol / CVaR overlays | ✅ opt-in | `application/risk.py`, adapters |
| Formulaic LGBM robot | ✅ | `domain/formulaic_lgbm_strategy.py` |
| PBO / CSCV | ✅ | `domain/overfitting.py`, `--pbo` |
| DeFi / TEE / agents | ⚪ | — |

---

## 8. Як увімкнути нові можливості

### Ризик-оверлеї (не змінюють сигнали `regime`/`ema`/`pairs`)

```dotenv
USE_VOL_SCALING=false
VOL_SCALING_TARGET=0.02
USE_FRACTIONAL_KELLY=false
USE_CVAR_BREAKER=false
MAX_CVAR_99=0.05
```

### Rolling refit для pairs

```dotenv
PAIRS_REFIT_EVERY=0    # 0 = заморозити β після першого фіту (як раніше)
PAIRS_REFIT_EVERY=24     # перефіт кожні 24 бари (1h → раз на добу)
```

**Каденція.** `PAIRS_REFIT_EVERY` задає, як часто коінтеграція переоцінюється — в **обох**
напрямках: і поки робот чекає на перший вхід у пару, і після того, як плановий рефіт закрив ворота
на вже відкритій позиції. Якщо рефіт не проходить ворота, робот відходить убік і повторює спробу
через повний інтервал, а не на кожному барі.

Це не косметика. Спроба на кожному барі означала ADF-фіт на **~75% барів** замість ~4%, які
випливають із `24` — і перетворювала прогін `pairs --folds 4` на понад годину. Після виправлення
разом з оптимізацією ADF той самий прогін триває **~3 хвилини**.

**Що це дає на реальних даних** (ETH/BTC 1h, 4 ковзні фолди, OOS 2025-11-22 … 2026-09-14):

| | рефіт вимкнено | рефіт `24` |
|---|---|---|
| фолдів у плюсі | 0/4 | **2/4** |
| середнє OOS | −4.41% | **−0.70%** |
| найгірший фолд | −6.06% | **−2.22%** |
| угод OOS | 856 | **356** |
| проти buy&hold (+2.44%) | гірше | усе ще гірше |

Тобто рефіт справді працює як задумано: робот перестає торгувати парою, коінтеграція якої зникла —
угод утричі менше, збитки в рази менші. **Але переваги це не доводить**: планку buy&hold не
подолано навіть із рефітом.

### Нові роботи

```bash
uv run lab research --robot vpin_momentum --synthetic --bars 3000
uv run python scripts/train_formulaic_lgbm.py --catalog catalog --output models/formulaic.txt
uv run lab research --robot formulaic_lgbm
```

### Перевірити, чи підбір параметрів узагалі щось значить

```bash
# PBO/CSCV: 8 блоків історії, кожна конфігурація сітки оцінюється на кожному блоці
uv run lab research --robot regime --pbo --pbo-blocks 8
```

Це прямий практичний висновок із розділу про перенавчання: замість віри в те, що
«сітка з 6 комбінацій безпечна», інструмент дає одне число — як часто переможець
in-sample провалюється out-of-sample. Деталі й реальний результат — [15](15-audit-vypravlennya.md).

---

## 9. Куди йти далі

- Що виправлено під час аудиту коду (знайдені помилки) → [15-audit-vypravlennya.md](15-audit-vypravlennya.md)
- Як LLM/LRM-модель реально допомагає в торгівлі (ролі, контури, промпти, пастки) → [14-llm-model-u-torhivli.md](14-llm-model-u-torhivli.md)
- MFT-мапа (VPIN, GLFT, funding) → [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md)
- Новий робот покроково → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
- Приклади MFT-модулів → [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md)
