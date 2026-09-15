# Sequence: що відбувається в часі

Три головні ланцюги: завантаження даних, walk-forward дослідження, один бар у рушії.

## 1. `lab ingest`

```mermaid
sequenceDiagram
    actor User as Дослідник
    participant CLI as cli.main
    participant Comp as composition
    participant UC as IngestHistoricalBars
    participant Feed as BinancePublicKlines
    participant Cat as NautilusParquetCatalog

    User->>CLI: lab ingest --start ... --symbols ETHUSDT
    CLI->>Comp: settings() / ingest_use_case() / ingest_request()
    Comp->>UC: IngestHistoricalBars(feed, catalog)
    CLI->>UC: execute(IngestRequest)
    UC->>UC: require_simulated_mode(mode)
    UC->>Feed: fetch(symbol, interval, start, end)
    Feed-->>UC: list[OhlcvBar]
    alt порожня відповідь
        UC-->>CLI: CatalogEmptyError
    else є бари
        UC->>Cat: write(bars, bar_type, instrument_id)
        Note over Cat: delete_data_range потім запис
        Cat-->>UC: bars_written
        UC-->>CLI: IngestReport
        CLI-->>User: wrote=N first=... last=...
    end
```

Ключі біржі не потрібні: лише публічний REST `/api/v3/klines`.

## 2. `lab research` (типовий walk-forward)

```mermaid
sequenceDiagram
    actor User as Дослідник
    participant CLI as cli.main
    participant Comp as composition
    participant WF as RunWalkForward
    participant Feed as ResearchBarFeed
    participant Split as walk_forward.split
    participant Grid as param_grid / Optuna
    participant Eng as NautilusResearchBacktest
    participant Score as in_sample_score

    User->>CLI: lab research --robot regime
    CLI->>Comp: walk_forward_request / walk_forward_use_case
    Comp->>WF: RunWalkForward(engine, feed)
    CLI->>WF: execute(WalkForwardRequest)
    WF->>WF: require_simulated_mode + require_backtest_support
    WF->>Feed: load(BacktestRequest)
    Feed-->>WF: list[OhlcvBar]
    WF->>Split: anchored_window + split_by_window
    Note over Split: IS ... embargo ... OOS
    Split-->>WF: in_sample, out_of_sample

    loop кожен кандидат IS
        WF->>Grid: наступні SelectedParams
        WF->>Eng: run(candidate, IS bars)
        Eng-->>WF: BacktestReport
        WF->>Score: ending_balance
    end

    WF->>Eng: run(best, OOS bars) один раз
    Eng-->>WF: out_of_sample report
    WF-->>CLI: WalkForwardReport
    CLI-->>User: IS окремо, OOS окремо
```

OOS-бари **ніколи** не потрапляють у цикл підбору. `--folds N` (N ≥ 2) повторює цей цикл
на кожному ковзному вікні й агрегує OOS у `MultiWindowReport`.

Для `pairs` замість `load` / `run` викликаються `load_multi` / `run_spread`.

## 3. Один закритий бар у `SignalRobot`

```mermaid
sequenceDiagram
    participant Eng as BacktestEngine
    participant SR as SignalRobot
    participant Val as validate_bar
    participant Robot as RegimeRouter / EmaCrossover / ...
    participant Risk as evaluate_entry
    participant Size as size_position
    participant OMS as order_factory

    Eng->>SR: on_bar(native Bar)
    SR->>SR: to_domain OhlcvBar
    SR->>Val: validate_bar UTC / OHLC / monotonic
    SR->>SR: ATR.update + HAR.update
    SR->>Robot: on_bar(domain bar)
    Robot-->>SR: Signal or None

    alt немає сигналу
        SR-->>Eng: return
    else side = FLAT
        SR->>OMS: close_all_positions
    else BUY або SELL
        SR->>Risk: evaluate_entry(AccountSnapshot, limits, overlay)
        alt allowed = false
            SR-->>Eng: лог, без ордера
        else allowed
            SR->>Size: stop_distance + resolve_risk_fraction + size_position
            alt qty = 0 або вже в потрібному боці
                SR-->>Eng: skip
            else
                SR->>OMS: flatten якщо є позиція
                SR->>OMS: market order + submit_order
            end
        end
    end
```

Fail-closed: немає equity в кеші, `qty == 0`, спрацював circuit breaker — ордера немає.

## 4. `lab live` (негативний сценарій)

```mermaid
sequenceDiagram
    actor User as Дослідник
    participant CLI as cli.main
    participant Risk as require_simulated_mode

    User->>CLI: lab live
    CLI->>Risk: require_simulated_mode(LIVE)
    Risk-->>CLI: LiveTradingDisabledError
    CLI-->>User: stderr + exit 1
```

Адаптера виконання на біржі в репозиторії немає: навіть виклик use case в обхід CLI
не надішле живий ордер.
