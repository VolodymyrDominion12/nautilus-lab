# Nautilus Lab — dashboard (frontend)

React + TypeScript + Vite UI for the `lab` research lab. It drives the FastAPI app in
`src/nautilus_lab/api/`, which in turn calls the same use cases the CLI uses.

## Running it

Two processes. The API must be up first — the UI has no data of its own.

```bash
# terminal 1 — API on :8000
.venv/bin/uvicorn nautilus_lab.api.app:app --port 8000

# terminal 2 — UI on :5173
cd frontend && npm install && npm run dev
```

`VITE_API_URL` (see `.env.example`) overrides the API base; it defaults to
`http://localhost:8000`.

If `npm run dev` dies with `ENOSPC: System limit for number of file watchers reached`, the
machine has exhausted inotify watches (IDEs consume them). `npm run build && npx vite preview`
serves the same app without a file watcher.

## Checks

```bash
npm run build        # tsc -b (includes noUnusedLocals) + vite build
npm run lint         # oxlint
npm test             # vitest: every src/**/*.test.ts
npm run check:logic  # only the research-discipline rules, see below
npm run e2e          # Playwright smoke: built dashboard + real API on synthetic markets
```

Unit tests live next to the module they cover (`src/lib/*.test.ts`) and run under vitest in
Node; `tsc -b` typechecks them with the rest of `src`, so a test cannot drift from the types.

- `research-logic.test.ts` covers the two pure modules the dashboard's honesty depends on:
  `preflight()` (runs the backend is known to reject, so a wall of traceback is replaced by a
  button that will not start) and `verdictFor()` (which refuses to read an in-sample number as a
  result). It replaces the old `scripts/check-research-logic.ts` assertion script.
- `format.test.ts` pins the rule every result panel shares: an unmeasured number (`null`, `''`,
  `NaN`) comes out as "n/a" / neutral / unknown, never as a zero that reads like a result.

### Browser smoke test

`npm run e2e` starts two servers and drives Chromium through `e2e/smoke.e2e.ts`:

- the API, `scripts/e2e_server.py` on :8765: the real `create_app`, with Binance replaced by
  synthetic 1m bars (one closed bar per second, no network, keys or journal);
- the dashboard as it ships (`vite build` into `dist-e2e/`, then `vite preview` on :4173), built
  with `VITE_API_URL` pointing at that API.

It checks that the dashboard reads `/api/status` through CORS and the origin gate, that a
started paper session shows in the sessions table, that its WebSocket reports "Stream Active",
and that new bars keep arriving. It also fails on any uncaught page error. Setup, once:

```bash
npm i -D @playwright/test
npx playwright install chromium   # add --with-deps on a fresh Linux machine
```

The API side has its own `pytest` (`tests/unit/test_e2e_server.py`), so a change that breaks
the synthetic sessions fails there first, with a Python traceback.

## Tabs

| Tab | What it does |
|-----|--------------|
| **Command Center** (`home`) | Live job states with elapsed time, the last measured result with its verdict, data coverage per instrument (bars, taker flow, ticks, depth, funding), recent experiments, journal counts, trained models. |
| **Research & Backtest** (`research`) | The core flow: pick a robot and instrument, choose the walk-forward window on a chart, run, then read the result panels. The advanced gates include the bar-level VPIN, tick-level VPIN and Hawkes filters. |
| **Parquet Catalog** (`catalog`) | Per-instrument coverage and fees, a per-series table, price preview, and four Binance ingest kinds (klines, aggregated trades, funding, live L2 depth) with a stop button. |
| **Strategy Specs** (`strategies`) | `specs/strategies/*.yaml` as validated: wiring, warm-up bars, `grid_source`. |
| **ML Pipeline** (`ml`) | LightGBM training with purged CV, model inventory. |
| **Experiment Journal** (`journal`) | `research/journal.jsonl` as a board; each row shows the gates it was run under. |
| **Trading Terminal** (`paper`) | Batch paper replay (`PaperSimulator`), the live multi-session table (`SessionsPanel`) and the live terminal with chart and stops (`LiveTradingTerminal`). Hypothetical orders only — no execution adapter exists. |
| **Arb Scanner** (`scan`) | Triangular-arbitrage scan over sample rates; demonstration only. |
| **Alpha Ideas** (`alpha`) | `lab propose` artifacts from `research/hypotheses/`, with a "test in research" hand-off. |
| **Settings** (`settings`) | Grouped `.env` settings; secrets are masked on load. |

## Threads behind the Trading Terminal

