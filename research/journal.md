# Журнал рішень

Один рядок на кожну перевірену ідею — і на прийняту, і на відкинуту. Це найдешевший
захист від повторного відкриття тієї самої поганої ідеї.

Правило запису: **число, а не враження**. «Виглядало добре» не є результатом.
Планка — `buy&hold` за той самий OOS-період; якщо її не подолано, це так і пишеться.

| Дата (UTC) | Джерело | Гіпотеза / робот | Ворота | OOS | buy&hold | Рішення | Причина |
|------------|---------|------------------|--------|-----|----------|---------|---------|
<!-- journal:rows:start -->
| 2026-09-15 10:00 | _приклад_ | `pairs` ETH/BTC | walk-forward, refit 24 | -0.70% | +2.44% | ❌ rejected | планку buy&hold не подолано, 356 угод при комісії 0.1% |
| 2026-09-17 08:42 | lab api research | regime BTC/USDT.SIM | walk-forward catalog folds=2 | -4.45% | -3.79% | ⏳ pending | auto: profitable 0/2 folds |
| 2026-09-23 10:21 | lab api research | formulaic_lgbm BTC/USDT.SIM | PBO/CSCV blocks=8 configurations=3 | n/a | n/a | ⏳ pending | PBO undefined: 3 configurations x 8 blocks (need >= 2 configurations) |
| 2026-09-23 17:00 | людина (план, docs/25) | `xsmom` 7 монет 1d (BTC, ETH, SOL, BNB, XRP, ADA, DOGE) | walk-forward folds=6 + PBO/CSCV blocks=8, grid=6, calmar | +56.70% (середнє), 4/6 прибуткових | +54.39% (кошик) | ❌ rejected | ворота REJECT: profitable 4/6 < 5/6, PBO 0.40 > 0.30, DSR 0.931 < 0.95; перевага над кошиком +2.3 в.п. при просадках до 53% |
| 2026-09-24 14:57 | lab research | regime ETH/USDT.SIM | synthetic backtest (no OOS split) | n/a | n/a | ⏳ pending | auto: in-sample only; IS return 530.51% (not an OOS number) |
| 2026-09-24 15:57 | lab api research | formulaic_lgbm BTC/USDT.SIM | PBO/CSCV blocks=8 configurations=3 | n/a | n/a | ⏳ pending | PBO=0 over 70 splits x 3 configurations on 8 blocks (selection generalises, but no configuration is profitable on average) |
| 2026-09-24 16:02 | lab api research | formulaic_lgbm BTC/USDT.SIM | PBO/CSCV blocks=8 configurations=3 | n/a | n/a | ⏳ pending | PBO=0 over 70 splits x 3 configurations on 8 blocks (selection generalises, but no configuration is profitable on average) |
| 2026-09-25 08:42 | lab api research | formulaic_lgbm BTC/USDT.SIM | PBO/CSCV blocks=8 configurations=3 | n/a | n/a | ⏳ pending | PBO=0 over 70 splits x 3 configurations on 8 blocks (selection generalises, but no configuration is profitable on average) |
| 2026-09-25 08:57 | lab api research | formulaic_lgbm BTC/USDT.SIM | PBO/CSCV blocks=8 configurations=3 | n/a | n/a | ⏳ pending | PBO=0 over 70 splits x 3 configurations on 8 blocks (selection generalises, but no configuration is profitable on average) |
| 2026-09-25 16:51 | lab api research | regime ETH/USDT.SIM | PBO/CSCV blocks=8 configurations=6 | n/a | n/a | ⏳ pending | PBO=0.1142857142857142857142857143 over 70 splits x 6 configurations on 8 blocks (selection generalises, but no configuration is profitable on average) |
| 2026-09-25 17:08 | lab api research | regime ETH/USDT.SIM | walk-forward catalog folds=2 | -5.42% | -4.09% | ⏳ pending | auto: profitable 0/2 folds |
| 2026-09-28 07:36 | lab api research | regime ETH/USDT.SIM | walk-forward catalog folds=4 | 0.00% | 2.33% | ⏳ pending | auto: profitable 2/4 folds |
| 2026-09-28 07:41 | lab api research | regime ETH/USDT.SIM | walk-forward catalog single split | 1.17% | n/a | ⏳ pending | auto: single split; buy&hold not measured |
| 2026-09-29 09:15 | lab api research | regime ETH/USDT.SIM | walk-forward catalog single split | 1.27% | n/a | ⏳ pending | auto: single split; buy&hold not measured |
| 2026-10-12 06:05 | lab propose | proposal deepseek-v4-pro | not run yet (proposal only) | n/a | n/a | ⏳ pending | awaiting review: research/hypotheses/2026-10-12-deepseek-v4-pro-9db1291e.json |
| 2026-11-25 09:30 | lab research | ema PAXGUSDT-PERP.SIM (baseline) | walk-forward folds=6 cost=binance_vip0_bnb | -0.54% (+0.30% gross), 4/6 | -3.58% (vol -2.00%) | ❌ rejected | REJECT: breakeven 1.18 bps, exposure 91.71%, 150 fills — програє витратам |
| 2026-11-25 09:48 | lab research | H-GOLD-02 gold_session_orb PAXGUSDT-PERP.SIM | walk-forward folds=6 prereg=matched (ba70eef22316) | 0.00%, 0/6 | -3.58% | ❌ rejected | REJECT: 0 fills; денний max_box_atr [0.6..1.0] на 1h ATR відсіяв >99% днів |
| 2026-11-25 09:55 | lab research | pairs XAU-XAG PERP (OLS / Kalman) & PAXG-XAU (Kalman) | walk-forward folds=6 cost=binance_vip0_bnb | -0.38% / 0.00% / -0.06% | -3.97% / -3.97% / -3.51% | ❌ rejected | REJECT: OLS 40 fills BE=-3.84 bps; Kalman XAU-XAG 0 fills (ADF); PAXG-XAU 12 fills |
| 2026-11-25 10:02 | lab research | funding PAXG/USDT–PAXGUSDT-PERP | walk-forward folds=6 cost=binance_vip0_bnb | +0.10%, 2/6 (worst 0.00%) | -3.58% (vol -0.18%) | ❌ rejected | REJECT: позитивний BE=14.88 bps, але лише 8 fills < 30 і 2/6 прибуткових фолдів |
| 2026-11-25 10:05 | lab research | meta_label PAXGUSDT-PERP 13-feat vs 21-feat + stress_x1_5 + PBO | OOS folds=6 (<=2026-05-26 train) + days=180 PBO | +0.45% (13f) / +0.92% (21f) / +0.83% (stress) | -3.58% (vol -0.04%) | ❌ rejected | REJECT: 21f дає 13.73 bps BE і переживає stress_x1_5 (+0.83%), але 2/6 фолдів, PBO=0.4143, DSR=0.0223 |
| 2026-11-25 10:08 | lab research | H-GOLD-01 regime gold PAXGUSDT-PERP.SIM | walk-forward folds=6 prereg=matched (c384fe040eee) | +0.41% (+0.81% gross), 2/6 | -3.58% (vol -1.13%) | ❌ rejected | REJECT: 74 fills, BE=10.28 bps, beats vol_matched, але profitable 2/6 < 5/6 |
| 2026-11-25 10:14 | lab research | H-GOLD-02B gold_session_orb PAXGUSDT-PERP.SIM | walk-forward folds=6 prereg=matched (d945052f1f75) | -0.31% (-0.12% gross), 1/6 | -3.58% (vol +0.10%) | ❌ rejected | REJECT: 32 fills, BE=-11.88 bps; не перекриває комісій і програє vol_matched |
| 2026-11-25 10:18 | lab research | H-GOLD-02B gold_session_orb PAXGUSDT-PERP.SIM | PBO/CSCV blocks=8 configs=9 splits=70 | n/a | n/a | ❌ rejected | REJECT: PBO=0.5714 (>0.30), DSR=0.0555; жодна конфігурація не прибуткова |
| 2026-11-25 10:18 | lab research | H-GOLD-01 regime gold PAXGUSDT-PERP.SIM | PBO/CSCV blocks=8 configs=15 splits=70 | n/a | n/a | ❌ rejected | REJECT: PBO=0.5143 (>0.30), DSR=0.4219 (<0.95) попри позитивний mean block donchian>=60 |
| 2026-11-25 10:28 | lab research | H-GOLD-01 regime gold PAXGUSDT-PERP.SIM | walk-forward folds=6 stress_x1_5 | +0.21% (+0.81% gross), 2/6 | -3.58% (vol -1.14%) | ❌ rejected | REJECT: витримує 1.5x витрат (74 fills, BE=10.28 bps), але 2/6 фолдів |
| 2026-11-25 10:32 | lab research | H-GOLD-02B gold_session_orb PAXGUSDT-PERP.SIM | walk-forward folds=6 stress_x1_5 | -0.40% (-0.12% gross), 1/6 | -3.58% (vol +0.09%) | ❌ rejected | REJECT: 32 fills, BE=-11.88 bps |
| 2026-11-25 10:34 | lab research | H-GOLD-01 regime gold PAXG/USDT.SIM (gold_rates2022) | walk-forward folds=4 slice gold_rates2022 | -0.04% (+0.18% gross), 1/4 | +0.32% (vol -0.02%) | ❌ rejected | REJECT: 16 fills, BE=0.79 bps, мінімальний DD у циклі підвищення ставок ФРС |
| 2026-11-25 10:35 | lab research | H-GOLD-01 regime gold PAXGUSDT-PERP.SIM (gold_blowoff2026) | walk-forward folds=4 slice gold_blowoff2026 | +0.43% (+0.62% gross), 3/4 | -2.54% (vol -0.60%) | ❌ rejected | REJECT (slice folds=4<6): 30 fills, BE=18.35 bps, пережив спалах волатильності |
| 2026-11-25 10:36 | lab research | gold_session_orb PAXG/USDT.SIM (gold_rates2022) | walk-forward folds=4 slice gold_rates2022 | -0.35% (+0.17% gross), 2/4 | +0.32% (vol +0.37%) | ❌ rejected | REJECT: 34 fills, BE=1.57 bps < 7.5 bps спот-комісії |
| 2026-11-25 10:37 | lab research | gold_session_orb PAXGUSDT-PERP.SIM (gold_blowoff2026) | walk-forward folds=3 slice gold_blowoff2026 | -0.48% (-0.42% gross), 0/3 | -2.68% (vol -0.06%) | ❌ rejected | REJECT: 6 fills, BE=-42.40 bps |
| 2026-11-25 10:45 | lab research | gold_session_orb PAXG/USDT.SIM (6.25y multi-cycle) | walk-forward folds=3 2020..2026 (250 fills) | -2.29% (+2.43% gross), 0/3 | +13.48% (vol +3.57%) | ❌ rejected | REJECT: грос-edge (BE=3.46 bps) повністю з'їдається 7.5 bps спот-комісією |
| 2026-11-25 10:51 | lab research | H-GOLD-01 regime gold PAXG/USDT.SIM (4y multi-cycle) | walk-forward folds=2 days=1460 | +5.74% (+9.46% gross), 2/2 | +2.85% (vol +0.25%) | ❌ rejected | REJECT (folds=2<6): 150 fills, BE=17.60 bps; обидва фолди (+11.17% і +0.32% vs -26.26%) |
| 2026-11-25 12:04 | lab research | H-GOLD-01 regime XAUUSDT-PERP.SIM (1h) | walk-forward folds=6 prereg=not_registered | +0.71% (+0.94% gross), 4/6 | -3.50% (vol -0.91%) | ⏳ pending | 42 fills, BE=26.78 bps (>5x витрат), перемагає vol_matched; історія <2y (лише execution check) |
| 2026-11-25 12:11 | lab research | H-GOLD-4H-01 regime PAXG/USDT.SIM (4h 6.25y) | walk-forward folds=6 prereg=matched (93d8c06721a4) | +0.55% (+1.03% gross), 4/6 | +5.82% (vol +1.06%) | ❌ rejected | REJECT: 118 fills, BE=12.12 bps, beats_vol_matched=fail (0.55%<1.06% через 15 bps спот-RT і 18.6% exposure) |
| 2026-11-25 12:21 | lab research | H-GOLD-4H-01 regime PAXG/USDT.SIM (4h 6.25y) | PBO/CSCV blocks=8 configs=15 splits=70 | n/a | n/a | ❌ rejected | PBO=0.0571 (PASS <=0.30 — вибір donchian>=40 узагальнюється!), але DSR=0.1024 (<0.95) |
| 2026-11-25 12:23 | lab research | ema PAXG/USDT.SIM (4h 6.25y) | walk-forward folds=6 + PBO/CSCV blocks=8 | +4.17% (+4.97% gross), 4/6 | +5.82% (vol +3.72%) | ❌ rejected | REJECT: BE=71.84 bps, але PBO=0.7286 (>0.50 — сильне перенавчання!) і DSR=0.4712 |
| 2026-11-25 12:38 | lab research | gold_session_orb XAUUSDT-PERP.SIM (1h) | walk-forward folds=6 cost=binance_vip0_bnb | -0.14% (-0.02% gross), 1/6 | -3.50% (vol -0.12%) | ❌ rejected | REJECT: 20 fills < 30, BE=-18.49 bps, програє vol_matched |
<!-- journal:rows:end -->

