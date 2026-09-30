import { describe, expect, test } from 'vitest';
import {
  blockedShare,
  buildBatchHash,
  parseBatchHash,
  rowWarnings,
  sortRows,
  topCounts,
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
