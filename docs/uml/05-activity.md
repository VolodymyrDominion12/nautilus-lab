# Activity: розгалуження сценаріїв

## `lab research` від аргументів CLI до звіту

```mermaid
flowchart TD
    start([lab research]) --> parse[Розбір аргументів і Settings]
    parse --> foldsCheck{folds >= 1?}
    foldsCheck -->|ні| errFolds[ValueError код 1]
    foldsCheck -->|так| synth{--synthetic?}

    synth -->|так| synthWf{walk-forward / optuna / folds > 1?}
    synthWf -->|ні| fullSynth[RunResearchBacktest на синтетиці]
    synthWf -->|так| wfPath[RunWalkForward]

    synth -->|ні| catalogPath{--full-sample?}
    catalogPath -->|так| fullCat[RunResearchBacktest на каталозі<br/>позначка in-sample only]
    catalogPath -->|ні| wfPath

    wfPath --> multi{folds > 1?}
    multi -->|так| execMulti[execute_multi: N ковзних фолдів]
    multi -->|ні| execOne[execute: один anchored split]
    execMulti --> printMulti[Друк агрегату OOS + buy and hold]
    execOne --> printWf[Друк IS окремо, OOS окремо]
    fullSynth --> printBt[Друк fills / ending / metrics]
    fullCat --> printBt

    printMulti --> notify{--notify?}
    printWf --> notify
    printBt --> notify
    notify -->|так| alert[AlertNotifier]
    notify -->|ні| done([код 0])
    alert --> done
    errFolds --> fail([код 1])
```

Помилки `LiveTradingDisabledError`, `CatalogEmptyError`, `InvalidWindowError`,
`RobotNotWiredError` / `ValueError` друкуються в stderr і дають код 1.

## Цикл дослідження (методологія)

Відповідає [04-tsykl-doslidzhennya.md](../04-tsykl-doslidzhennya.md).

```mermaid
flowchart TD
    prep[Підготовка .env + smoke --synthetic] --> ingest[ingest історії]
    ingest --> sanity[Перевірка каталогу]
    sanity --> baseline[Walk-forward простої стратегії]
    baseline --> main[Walk-forward цільового робота]
    main --> multi[За бажанням --folds 4]
    multi --> read[Читати лише OOS як звіт]
    read --> stress[Стрес-слайси covid2020 / ftx2022 / etf2024]
    stress --> sensitivity[Embargo, IS-частка, VPIN]
    sensitivity --> verdict{OOS стабільно кращий за buy and hold?}
    verdict -->|ні| reject[Не брати в роботу]
    verdict -->|так| journal[Записати параметри й обмеження]
```

In-sample баланс — лише для **вибору** параметрів, не для висновку.

## Підбір параметрів на одному вікні

```mermaid
flowchart TD
    bars[IS-бари] --> method{use_optuna?}
    method -->|ні| grid[iter_param_grid: невелика сітка]
    method -->|так| tpe[Optuna TPE, --trials N]
    grid --> runIS[engine.run на IS]
    tpe --> runIS
    runIS --> score[in_sample_score = ending_balance]
    score --> more{ще кандидати?}
    more -->|так| runIS
    more -->|ні| best[Найкращі SelectedParams]
    best --> oos[Один engine.run на OOS]
    oos --> report[WalkForwardReport]
```
