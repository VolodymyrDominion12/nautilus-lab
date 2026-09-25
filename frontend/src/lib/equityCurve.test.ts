/**
 * Chaining out-of-sample folds into one equity path (docs/27 E-2.5).
 */
import { describe, expect, test } from 'vitest';

import { chainFolds, curveStats } from './equityCurve';
import type { FoldSummary } from '../services/api';

const fold = (oos: string | null, bh: string | null, fills = 3): FoldSummary =>
  ({
    oos_return_raw: oos,
    buy_and_hold_return_raw: bh,
    fills,
    oos_metrics: null,
    window: { out_of_sample_start: '2024-01-01T00:00:00Z', out_of_sample_end: '2024-02-01T00:00:00Z' },
  }) as unknown as FoldSummary;

const close = (actual: number | undefined, expected: number) =>
  expect(Math.abs((actual ?? Number.NaN) - expected) < 1e-9, `${actual} != ${expected}`).toBe(true);

describe('chainFolds', () => {
  test('no folds, no path', () => {
    expect(chainFolds([], 10_000)).toEqual([]);
  });

  test('returns compound fold after fold, for the robot and buy & hold alike', () => {
    const points = chainFolds([fold('0.10', '0.05'), fold('-0.10', '0.05')], 1_000);
    expect(points.map((p) => p.label)).toEqual(['Start', 'Fold 1', 'Fold 2']);
    close(points[1]?.equityValue, 1_100);
    close(points[2]?.equityValue, 990);
    close(points[2]?.cumulativeOosReturn, -0.01);
    close(points[2]?.bhEquityValue, 1_102.5);
  });

  test('drawdown is measured from the running peak', () => {
    const points = chainFolds([fold('0.10', '0'), fold('-0.10', '0'), fold('0.20', '0')], 1_000);
    expect(points[1]?.drawdownPct).toBe(0);
    close(points[2]?.drawdownPct, -0.1);
    expect(points[3]?.drawdownPct).toBe(0);
  });

  test('an unmeasured fold return leaves equity unchanged instead of breaking the path', () => {
    const points = chainFolds([fold(null, null)], 1_000);
    close(points[1]?.equityValue, 1_000);
  });

  test('a missing or non-positive starting equity falls back to 10 000', () => {
    expect(chainFolds([fold('0', '0')], null)[0]?.equityValue).toBe(10_000);
    expect(chainFolds([fold('0', '0')], 0)[0]?.equityValue).toBe(10_000);
  });
});

test('curveStats: totals, deepest drawdown and fold win rate', () => {
  const folds = [fold('0.10', '0.02'), fold('-0.10', '0.02'), fold('0.05', '0.02'), fold('0', '0')];
  const stats = curveStats(chainFolds(folds, 1_000), folds);
  close(stats.maxDd, 0.1);
  expect(stats.profitableFolds).toBe(2);
  expect(stats.winRate).toBe(50);
  close(stats.totalOos, 1.1 * 0.9 * 1.05 - 1);
});