**Як це працює.** Рядки між маркерами `journal:rows:start` і `journal:rows:end`
автоматично дописує CLI:

```bash
uv run lab research --robot regime --folds 4 --journal
uv run lab propose --count 5 --journal
```

Скрипт **лише дописує** нові рядки перед кінцевим маркером: існуючі він ніколи не
переписує, тому твоє рішення в старому рядку переживе наступний прогін. Маркери
видаляти не можна — без них запис падає з помилкою, а не вгадує місце.

Поруч лежить `journal.jsonl` — машинний лог тих самих прогонів (по одному JSON на
рядок, з полями `artifact`, `fills`, `gates`). Він теж тільки дописується.

Легенда рішень: `⏳ pending` — на рев'ю · `✅ accepted` — прийнято в `domain/` ·
`❌ rejected` — відкинуто · `🔁 rerun` — потрібен повторний прогін (артефакт неповний).

## Що фіксувати обов'язково

- **Джерело**: який промпт і яка модель дали ідею (або «людина», або «стаття»).
- **Ворота**: purged K-fold, walk-forward OOS з `--folds N`, PBO/CSCV, чи кілька одразу.
- **OOS і buy&hold** за той самий період — інакше число нічого не означає.
- **Причину відмови**: немає механізму / вигадана фіча / не подолало планку /
  мало угод для висновку / занадто чутливе до параметрів.

## Приклад запису про модельно-запропоновану ідею

```
2026-09-15 · prompts/01-generate-alphas.md · deepseek-chat · as_of 2026-09-15
Гіпотеза: volume-climax reversal (horizon 5, sign -1)
Формула: -reversal_3 * zscore(volume_ratio)   ← усі імена з FEATURE_NAMES
purged CV (5 фолдів, embargo 10): accuracy 34.2% (база flat ≈ 41%) → нижче бази
Рішення: ❌ rejected
Причина: сигнал не відрізняє напрямок; механізм правдоподібний, але на 1h-барах
ETH/USDT не видно. У walk-forward не пускали — немає сенсу витрачати OOS.
```

Запис про **відкинуту** ідею не менш цінний за запис про прийняту.
