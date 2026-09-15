# Deployment / context: що крутиться і куди ходить дані

Це **локальна дослідницька пісочниця**, не торговий кластер. Немає WebSocket, колокації
і live-брокера.

```mermaid
flowchart TB
    subgraph workstation["Робоча станція дослідника"]
        cli["процес: uv run lab"]
        env["файл .env локальний"]
        src["пакет nautilus_lab"]
        catalog["тека catalog/ Parquet"]
        reports["тека reports/ HTML tearsheet"]
        tests["pytest без мережі в unit"]
    end

    subgraph optional["Опційні extras"]
        optuna["optuna TPE"]
        lgbm["LightGBM"]
        plotly["plotly tearsheet"]
        httpx["httpx алерти"]
        arch["arch EGARCH"]
    end

    subgraph external["Зовнішній світ"]
        binance["Binance публічний REST<br/>klines / funding без ключів"]
        telegram["Telegram Bot API"]
        webhook["довільний Webhook"]
    end

    cli --> src
    cli --> env
    src --> catalog
    src --> reports
    src --> optuna
    src --> lgbm
    src --> plotly
    src -.->|"лише ingest"| binance
    src -.->|"лише --notify"| telegram
    src -.->|"лише --notify"| webhook
    tests --> src
```

Пунктир — мережа. Типовий `lab research` після ingest **не ходить в інтернет**: читає каталог.

## Контекст системи (C4-подібний)

```mermaid
flowchart LR
    user["Дослідник"] --> lab["nautilus-lab CLI"]
    lab --> nt["NautilusTrader BacktestEngine"]
    lab --> fs["Локальний Parquet catalog"]
    lab --> binance["Binance public market data"]
    lab --> notify["Alerts Telegram/Webhook"]
    nt --> sim["Venue SIM<br/>NETTING, MARGIN, 1x<br/>FillModel slippage 0.25<br/>LatencyModel 50 ms"]
```

Інструменти симуляції: `ETH/USDT.SIM`, `BTC/USDT.SIM`, `ETHUSDT-PERP.SIM`.

## Потік даних (pipeline)

```mermaid
flowchart LR
    kline["Binance kline JSON"] --> parse["parse_binance_kline"]
    parse --> bar["OhlcvBar Decimal UTC"]
    bar --> validate["validate_bar"]
    validate --> parquet["ParquetDataCatalog"]
    parquet --> feed["ResearchBarFeed.load"]
    synth["synthetic_ohlcv"] --> feed
    feed --> convert["to_engine_bars"]
    convert --> engine["BacktestEngine"]
    engine --> native["нативний Bar"]
    native --> adapter["SignalRobot / SpreadRobot"]
    adapter --> domainBar["знову OhlcvBar"]
    domainBar --> signal["Signal / SpreadSignal"]
    signal --> risk["risk size + breakers"]
    risk --> order["Market order SIM"]
    order --> fills["fills / positions"]
    fills --> metrics["compute_metrics"]
    metrics --> report["BacktestReport / консоль / tearsheet"]
```

Гроші скрізь `Decimal`. Індикатори бачать лише **закритий** бар (`RollingWindow.prior()`),
щоб не було look-ahead.

## Щого немає в деплої (навмисно)

- ключів API біржі в git / обов'язковому `.env`;
- процесу live-виконання;
- спільної БД — стан дослідження в каталозі й звітах;
- окремого API-сервера — лише CLI `lab`.
