import { describe, expect, test } from 'vitest';
import {
  blockedShare,
  buildBatchHash,
  formatDuration,
  retryBlockedReason,
  parseBatchHash,
  parseVariants,
  variantOfCell,
  restartBlockedReason,
  restartHint,
  resumeBlockedReason,
  resumeHint,
  unfinishedCells,
  rowWarnings,
  sortRows,
  topCounts,
  type BatchListRow,
  type BatchRow,
} from './batch';

const row = (over: Partial<BatchRow>): BatchRow => ({
  cell_id: 'ema_BTC',
  robot: 'ema',
  symbol: 'BTCUSDT',
  instrument_id: 'BTC/USDT.SIM',
  interval: '1h',
  catalog: 'catalog',
  status: 'ok',
  ...over,
});

describe('batch routes', () => {
  test('round-trip every page', () => {
    for (const route of [
      { page: 'list' as const },
      { page: 'batch' as const, batchId: '20260930_120000_batch' },
      { page: 'run' as const, batchId: 'b1', cellId: 'ema_BTC', fold: 2, tab: 'analysis' as const },
      { page: 'run' as const, batchId: 'b1', cellId: 'pairs_ETHBTC', fold: undefined, tab: undefined },
    ]) {
      expect(parseBatchHash(buildBatchHash(route))).toEqual(route);
    }
  });

  test('rejects foreign or unsafe fragments', () => {
    expect(parseBatchHash('#/trade?session=x&id=y')).toBeNull();
    expect(parseBatchHash('#/run/../etc')).toBeNull();
    expect(parseBatchHash('#/batch/a b')).toBeNull();
    expect(parseBatchHash('#/run/b1/ema_BTC?tab=nope')).toEqual({
      page: 'run',
      batchId: 'b1',
      cellId: 'ema_BTC',
      fold: undefined,
      tab: undefined,
    });
  });
});

describe('batch table', () => {
  test('sorts with missing values last in both directions', () => {
    const rows = [
      row({ cell_id: 'a', numbers: { mean_oos: 0.01 } }),
      row({ cell_id: 'b', numbers: { mean_oos: null } }),
      row({ cell_id: 'c', numbers: { mean_oos: -0.02 } }),
    ];
    expect(sortRows(rows, 'mean_oos', true).map((r) => r.cell_id)).toEqual(['a', 'c', 'b']);
    expect(sortRows(rows, 'mean_oos', false).map((r) => r.cell_id)).toEqual(['c', 'a', 'b']);
  });

  test('sorts by headroom (breakeven minus paid cost rate)', () => {
    const rows = [
      row({ cell_id: 'a', numbers: { mean_breakeven_cost: 0.0005, mean_paid_cost_rate: 0.0002 } }), // 3 bps
      row({ cell_id: 'b', numbers: { mean_breakeven_cost: null, mean_paid_cost_rate: null } }),
      row({ cell_id: 'c', numbers: { mean_breakeven_cost: 0.0001, mean_paid_cost_rate: 0.0004 } }), // -3 bps
    ];
    expect(sortRows(rows, 'headroom', true).map((r) => r.cell_id)).toEqual(['a', 'c', 'b']);
    expect(sortRows(rows, 'headroom', false).map((r) => r.cell_id)).toEqual(['c', 'a', 'b']);
  });

  test('blocked share and warnings read the decision counts', () => {
    const blocked = row({
      numbers: { total_oos_fills: 10 },
      decisions: {
        records: 100,
        bars: 100,
        untraced_bars: 60,
        in_position_pct: 10,
        outcomes: { ENTRY_BLOCKED_RISK: 30, NO_SIGNAL: 70 },
        blocked_by: { 'risk.max_drawdown': 30 },
        regime_share_pct: {},
        near_misses: 0,
        bar_seq_gaps: 0,
      },
    });
    expect(blockedShare(blocked)).toBeCloseTo(0.3);
    const warnings = rowWarnings(blocked);
    expect(warnings.some((w) => w.includes('без кроків'))).toBe(true);
    expect(warnings.some((w) => w.includes('30%'))).toBe(true);
    expect(topCounts(blocked.decisions?.outcomes, 1)).toBe('NO_SIGNAL×70');
  });

  test('a finished run with no fills is flagged', () => {
    expect(rowWarnings(row({ numbers: { total_oos_fills: 0 } }))).toContain('0 угод за всі фолди');
  });
});

