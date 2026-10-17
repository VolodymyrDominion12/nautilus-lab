# research/experiments — рецепти батчів

Кожен файл — тіло `POST /api/batches` (те саме, що форма «Батч» на дашборді):

```bash
curl -s -X POST localhost:8000/api/batches -H 'content-type: application/json' \
  -d @research/experiments/p1_regime_4h_fixed.json            # запуск
jq '.dry_run=true' research/experiments/p1_regime_4h_fixed.json \
  | curl -s -X POST localhost:8000/api/batches -H 'content-type: application/json' -d @-   # лише план
```

## p1_regime_4h_fixed.json (план 16.10, крок P1)

regime 4h, 11 монет (MATIC без даних після 2024-09-10 — план його блокує), 2200 днів,
12 фолдів, `is_fraction=0.5` → IS ≈ 1100 днів, OOS ≈ 12 × 92 дні (≈ 2023-09 → 2026-10).

| Варіант | Що | Порівнюємо з |
|---|---|---|
| R0_grid | як у батчі 13.10: сітка donchian × bb_k, усі ноги | точка відліку |
| R1_fixed40 | без IS-пошуку, donchian 40, без range-ноги | R0 — чи сітка щось дає |
| R3_fixed40_gt | R1 + ворота глобального тренду (1d SMA200) | R1 |
| R4_fixed40_long | R1 лише лонги (як можна торгувати на споті) | R1 — внесок шортів |

Спот, комісія 7.5 bps, шорти без вартості позики — R4 показує, що лишається без них.
Варіант на перпах (R2 у плані) — окремим рецептом, коли `catalog_perp_4h` має funding.
Вирішальний бенчмарк — vol-matched buy&hold (гейт з 16.10 показує сирий buy&hold як `info`).

## p1_regime_4h_perp.json (R2)

Те саме, що R1/R3/R4, але на USDⓈ-M перпах (`"market": "perp"`, `catalog_perp_4h`, профіль
`binance_vip0_bnb` → taker 5 bps). 10 монет: перп-барів LTC у каталозі немає, MATIC
закінчується 2024-09. Кінець даних перпів — 2026-10-03.

Funding у самому бектесті не нараховується (його моделює лише робот `funding`), тому summary
клітинки віднімає його постфактум: `breakdown.funding` / `net_after_funding` /
`funding_by_fold` і `numbers.mean_oos_after_funding`. Порівнювати R2 з R1 — саме за цим
числом. Funding до кінця 2023 у Binance без mark price → там номінал рахується за ціною входу.

## Преєстрація

Обидва рецепти мають `hypothesis` (батчу і кожного варіанта). Кожна клітинка пише свої
умови в `research/preregistrations/` **до** першого бектесту (`preregister` у її config.json),
тож гейт може показати `preregistered=pass`. Без `hypothesis` клітинка — exploratory і
`preregistered=not measured`. Змінив рецепт після запуску → нова гіпотеза, нова спроба.

## Портфель

Після батчу: `uv run python scripts/portfolio_replay.py reports/batches/<id> --variant R1_fixed40
--heat 0.03 --per-side 4 --target-vol 0.12` — угоди всіх монет на одному рахунку з лімітами.
Працює й на старих батчах (угоди відновлюються з decision-логів, без funding).

## p1_regime_4h_ensemble.json (план 16.10, ансамбль каналів + фільтр волатильності)

Ті самі вікна, що й p1_regime_4h_fixed (2200 днів, 12 фолдів, IS 0.5), 4 спроби:

| Варіант | Що |
|---|---|
| E20 / E40 / E90 | donchian 20 / 40 / 90 без IS-пошуку, без range-ноги — підсистеми ансамблю |
| E40_vol | E40 + `ENTRY_FILTER_VOL_EXPANSION` (знахідка батчу 20261016_094231, тут — преєстрована перевірка) |

Ансамбль не окремий робот, а три підсистеми на одному рахунку, кожна з 1/3 ризику:

```bash
uv run python scripts/portfolio_replay.py reports/batches/<id> --variant E20,E40,E90 --risk 0.00167
uv run python scripts/portfolio_replay.py reports/batches/<id> --variant E40 --risk 0.005
```

Ліміт на бік рахує монету один раз, хоч би скільки підсистем її тримало. Гіпотеза: Sharpe
денних прибутків ансамблю вищий, ніж E40 з тим самим сумарним ризиком, а MaxDD не гірший.

Угоди, які walk-forward закрив кінцем фолду, з 17.10 є в `trades.jsonl` з причиною
`FOLD_END` (SUMMARY_VERSION 6); без них угоди не сходились із доходністю фолдів.
