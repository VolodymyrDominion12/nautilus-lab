/**
 * Logic checks for the research discipline rules the dashboard enforces in the UI.
 *
 * These live in a script rather than a test runner because the project has no frontend test
 * setup, and the rules they cover are exactly the ones that must not silently regress:
 * a preflight that stops an impossible run, and a verdict that refuses to read an in-sample
 * number as a result. Run with `npm run check:logic`.
 */

import { formatBps, formatPct, toneOf } from '../src/lib/format';
import {
  cliCommand,
  foldLayout,
  fractionBoundaries,
  preflight,
  sliceOverlapsCatalog,
  verdictFor,
} from '../src/lib/research';
import type { ResearchSummary, StrategySpec } from '../src/services/api';

let failures = 0;

const check = (name: string, condition: boolean, detail = ''): void => {
  if (condition) {
    console.log(`  ok   ${name}`);
    return;
  }
  failures += 1;
  console.error(`  FAIL ${name}${detail ? ` — ${detail}` : ''}`);
};

const spec = (overrides: Partial<StrategySpec> = {}): StrategySpec => ({
  name: 'regime',
  domain_module: 'domain/regime_router.py',
  strategy_class: 'RegimeRouter',
  wired_in_backtest: true,
  minimum_bars: 150,
  grid_source: 'default_branch',
  status: 'candidate',
  summary: '',
  params: [],
  ...overrides,
});

const baseInput = {
  robot: 'regime',
  spec: spec(),
  source: 'catalog' as const,
  totalBars: 20000,
  syntheticBars: 3000,
  folds: 2,
  isFraction: 0.7,
  embargoBars: 10,
  fullSample: false,
  useOptuna: false,
  pbo: false,
  windowMode: 'fraction' as const,
  isStart: '',
  isEnd: '',
  oosStart: '',
  oosEnd: '',
  instrument: {
    instrument_id: 'ETH/USDT.SIM',
    raw_symbol: 'ETH/USDT',
    bars_count: 20000,
    first_date: '2024-01-01T00:00:00+00:00',
    last_date: '2026-04-01T00:00:00+00:00',
    quote_currency: 'USDT',
    maker_fee: 0.0002,
    taker_fee: 0.0005,
  },
  catalogInstruments: 1,
};

const errorsOf = (input: Parameters<typeof preflight>[0]) =>
  preflight(input)
    .filter((issue) => issue.level === 'error')
    .map((issue) => issue.message);

console.log('foldLayout — must mirror floor(total * is_fraction) and per_fold division');
{
  const layout = foldLayout({ total: 1000, folds: 4, isFraction: 0.7, embargoBars: 10 });
  check('in-sample bars = floor(1000 * 0.7) = 700', layout.inSampleBars === 700, String(layout.inSampleBars));
  // (1000 - 700 - 10) / 4 = 72.5 -> 72
  check('per-fold bars = floor((1000-700-10)/4) = 72', layout.perFoldBars === 72, String(layout.perFoldBars));
  const single = foldLayout({ total: 1000, folds: 1, isFraction: 0.7, embargoBars: 10 });
  check('single split OOS bars = 1000-700-10 = 290', single.singleOosBars === 290, String(single.singleOosBars));
  check('single split has no per-fold size', single.perFoldBars === 0);
}

console.log('preflight — accepts a run the engine can actually complete');
check('a sane catalog run has no blocking error', errorsOf(baseInput).length === 0, errorsOf(baseInput).join(' | '));