describe('restarting a batch', () => {
  const listed = (over: Partial<BatchListRow>): BatchListRow => ({
    id: '20260930_120000_batch',
    label: 'batch',
    created_at: '2026-09-30T12:00:00+00:00',
    status: 'ok',
    cells: 4,
    counts: { ok: 4 },
    robots: ['ema'],
    symbols: ['ETHUSDT'],
    ...over,
  });

  test('any finished batch may be re-run, however it ended', () => {
    for (const status of ['ok', 'failed', 'cancelled', 'lost', 'blocked']) {
      expect(restartBlockedReason(listed({ status }))).toBeNull();
    }
  });

  test('a batch that is still moving is cancelled first', () => {
    expect(restartBlockedReason(listed({ status: 'running' }))).toContain('скасуйте');
    expect(restartBlockedReason(listed({ status: 'queued' }))).toContain('скасуйте');
  });

  test('an imported sweep has no request to re-run', () => {
    expect(restartBlockedReason(listed({ imported_from: 'reports/decision-sweep' }))).toContain(
      'імпортований',
    );
  });

  test('the row says when it was re-run, and how many times', () => {
    expect(restartHint(listed({}))).toBeNull();
    expect(restartHint(listed({ restarted_at: '2026-10-01T09:30:00+00:00' }))).toBe(
      'перезапущено 2026-10-01 09:30:00',
    );
    expect(
      restartHint(listed({ restarted_at: '2026-10-01T09:30:00+00:00', restart_count: 3 })),
    ).toBe('перезапущено 3× · 2026-10-01 09:30:00');
    // A stored batch from before the counter existed still reads as one restart.
    expect(
      restartHint(listed({ restarted_at: '2026-10-01T09:30:00+00:00', restart_count: null })),
    ).toBe('перезапущено 2026-10-01 09:30:00');
  });
});

describe('parseVariants', () => {
  test('reads named blocks of KEY=value, the way the batch will run them', () => {
    const { variants, error } = parseVariants(
      [
        '# гіпотези тижня',
        '[H0]',
        'REGIME_LEGS=uptrend,downtrend',
        '',
        '[H1]',
        'REGIME_LEGS=uptrend,downtrend',
        'ENTRY_FILTER_HTF_TREND=true',
      ].join('\n'),
    );
    expect(error).toBeNull();
    expect(variants).toEqual([
      { name: 'H0', env: { REGIME_LEGS: 'uptrend,downtrend' } },
      {
        name: 'H1',
        env: { REGIME_LEGS: 'uptrend,downtrend', ENTRY_FILTER_HTF_TREND: 'true' },
      },
    ]);
  });

  test('an empty box means a plain matrix, not an error', () => {
    expect(parseVariants('')).toEqual({ variants: [], error: null });
    expect(parseVariants('  \n# лише коментар\n')).toEqual({ variants: [], error: null });
  });

  test('refuses a half-understood matrix instead of running something else', () => {
    expect(parseVariants('REGIME_LEGS=uptrend').error).toContain('спершу оголоси варіант');
    expect(parseVariants('[H0]\nREGIME_LEGS=uptrend\n[H0]\nX=1').error).toContain('уже оголошено');
    expect(parseVariants('[H 0]\nA=1').error).toContain('ім\'я варіанта');
    expect(parseVariants('[H0]\nlower=1').error).toContain('назву налаштування');
    expect(parseVariants('[H0]\nбез знака').error).toContain('KEY=value');
    expect(parseVariants('[H0]\n[H1]\nA=1').error).toContain('не змінює жодного налаштування');
  });

  test('a value may contain «=» and spaces', () => {
    const { variants } = parseVariants('[H0]\nBINANCE_SYMBOLS=["BTCUSDT", "ETHUSDT"]');
    expect(variants[0]?.env.BINANCE_SYMBOLS).toBe('["BTCUSDT", "ETHUSDT"]');
  });
});

