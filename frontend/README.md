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
npm run check:logic  # research-discipline rules, see below
```

`check:logic` runs `scripts/check-research-logic.ts` through `jiti`. It covers the two pure
modules the dashboard's honesty depends on: `preflight()` (which runs the backend is known to
reject, so a wall of traceback is replaced by a button that will not start) and `verdictFor()`
(which refuses to read an in-sample number as a result). The project has no frontend test
runner, so these run as assertions in a script.

## Tabs

| Tab | What it does |
|-----|--------------|
| **Command Center** | Live job states with elapsed time, the last measured result with its verdict, recent experiments, journal counts, trained models. |
| **Research & Backtest** | The core flow: pick a robot and instrument, choose the walk-forward window on a chart, run, then read the result panels. |
| **Parquet Catalog** | Per-instrument coverage and fees, price preview, Binance ingest with a stop button. |
| **Strategy Specs** | `specs/strategies/*.yaml` as validated: wiring, warm-up bars, `grid_source`. |
| **ML Pipeline** | LightGBM training with purged CV, model inventory. |
| **Experiment Journal** | `research/journal.jsonl` as a board; each row shows the gates it was run under. |
| **Paper Simulator** | Hypothetical orders only — no execution adapter exists. |
| **Settings** | Grouped `.env` settings; secrets are masked on load. |

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
- **Live trading is unreachable.** There is no execution adapter; `lab live` exits 1 by design.
- **Paper mode offers only the robots it can build** (`regime`, `ema`). Anything else would
  silently run the regime robot while the artifact recorded a different name.

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
- **Tearsheets are ~4 MB each**; the viewer lists the newest few with their size.