console.log('preflight — blocks runs the backend is known to refuse');
check(
  'unwired robot is blocked',
  errorsOf({ ...baseInput, spec: spec({ wired_in_backtest: false }) }).some((m) => m.includes('fail closed')),
);
check(
  'missing spec is blocked',
  errorsOf({ ...baseInput, spec: undefined }).some((m) => m.includes('no spec')),
);
check(
  'full_sample + optuna is blocked',
  errorsOf({ ...baseInput, fullSample: true, useOptuna: true }).some((m) => m.includes('mutually exclusive')),
);
check(
  'multi-window with custom dates is blocked',
  errorsOf({ ...baseInput, folds: 4, windowMode: 'custom' }).some((m) => m.includes('derive their own windows')),
);
check(
  'partial custom dates are blocked',
  errorsOf({
    ...baseInput,
    folds: 1,
    windowMode: 'custom',
    isStart: '2024-01-01',
    isEnd: '',
    oosStart: '',
    oosEnd: '',
  }).some((m) => m.includes('all four dates')),
);
check(
  'is_fraction at 1.0 is blocked',
  errorsOf({ ...baseInput, isFraction: 1 }).some((m) => m.includes('between 0 and 1')),
);
check(
  'too few bars for the warm-up is blocked',
  errorsOf({ ...baseInput, totalBars: 200, folds: 1 }).some((m) => m.includes('warm up')),
);
check(
  'per-fold size below one bar is blocked',
  errorsOf({ ...baseInput, totalBars: 100, folds: 10, isFraction: 0.9 }).some((m) =>
    m.includes('cannot fill'),
  ),
);
check(
  'legs shorter than the warm-up are blocked',
  errorsOf({ ...baseInput, totalBars: 400, folds: 8, isFraction: 0.7 }).some((m) =>
    m.includes('out-of-sample leg gets 13 bars'),
  ),
);
check(
  'missing instrument is blocked',
  errorsOf({ ...baseInput, instrument: null, totalBars: null }).some((m) => m.includes('No instrument selected')),
);
check('synthetic smoke run is allowed', errorsOf({ ...baseInput, source: 'synthetic' }).length === 0);

console.log('preflight — warns without blocking');
{
  const catalogWarnings = preflight({ ...baseInput, catalogInstruments: 2 })
    .filter((issue) => issue.level === 'warning')
    .map((issue) => issue.message);
  check('multi-instrument catalog warns', catalogWarnings.some((m) => m.includes('2 instruments')));

  const syntheticWarnings = preflight({ ...baseInput, source: 'synthetic', pbo: true })
    .filter((issue) => issue.level === 'warning')
    .map((issue) => issue.message);
  check('PBO on synthetic warns', syntheticWarnings.some((m) => m.includes('synthetic generator')));
  check(
    'warnings never block the run',
    errorsOf({ ...baseInput, source: 'synthetic', pbo: true }).length === 0,
  );
}

console.log('preflight — tick-level filters are never accepted without the data behind them');
{
  const tickReady = {
    ...baseInput,
    tickVpin: true,
    tickVpinRobots: ['regime', 'meta_label', 'vpin_momentum'],
    hawkesRobots: ['regime', 'meta_label'],
    tickDataAvailable: true,
  };
  check('tick VPIN on a wired robot with ticks passes', errorsOf(tickReady).length === 0, errorsOf(tickReady).join(' | '));
  check(
    'Hawkes on regime with ticks passes',
    errorsOf({ ...tickReady, tickVpin: false, hawkes: true }).length === 0,
  );

  check(
    'tick VPIN on a robot that ignores it is blocked',
    errorsOf({ ...tickReady, robot: 'ema' }).some((m) => m.includes('not wired into')),
  );
  check(
    'Hawkes on a robot without a regime router is blocked',
    errorsOf({
      ...baseInput,
      robot: 'vpin_momentum',
      hawkes: true,
      hawkesRobots: ['regime'],
      tickDataAvailable: true,
    }).some((m) => m.includes('Hawkes filter is not wired')),
  );
  check(
    'tick VPIN on synthetic bars is blocked',
    errorsOf({ ...tickReady, source: 'synthetic' }).some((m) => m.includes('no ticks')),
  );
  check(
    'tick VPIN without a tick series is blocked',
    errorsOf({ ...tickReady, tickDataAvailable: false }).some((m) =>
      m.includes('No aggregated-trade series'),
    ),
  );
  const unknownCoverage = preflight({ ...tickReady, tickDataAvailable: null })
    .filter((issue) => issue.level === 'warning')
    .map((issue) => issue.message);
  check(
    'unknown coverage is a warning, not a silent pass',
    unknownCoverage.some((m) => m.includes('coverage could not be read')),
  );
  check(
    'unknown coverage still allows the run',
    errorsOf({ ...tickReady, tickDataAvailable: null }).length === 0,
  );
}

