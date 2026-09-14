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
годинних барах з трьома класичними роботами і fail-closed live.

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
| PPO зважує альфи в портфелі | 🟡 замінник: `ensemble_vote` / мета-мітка — майбутнє |
| Офлайн дослідження гіпотез | ✅ `application/train_formulaic.py` + `domain/formulaic_alphas.py` |
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
| LightGBM + OBI/WOFI | 🟡 `ml_obi` — domain only, немає L2-фіду |
| Deep Multivariate Hawkes | 🟡 `ExponentialHawkes` — одновимірний |
| VPIN як фільтр режиму | ✅ `RegimeRouter` + `--bar-vpin` |
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
| CFA / ensemble | 🟡 `ensemble_vote` — заплановано після валідації окремих роботів |
| PBO / CSCV | 🔴 (див. scalper-hft для повного аудиту) |

---

## 7. Підсумкова таблиця

| Розділ ШІ-документа | Статус | Ключовий файл |
|---------------------|--------|----------------|
| LLM formulaic alphas | 🟡 офлайн | `application/train_formulaic.py` |
| PPO зважування | 🔴 | — |
| PatchTST / Mamba | 🔴 | — |
| LightGBM + OBI | 🟡 | `domain/ml_obi_strategy.py` |
| VPIN | ✅ | `domain/vpin.py`, `vpin_momentum` |
| Hawkes | 🟡 | `domain/hawkes.py` |
| Коінтеграція + rolling refit | ✅ | `domain/pairs/pairs_trading.py` |
| DRL портфель | 🔴 | — |
| Kelly / vol / CVaR overlays | ✅ opt-in | `application/risk.py`, adapters |
| Formulaic LGBM robot | ✅ | `domain/formulaic_lgbm_strategy.py` |
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

### Нові роботи

```bash
uv run lab research --robot vpin_momentum --synthetic --bars 3000
uv run python scripts/train_formulaic_lgbm.py --catalog catalog --output models/formulaic.txt
uv run lab research --robot formulaic_lgbm
```

---

## 9. Куди йти далі

- MFT-мапа (VPIN, GLFT, funding) → [08-mft-2026-vidpovidnist.md](08-mft-2026-vidpovidnist.md)
- Новий робот покроково → [07-yak-stvoryty-strategiyu.md](07-yak-stvoryty-strategiyu.md)
- Приклади MFT-модулів → [09-mft-moduli-pryklady.md](09-mft-moduli-pryklady.md)