describe('variantOfCell', () => {
  test('reads the variant out of a cell id, and stays quiet for a plain batch', () => {
    expect(variantOfCell('regime_BTC__H1')).toBe('H1');
    expect(variantOfCell('pairs_ETHBTC__COST-x1_5')).toBe('COST-x1_5');
    expect(variantOfCell('regime_BTC')).toBeNull();
  });
});

describe('retryBlockedReason', () => {
  // A whole row, not a partial: the guard reads status, counts and the import marker.
  const row = (over: Partial<BatchListRow>): BatchListRow => ({
    id: '20261003_182518_batch',
    label: 'sweep',
    created_at: '2026-10-03T18:25:00+00:00',
    status: 'ok',
    cells: 50,
    counts: { ok: 34, failed: 6, blocked: 10 },
    robots: ['regime'],
    symbols: ['BTCUSDT'],
    ...over,
  });

  test('a batch with failed or cancelled cells can be repaired', () => {
    expect(retryBlockedReason(row({ counts: { ok: 3, failed: 2 } }))).toBeNull();
    expect(retryBlockedReason(row({ counts: { ok: 3, cancelled: 1 } }))).toBeNull();
  });

  test('a batch with nothing to redo says so instead of relaunching everything', () => {
    expect(retryBlockedReason(row({ counts: { ok: 4, blocked: 1 } }))).toContain(
      'Перезапустити',
    );
  });

  test('a running batch is cancelled first, and an imported one cannot be retried', () => {
    expect(retryBlockedReason(row({ status: 'running', counts: { failed: 1 } }))).toContain(
      'скасуйте',
    );
    expect(
      retryBlockedReason(row({ counts: { failed: 1 }, imported_from: 'reports/decision-sweep' })),
    ).toContain('імпортований');
  });
});

describe('formatDuration', () => {
  test('reads as time, not as a float', () => {
    expect(formatDuration(45)).toBe('45 с');
    expect(formatDuration(125)).toBe('2 хв 05 с');
    expect(formatDuration(7500)).toBe('2 год 05 хв');
    expect(formatDuration(null)).toBe('—');
  });
});

describe('resumeBlockedReason', () => {
  const row = (over: Partial<BatchListRow>): BatchListRow => ({
    id: '20261008_080000_batch',
    label: 'sweep',
    created_at: '2026-10-08T05:00:00+00:00',
    status: 'lost',
    cells: 20,
    counts: { ok: 12, running: 2, queued: 6 },
    robots: ['regime'],
    symbols: ['BTCUSDT'],
    ...over,
  });

  test('a batch whose process died can continue from where it stopped', () => {
    expect(resumeBlockedReason(row({}))).toBeNull();
    expect(unfinishedCells(row({}).counts)).toBe(8);
  });

  test('a cancelled batch can continue: cancel then continue is a pause', () => {
    expect(
      resumeBlockedReason(row({ status: 'cancelled', counts: { ok: 5, cancelled: 3 } })),
    ).toBeNull();
  });

  test('a running, finished or imported batch cannot', () => {
    expect(resumeBlockedReason(row({ status: 'running' }))).toContain('виконується');
    expect(resumeBlockedReason(row({ status: 'ok', counts: { ok: 18, failed: 2 } }))).toContain(
      'завершені',
    );
    expect(resumeBlockedReason(row({ imported_from: 'reports/decision-sweep' }))).toContain(
      'імпортований',
    );
  });

  test('the list says when a batch was continued', () => {
    expect(resumeHint(row({}))).toBeNull();
    expect(resumeHint(row({ resumed_at: '2026-10-08T06:00:00+00:00', resume_count: 2 }))).toContain(
      '2×',
    );
  });
});