console.log('preflight — a stress slice must lie inside the catalog it runs on');
{
  // The catalog in baseInput covers 2024-01-01..2026-04-01: covid2020 and ftx2022 are
  // wholly outside it, and a slice replaces the load window, so those runs would load
  // zero bars and die after a full process launch.
  const outside = {
    ...baseInput,
    stressSliceWindow: {
      name: 'covid2020',
      start: '2020-02-01T00:00:00+00:00',
      end: '2020-05-01T00:00:00+00:00',
    },
  };
  check(
    'a slice outside the catalog is blocked',
    errorsOf(outside).some((m) => m.includes('which this catalog does not hold')),
  );
  check(
    'the blocking message names the slice and the command that fixes it',
    errorsOf(outside).some((m) => m.includes('covid2020') && m.includes('Ingest that window')),
  );

  const inside = {
    ...baseInput,
    stressSliceWindow: {
      name: 'etf2024',
      start: '2024-01-01T00:00:00+00:00',
      end: '2024-06-01T00:00:00+00:00',
    },
  };
  check('a slice inside the catalog is allowed', errorsOf(inside).length === 0, errorsOf(inside).join(' | '));

  const partial = {
    ...baseInput,
    stressSliceWindow: {
      name: 'ftx2022',
      start: '2022-05-01T00:00:00+00:00',
      end: '2024-03-01T00:00:00+00:00',
    },
  };
  check('a slice starting before the catalog warns without blocking', errorsOf(partial).length === 0);
  check(
    'the partial-overlap warning explains the truncation',
    preflight(partial)
      .filter((issue) => issue.level === 'warning')
      .some((issue) => issue.message.includes('starts before the catalog does')),
  );

  check(
    'sliceOverlapsCatalog agrees with the preflight verdict',
    sliceOverlapsCatalog(
      { start: '2024-01-01T00:00:00+00:00', end: '2024-06-01T00:00:00+00:00' },
      baseInput.instrument,
    ) && !sliceOverlapsCatalog(outside.stressSliceWindow, baseInput.instrument),
  );
  check(
    'an unknown catalog range is treated as covering, not as absent',
    sliceOverlapsCatalog(outside.stressSliceWindow, null),
  );
}

console.log('cliCommand — only flags that exist in interfaces/cli.py');
{
  const command = cliCommand({
    robot: 'regime',
    source: 'catalog',
    bars: 3000,
    folds: 4,
    isFraction: 0.7,
    embargoBars: 10,
    useOptuna: false,
    optunaTrials: 20,
    pbo: false,
    pboBlocks: 8,
    barVpin: false,
    tickVpin: true,
    hawkes: true,
    stressSlice: 'ftx2022',
    generateTearsheet: true,
    journal: true,
    notify: false,
    fullSample: false,
    catalogPath: 'catalog',
    instrumentId: 'ETH/USDT.SIM',
    windowMode: 'fraction',
    isStart: '',
    isEnd: '',
    oosStart: '',
    oosEnd: '',
  });
  // `--instrument` and `--stress-slice` are not CLI flags: the button used to emit both,
  // so "reproduce it in the terminal" produced a usage error instead of the run.
  check('the CLI command names no --instrument flag', !command.includes('--instrument '));
  check('the stress slice uses --slice', command.includes('--slice ftx2022'));
  check('the tick flags are carried through', command.includes('--tick-vpin') && command.includes('--hawkes'));
  check('folds are carried through', command.includes('--folds 4'));
  check('the catalog is carried through', command.includes('--catalog catalog'));
  check('the instrument travels as INSTRUMENT_ID', command.startsWith('INSTRUMENT_ID=ETH/USDT.SIM '));

  const pbo = cliCommand({
    robot: 'regime',
    source: 'catalog',
    bars: 3000,
    folds: 1,
    isFraction: 0.7,
    embargoBars: 10,
    useOptuna: false,
    optunaTrials: 20,
    pbo: true,
    pboBlocks: 12,
    barVpin: false,
    tickVpin: false,
    hawkes: false,
    stressSlice: '',
    generateTearsheet: true,
    journal: false,
    notify: false,
    fullSample: false,
    catalogPath: 'catalog',
    instrumentId: 'ETH/USDT.SIM',
    windowMode: 'fraction',
    isStart: '',
    isEnd: '',
    oosStart: '',
    oosEnd: '',
  });
  // the API refuses --pbo with a tearsheet; the preview must not suggest otherwise
  check('a PBO audit emits no --tearsheet', !pbo.includes('--tearsheet'));
  check('a non-default block count is emitted', pbo.includes('--pbo-blocks 12'));

  const fullSample = cliCommand({
    robot: 'regime',
    source: 'catalog',
    bars: 3000,
    folds: 4,
    isFraction: 0.5,
    embargoBars: 0,
    useOptuna: false,
    optunaTrials: 20,
    pbo: false,
    pboBlocks: 8,
    barVpin: false,
    tickVpin: false,
    hawkes: false,
    stressSlice: '',
    generateTearsheet: false,
    journal: false,
    notify: false,
    fullSample: true,
    catalogPath: 'catalog',
    instrumentId: 'ETH/USDT.SIM',
    windowMode: 'fraction',
    isStart: '',
    isEnd: '',
    oosStart: '',
    oosEnd: '',
  });
  check('a full-sample run drops the split flags', fullSample.includes('--full-sample') && !fullSample.includes('--folds'));
}