The terminal is the most stateful screen, and it does **not** reuse the batch paper
runner. Three layers, all in `src/nautilus_lab/api/`:

- **`market_feed.py` / `binance_ws.py`** — one public WebSocket subscription per
  `(symbol, interval)` pair, shared between sessions: two robots on ETH 1h read the
  same candles, which saves Binance limits and keeps the comparison honest.
- **`paper_streamer.py`** — warms each session up with `WARMUP_BARS = 300` replayed
  closed bars (a cold regime robot would sit silent for hours on 1m), then feeds live
  closed candles. Live robots are a shorter list than the backtest-wired set:
  `regime`, `ema`, `adaptive_ema`, `vpin_momentum`, `formulaic_lgbm` plus a `hold`
  benchmark — the spread robot `pairs` and the OBI/meta-label robots need data the
  live path does not assemble.
- **`live_sessions.py` + `infrastructure/paper_sessions.py`** — the session registry,
  per-session virtual ledger, portfolio file and restart recovery (`LIVE_PAPER_*`
  settings). `LAB_ROLE=paper` restricts a deployed server to these routes only.

The browser follows it over `GET /api/paper/live-stream` (WebSocket).

## What the UI refuses to do (on purpose)

These are the project's research rules expressed in the interface. They are not
customisable, because a dashboard that lets you skip them is how a lab starts lying to itself.

- **In-sample is never presented as a result.** Every result carries an evidence badge:
  `out-of-sample (report this)`, `in-sample only (selection only)`, or
  `overfitting audit (no PnL verdict)`.
- **Buy&hold is the bar.** Win or lose, the out-of-sample mean is shown next to simply holding
  the instrument over the same windows, alongside per-fold bars so one lucky window cannot
  masquerade as an edge.
- **Unmeasured is `n/a`, never `0`.** A fold with no fills has no breakeven and no verdict
  (`beats_buy_and_hold: null`), and the UI says so rather than rounding it into a win or a loss.
- **A negative breakeven cost is stated as such** — the run loses money before fees, so cheaper
  execution would not have saved it.
- **Fail-closed runs are blocked before they start.** `preflight()` refuses robots with no
  backtest adapter, full-sample combined with Optuna, multi-window runs with explicit dates, and
  splits whose legs are shorter than the robot's warm-up.
- **A tick-level filter is never accepted without ticks.** The tick VPIN and Hawkes filters are
  refused (blocked error, and HTTP 400 from the API) on a robot that ignores them, on synthetic
  bars, and on a catalog whose aggregated-trade series is missing — the engine reads a missing
  series as an empty one, so the filter would run on its defaults while the run carried its name.
- **A missing optional series is reported, not hidden.** The catalog and command-center tables
  show taker flow / ticks / depth / funding as present or `missing` for every instrument, because
  "the run finished" is not evidence that the data behind a filter existed.
- **Live trading is unreachable.** There is no execution adapter; `lab live` exits 1 by design.
- **Paper mode offers only the robots the running path can build.** The batch simulator
  takes `status.paper_robots` (which equals `BACKTEST_WIRED_ROBOTS`), the live terminal
  takes `status.live_paper_robots` (the shorter live list, plus `hold`). Anything else
  would silently run a different robot while the artifact recorded the requested name.

## Behaviour worth knowing

- **Per-run parameter overrides are opt-in.** A run uses the values from the Settings tab unless
  "Override robot parameters for this run" is switched on. The earlier behaviour always sent spec
  defaults, which silently shadowed the saved settings.
- **The form is remembered** in `localStorage` (`nautilus-lab:research-form:v2`), so a reload does
  not quietly change the research conditions. "Reset form" clears it.
- **A refused launch is surfaced.** The API answers HTTP 200 with `status: "error"` when a job of
  the same kind is running; the UI shows that message instead of spinning while a previous run's
  numbers are on screen.
- **Results older than the launch are labelled stale**, and a job that dies before writing its
  artifact stops the spinner instead of polling forever.
- **The window chart is the real split.** The amber band is the parameter-selection leg, the
  green band is the reported forecast, and the boundary is derived from the bar count
  (`floor(total * is_fraction)`), the same rule the engine uses.
- **"Copy CLI" only emits real flags.** The command is built by `cliCommand()` from the flags in
  `interfaces/cli.py`; the instrument travels as `INSTRUMENT_ID` because there is no
  `--instrument` flag to pass it through.
- **Tearsheets are ~4 MB each**; the viewer lists the newest few with their size.
