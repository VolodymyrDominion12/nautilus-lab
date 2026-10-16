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