console.log('format — an unmeasured number is never rendered as zero');
check('formatPct(null) is n/a', formatPct(null) === 'n/a');
check('formatBps(null) is n/a', formatBps(null) === 'n/a');
check('toneOf(null) is neutral', toneOf(null) === 'neutral');
check('formatPct(0.0123) is +1.23%', formatPct(0.0123) === '+1.23%');
check('formatBps(0.0005) is 5.0 bps', formatBps(0.0005) === '5.0 bps');
check('formatPct(-0.05) keeps the sign', formatPct(-0.05) === '-5.00%');

console.log('fractionBoundaries — derives the bar-index split, not a time fraction');
{
  // 101 bars spanning 2024-01-01..2024-04-10, is_fraction 0.5 -> split at bar 50
  const first = '2024-01-01T00:00:00+00:00';
  const last = '2024-04-10T00:00:00+00:00';
  const bands = fractionBoundaries({
    firstDate: first,
    lastDate: last,
    barsCount: 101,
    isFraction: 0.5,
    embargoBars: 0,
  });
  const totalSeconds = Date.parse(last) / 1000 - Date.parse(first) / 1000;
  const expected = Date.parse(first) / 1000 + (totalSeconds / 100) * 50;
  check('split lands at bar 50 of 101', bands.isEnd != null && Math.abs(bands.isEnd - expected) < 1, String(bands.isEnd));
  check('OOS starts where IS ends when the embargo is zero', bands.oosStart === bands.isEnd);
  const withGap = fractionBoundaries({
    firstDate: first,
    lastDate: last,
    barsCount: 101,
    isFraction: 0.5,
    embargoBars: 10,
  });
  check('embargo pushes OOS start later', (withGap.oosStart ?? 0) > (bands.oosStart ?? 0));
  const unknown = fractionBoundaries({
    firstDate: first,
    lastDate: last,
    barsCount: 0,
    isFraction: 0.5,
    embargoBars: 0,
  });
  check('unknown bar count still returns boundaries', unknown.isEnd != null);
  check(
    'unusable dates give no boundaries',
    fractionBoundaries({ firstDate: null, lastDate: null, barsCount: 100, isFraction: 0.5, embargoBars: 0 })
      .isEnd === null,
  );
}

const summaryBase: ResearchSummary = {
  is_finished: true,
  is_error: false,
  run_type: 'multi_window',
  robot: 'regime',
  source: 'catalog',
  finished_at: '2026-01-01T00:00:00+00:00',
  tearsheet_url: null,
  multi_window: null,
  single_backtest: null,
};

