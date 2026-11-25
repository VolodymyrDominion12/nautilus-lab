# Лідерборд бектестів (Backtest Leaderboard)

Таблиця найкращих перевірених бектестів за результатами Out-of-Sample (OOS).
Кожен запис містить стратегію, інструмент, таймфрейм, кількість свічок, усі параметри
запуску та готову CLI-команду для 100% точного відтворення.

## Правила включення
- **In-sample — лише вибір, OOS — це звіт**: оцінка базується на out-of-sample або агрегаті фолдів.
- **Порівняння з Buy & Hold**: excess return відображає альфу над пасивним утриманням.
- **Повна відтворюваність**: точні аргументи та зафіксована команда запуску.

| # | Стратегія | Інструмент | ТФ | Свічки | OOS Return | Buy&Hold | Excess | Max DD | Fills | Аргументи | Команда для відтворення |
|---|---|---|---|---|---|---|---|---|---|---|---|
<!-- leaderboard:rows:start -->
| 1 | `regime` | `ETH/USDT.SIM` | `1h` | 12486 | **+10.16%** | +34.64% | -24.48% | n/a | 188 | bb_k=3, bb_period=120, donchian_period=120, enter_trend_er=0.30, exit_trend_e... | `BB_K=3 BB_PERIOD=120 DONCHIAN_PERIOD=120 ENTER_TREND_ER=0.30 EXIT_TREND_ER=0.20 FAST_EMA=10 SLOW_EMA=20 uv run lab research --robot regime --instrument ETH/USDT.SIM --interval 1h --folds 2` |
| 2 | `ema` | `ETH/USDT.SIM` | `1h` | 12486 | **+9.57%** | +34.64% | -25.07% | n/a | 546 | ema_min_spread_pct=0.003, fast_ema=10, slow_ema=40 | `EMA_MIN_SPREAD_PCT=0.003 FAST_EMA=10 SLOW_EMA=40 uv run lab research --robot ema --instrument ETH/USDT.SIM --interval 1h --folds 2` |
| 3 | `regime` | `PAXG/USDT.SIM` | `4h` | 4094 | **+0.55%** | +5.82% | -5.27% | n/a | 118 | bb_k=3, bb_period=40, donchian_period=40, enter_trend_er=0.30, exit_trend_er=... | `BB_K=3 BB_PERIOD=40 DONCHIAN_PERIOD=40 ENTER_TREND_ER=0.30 EXIT_TREND_ER=0.20 FAST_EMA=10 SLOW_EMA=20 uv run lab research --robot regime --catalog catalog_gold_4h --instrument PAXG/USDT.SIM --interval 4h --folds 6` |
| 4 | `regime` | `PAXGUSDT-PERP.SIM` | `1h` | 4368 | **+0.41%** | -3.58% | +3.99% | n/a | 74 | bb_k=3, bb_period=120, donchian_period=120, enter_trend_er=0.30, exit_trend_e... | `BB_K=3 BB_PERIOD=120 DONCHIAN_PERIOD=120 ENTER_TREND_ER=0.30 EXIT_TREND_ER=0.20 FAST_EMA=10 SLOW_EMA=20 uv run lab research --robot regime --catalog catalog_gold_1h --instrument PAXGUSDT-PERP.SIM --interval 1h --folds 6` |
| 5 | `regime` | `PAXGUSDT-PERP.SIM` | `1h` | 4368 | **+0.21%** | -3.58% | +3.79% | n/a | 74 | bb_k=3, bb_period=120, donchian_period=120, enter_trend_er=0.30, exit_trend_e... | `BB_K=3 BB_PERIOD=120 DONCHIAN_PERIOD=120 ENTER_TREND_ER=0.30 EXIT_TREND_ER=0.20 FAST_EMA=10 SLOW_EMA=20 uv run lab research --robot regime --catalog catalog_gold_1h --instrument PAXGUSDT-PERP.SIM --interval 1h --folds 6` |
| 6 | `gold_session_orb` | `PAXGUSDT-PERP.SIM` | `1h` | 4368 | **0.00%** | -3.58% | +3.58% | n/a | 0 | gold_orb_buffer_atr=0.0, gold_orb_max_box_atr=1.0 | `GOLD_ORB_BUFFER_ATR=0.0 GOLD_ORB_MAX_BOX_ATR=1.0 uv run lab research --robot gold_session_orb --catalog catalog_gold_1h --instrument PAXGUSDT-PERP.SIM --interval 1h --folds 6` |
| 7 | `gold_session_orb` | `PAXGUSDT-PERP.SIM` | `1h` | 4368 | **-0.31%** | -3.58% | +3.28% | n/a | 32 | gold_orb_buffer_atr=0.30, gold_orb_max_box_atr=2.5 | `GOLD_ORB_BUFFER_ATR=0.30 GOLD_ORB_MAX_BOX_ATR=2.5 uv run lab research --robot gold_session_orb --catalog catalog_gold_1h --instrument PAXGUSDT-PERP.SIM --interval 1h --folds 6` |
| 8 | `gold_session_orb` | `PAXGUSDT-PERP.SIM` | `1h` | 4368 | **-0.40%** | -3.58% | +3.18% | n/a | 32 | gold_orb_buffer_atr=0.30, gold_orb_max_box_atr=2.5 | `GOLD_ORB_BUFFER_ATR=0.30 GOLD_ORB_MAX_BOX_ATR=2.5 uv run lab research --robot gold_session_orb --catalog catalog_gold_1h --instrument PAXGUSDT-PERP.SIM --interval 1h --folds 6` |
<!-- leaderboard:rows:end -->

## Як запустити відтворення
Щоб повторити будь-який бектест з таблиці, скопіюйте команду з останньої колонки або скористайтеся CLI:
```bash
uv run lab leaderboard --reproduce 1   # показати повну інструкцію відтворення топ-1
uv run lab leaderboard                 # переглянути таблицю в терміналі
```

Також можна додати новий бектест до лідерборду прапорцем `--leaderboard`:
```bash
uv run lab research --robot regime --folds 4 --leaderboard
```
