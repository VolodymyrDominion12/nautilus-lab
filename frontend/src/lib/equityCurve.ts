/**
 * The out-of-sample folds chained into one equity path (docs/27 E-2.5: pulled out of
 * `EquityCurveChart` so the arithmetic is tested without rendering an SVG).
 *
 * Each fold's OOS return compounds on the equity left by the previous fold, and so does
 * buy & hold. The first point is the starting equity before any fold.
 */
import { toNumber } from './format';
import type { FoldSummary } from '../services/api';

export interface EquityPoint {
  foldIndex: number;
  label: string;
  startDate: string;
  endDate: string;
  foldOosReturn: number;
  foldBhReturn: number;
  cumulativeOosReturn: number;
  cumulativeBhReturn: number;
  equityValue: number;
  bhEquityValue: number;
  /** Distance below the running peak, as a negative fraction (0 at a new high). */
  drawdownPct: number;
  maxFoldDrawdown: number;
  fills: number;
}

export function chainFolds(folds: FoldSummary[], startingEquity?: number | null): EquityPoint[] {
  if (!folds || folds.length === 0) return [];

  const baseEquity = startingEquity && startingEquity > 0 ? startingEquity : 10000;
  let currentEquity = baseEquity;
  let currentBhEquity = baseEquity;
  let peakEquity = baseEquity;

  const list: EquityPoint[] = [];

  // Initial starting point (Fold 0 baseline)
  const firstStart = folds[0]?.window?.out_of_sample_start || '';
  list.push({
    foldIndex: 0,
    label: 'Start',
    startDate: firstStart,
    endDate: firstStart,
    foldOosReturn: 0,
    foldBhReturn: 0,
    cumulativeOosReturn: 0,
    cumulativeBhReturn: 0,
    equityValue: baseEquity,
    bhEquityValue: baseEquity,
    drawdownPct: 0,
    maxFoldDrawdown: 0,
    fills: 0,
  });

  folds.forEach((fold, idx) => {
    const oosRet = toNumber(fold.oos_return_raw) ?? 0;
    const bhRet = toNumber(fold.buy_and_hold_return_raw) ?? 0;

    currentEquity = currentEquity * (1 + oosRet);
    currentBhEquity = currentBhEquity * (1 + bhRet);

    if (currentEquity > peakEquity) {
      peakEquity = currentEquity;
    }
    const dd = peakEquity > 0 ? (currentEquity - peakEquity) / peakEquity : 0;
    const foldMetricsDd = fold.oos_metrics?.max_drawdown ?? 0;

    list.push({
      foldIndex: idx + 1,
      label: `Fold ${idx + 1}`,
      startDate: fold.window?.out_of_sample_start || '',
      endDate: fold.window?.out_of_sample_end || '',
      foldOosReturn: oosRet,
      foldBhReturn: bhRet,
      cumulativeOosReturn: (currentEquity - baseEquity) / baseEquity,
      cumulativeBhReturn: (currentBhEquity - baseEquity) / baseEquity,
      equityValue: currentEquity,
      bhEquityValue: currentBhEquity,
      drawdownPct: dd,
      maxFoldDrawdown: Math.max(Math.abs(dd), foldMetricsDd),
      fills: fold.fills ?? 0,
    });
  });

  return list;
}

export interface CurveStats {
  totalOos: number;
  totalBh: number;
  /** Deepest drawdown along the chained path, as a positive fraction. */
  maxDd: number;
  profitableFolds: number;
  /** Share of folds with a positive OOS return, in percent. */
  winRate: number;
}

export function curveStats(points: EquityPoint[], folds: FoldSummary[]): CurveStats {
  const last = points[points.length - 1];
  const profitableFolds = folds.filter((f) => (toNumber(f.oos_return_raw) ?? 0) > 0).length;
  return {
    totalOos: last?.cumulativeOosReturn ?? 0,
    totalBh: last?.cumulativeBhReturn ?? 0,
    maxDd: Math.max(...points.map((p) => Math.abs(p.drawdownPct)), 0),
    profitableFolds,
    winRate: folds.length > 0 ? (profitableFolds / folds.length) * 100 : 0,
  };
}