console.log('verdict — never reads an in-sample number as a result');
{
  const none = verdictFor(null);
  check('no run yields no evidence', none.evidence === 'none');

  const fullSample = verdictFor({
    ...summaryBase,
    run_type: 'full_sample',
    single_backtest: {
      fills: 5,
      positions: 1,
      ending_balance: 120000,
      fees_paid: 10,
      max_dd_pct: '4.00%',
      turnover: 1000,
      sharpe: 1.2,
      breakeven_cost: 0.0007,
      paid_cost_rate: 0.0005,
      cost_headroom: 0.0002,
      traded_notional: 20000,
      metrics: null,
    },
  });
  check('full-sample run is in-sample only', fullSample.evidence === 'in-sample-only');
  check('in-sample run claims no baseline verdict', fullSample.beatsBuyHold === null);
  check('in-sample run warns it is not a result', fullSample.concerns.some((c) => c.includes('No out-of-sample split')));

  const losing = verdictFor({
    ...summaryBase,
    multi_window: {
      profitable: '1/2',
      fold_count: 2,
      mean_oos: '+1.00%',
      mean_oos_raw: '0.01',
      median_oos: '+1.00%',
      worst_oos: '-2.00%',
      best_oos: '+4.00%',
      spread: '+6.00%',
      spread_raw: '0.06',
      buy_and_hold_mean: '+9.00%',
      buy_and_hold_mean_raw: '0.09',
      mean_excess_return: '-8.00%',
      mean_excess_return_raw: '-0.08',
      total_oos_fills: 12,
      beats_buy_and_hold: false,
      mean_breakeven_cost: 0.0006,
      breakeven_costs: [0.0006, 0.0005],
      mean_paid_cost_rate: 0.0005,
      cost_headroom: 0.0001,
      folds: [
        {
          index: 0,
          oos_return: '+4.00%',
          oos_return_raw: '0.04',
          buy_and_hold_return: '+3.00%',
          buy_and_hold_return_raw: '0.03',
          excess_return: '+1.00%',
          excess_return_raw: '0.01',
          beats_buy_and_hold: true,
          selected: 'fast=10',
          candidates_tried: 3,
          fills: 8,
          in_sample_fills: 4,
          oos_ending_balance: 104000,
          oos_metrics: null,
          window: { out_of_sample_start: '2025-01-01T00:00:00+00:00', out_of_sample_end: '2025-02-01T00:00:00+00:00' },
        },
        {
          index: 1,
          oos_return: '-2.00%',
          oos_return_raw: '-0.02',
          buy_and_hold_return: '+15.00%',
          buy_and_hold_return_raw: '0.15',
          excess_return: '-17.00%',
          excess_return_raw: '-0.17',
          beats_buy_and_hold: false,
          selected: 'fast=20',
          candidates_tried: 3,
          fills: 4,
          in_sample_fills: 2,
          oos_ending_balance: 98000,
          oos_metrics: null,
          window: { out_of_sample_start: '2025-02-01T00:00:00+00:00', out_of_sample_end: '2025-03-01T00:00:00+00:00' },
        },
      ],
      notes: '',
      summary_line: 'folds=2',
    },
  });
  check('multi-window is out-of-sample evidence', losing.evidence === 'out-of-sample');
  check('losing to buy&hold is reported as such', losing.beatsBuyHold === false);
  check('losing run lists the baseline as a concern', losing.concerns.some((c) => c.includes('Lost to simply holding')));
  check('partial fold wins are flagged', losing.concerns.some((c) => c.includes('1/2 folds')));
  check(
    'positive cost headroom is not flagged',
    !losing.concerns.some((c) => c.includes('Breakeven cost')),
  );

  const zeroFills = verdictFor({
    ...summaryBase,
    multi_window: {
      ...(losing as unknown as { }) && {
        profitable: '0/2',
        fold_count: 2,
        mean_oos: '+0.00%',
        mean_oos_raw: '0.0',
        median_oos: '+0.00%',
        worst_oos: '+0.00%',
        best_oos: '+0.00%',
        spread: '+0.00%',
        spread_raw: '0.0',
        buy_and_hold_mean: '+5.00%',
        buy_and_hold_mean_raw: '0.05',
        mean_excess_return: '-5.00%',
        mean_excess_return_raw: '-0.05',
        total_oos_fills: 0,
        beats_buy_and_hold: false,
        mean_breakeven_cost: null,
        breakeven_costs: [],
        mean_paid_cost_rate: null,
        cost_headroom: null,
        folds: [],
        notes: '',
        summary_line: '',
      },
    },
  });
  const noHeadroom = verdictFor({
    ...summaryBase,
    multi_window: {
      profitable: '2/2',
      fold_count: 2,
      mean_oos: '+2.00%',
      mean_oos_raw: '0.02',
      median_oos: '+2.00%',
      worst_oos: '+1.00%',
      best_oos: '+3.00%',
      spread: '+2.00%',
      spread_raw: '0.02',
      buy_and_hold_mean: '+1.00%',
      buy_and_hold_mean_raw: '0.01',
      mean_excess_return: '+1.00%',
      mean_excess_return_raw: '0.01',
      total_oos_fills: 30,
      beats_buy_and_hold: true,
      mean_breakeven_cost: 0.0004,
      breakeven_costs: [0.0004, 0.0004],
      mean_paid_cost_rate: 0.0005,
      cost_headroom: -0.0001,
      folds: [],
      notes: '',
      summary_line: '',
    },
  });
  check('a winner still passes all fold checks', noHeadroom.beatsBuyHold === true);
  check(
    'negative cost headroom is flagged even when the run won',
    noHeadroom.concerns.some((c) => c.includes('Breakeven cost is at or below the cost')),
  );

  const belowZeroCost = verdictFor({
    ...summaryBase,
    multi_window: {
      ...(noHeadroom as unknown as { multi_window: never }).multi_window,
      mean_breakeven_cost: -0.0031,
      cost_headroom: -0.0036,
    },
  });
  check(
    'a negative breakeven is called out as losing before fees',
    belowZeroCost.concerns.some((c) => c.includes('loses money even before fees')),
  );
  check(
    'a negative breakeven does not claim cheaper execution would help',
    !belowZeroCost.concerns.some((c) => c.includes('depends on cheap execution')),
  );

  check('zero fills is called out', zeroFills.concerns.some((c) => c.includes('Zero out-of-sample fills')));

  const audit = verdictFor({
    ...summaryBase,
    run_type: 'pbo',
    pbo: {
      pbo: '0.25',
      blocks: 8,
      configuration_count: 6,
      split_count: 4,
      is_meaningful: true,
      summary_line: 'PBO=0.25 over 4 splits',
      deflated_sharpe: {
        summary_line: 'DSR=0.9',
        probability: '0.9',
        sharpe: '1.1',
        threshold_sharpe: '0.4',
        observations: 8,
        trials: 6,
        note: '',
      },
      labels: ['a'],
      block_returns: [[0.01]],
      best_configuration_index: 0,
      best_configuration_label: 'a',
      notes: '',
    },
  });
  check('a PBO run is an overfitting audit, not a PnL verdict', audit.evidence === 'overfitting-audit');

  const syntheticRun = verdictFor({
    ...summaryBase,
    source: 'synthetic',
    multi_window: {
      profitable: '2/2',
      fold_count: 2,
      mean_oos: '+40.00%',
      mean_oos_raw: '0.4',
      median_oos: '+40.00%',
      worst_oos: '+10.00%',
      best_oos: '+70.00%',
      spread: '+60.00%',
      spread_raw: '0.6',
      buy_and_hold_mean: '+1.00%',
      buy_and_hold_mean_raw: '0.01',
      mean_excess_return: '+39.00%',
      mean_excess_return_raw: '0.39',
      total_oos_fills: 200,
      beats_buy_and_hold: true,
      mean_breakeven_cost: 0.01,
      breakeven_costs: [0.01],
      mean_paid_cost_rate: 0.0005,
      cost_headroom: 0.0095,
      folds: [],
      notes: '',
      summary_line: '',
    },
  });
  check(
    'a spectacular synthetic result still carries the synthetic warning',
    syntheticRun.concerns.some((c) => c.includes('synthetic bars')),
  );

  const errored = verdictFor({ ...summaryBase, is_error: true, error_message: 'boom' });
  check('an errored run carries no evidence', errored.evidence === 'none');
}

console.log('');
if (failures > 0) {
  console.error(`${failures} check(s) failed`);
  process.exit(1);
}
console.log('all logic checks passed');
