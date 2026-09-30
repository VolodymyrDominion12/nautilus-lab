/**
 * Indicator lines for the trade chart, read out of the decision log (docs/30, stage 6).
 *
 * The log already holds, per bar, the numbers each strategy decided on (EMA, Donchian
 * channel, Bollinger bands, trailing stop) and the stop that bound the position
 * (`states.stop_loss`). Drawing them over the candles shows *why* the entry happened where
 * it did — the close crossing the channel, the band touch — instead of leaving the reader
 * to reconstruct it from a table. Only price-scale values are overlaid; oscillators (ER,
 * VPIN, probabilities) stay in the indicator table, where their own scale makes sense.
 */
import type { TradeChartBar, TradeDecisionRow } from '../services/api';
import { toNumber } from './format';
import { snapToBar } from './trades';

export interface OverlayPoint {
  time: number;
  value: number;
}

export interface OverlaySeries {
  key: string;
  label: string;
  color: string;
  /** Drawn as a step line (a level that holds until it moves), not a slope. */
  step: boolean;
  dashed: boolean;
  points: OverlayPoint[];
}

/** Price-scale values worth drawing, with the label and colour each gets. */
const OVERLAYS: Record<string, { label: string; color: string; step?: boolean; dashed?: boolean }> = {
  fast_ema: { label: 'EMA fast', color: '#f59e0b' },
  slow_ema: { label: 'EMA slow', color: '#8b5cf6' },
  ema: { label: 'EMA', color: '#f59e0b' },
  prior_high: { label: 'Канал ↑', color: '#22d3ee', step: true, dashed: true },
  prior_low: { label: 'Канал ↓', color: '#22d3ee', step: true, dashed: true },
  mean: { label: 'BB середня', color: '#a3a3a3' },
  upper: { label: 'BB верх', color: '#64748b', dashed: true },
  lower: { label: 'BB низ', color: '#64748b', dashed: true },
  trail_stop: { label: 'Трейл-стоп', color: '#fb7185', step: true },
};
const STOP_KEY = 'stop_loss';

type Row = Pick<TradeDecisionRow, 'ts' | 'steps' | 'states'>;

/**
 * One series per overlay key found in `rows`, each point snapped onto a chart candle.
 *
 * Rows outside the chart's bars are dropped (`snapToBar` returns null); a key with fewer
 * than two points is not a line and is left out. The stop comes from `states.stop_loss`
 * and is drawn as a step line: that is how a ratchet moves.
 */
export const overlaySeries = (rows: Row[], bars: TradeChartBar[]): OverlaySeries[] => {
  const times = bars.map((bar) => bar.time);
  const collected = new Map<string, Map<number, number>>();
  const put = (key: string, time: number, value: number) => {
    const series = collected.get(key) ?? new Map<number, number>();
    series.set(time, value);
    collected.set(key, series);
  };

  for (const row of rows) {
    const time = snapToBar(Date.parse(row.ts) / 1000, times);
    if (time == null) continue;
    for (const step of row.steps ?? []) {
      if (step.stage !== 'strategy' && step.stage !== 'regime') continue;
      for (const [key, raw] of Object.entries(step.values ?? {})) {
        if (!(key in OVERLAYS)) continue;
        const value = toNumber(raw as string | number | null);
        if (value != null) put(key, time, value);
      }
    }
    const stop = toNumber((row.states ?? {})[STOP_KEY] as string | number | null);
    if (stop != null) put(STOP_KEY, time, stop);
  }

  const out: OverlaySeries[] = [];
  for (const [key, byTime] of collected) {
    if (byTime.size < 2) continue;
    const spec =
      key === STOP_KEY
        ? { label: 'Стоп-лос', color: '#ef4444', step: true, dashed: false }
        : { step: false, dashed: false, ...OVERLAYS[key] };
    out.push({
      key,
      label: spec.label ?? key,
      color: spec.color ?? '#94a3b8',
      step: Boolean(spec.step),
      dashed: Boolean(spec.dashed),
      points: [...byTime.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([time, value]) => ({ time, value })),
    });
  }
  return out.sort((a, b) => a.key.localeCompare(b.key));
};

/** Readings a threshold `softerByPct` looser would have let through (value in [-X, 0)). */
export const extraPasses = (values: number[], softerByPct: number): number =>
  values.reduce((n, value) => (value >= -softerByPct && value < 0 ? n + 1 : n), 0);

/** Counts per bucket of `width` percent over [min, max], for a small histogram. */
export const histogram = (
  values: number[],
  { min = -50, max = 50, width = 5 }: { min?: number; max?: number; width?: number } = {},
): { from: number; count: number }[] => {
  const buckets: { from: number; count: number }[] = [];
  for (let from = min; from < max; from += width) buckets.push({ from, count: 0 });
  for (const value of values) {
    const clamped = Math.min(Math.max(value, min), max - 1e-9);
    const index = Math.floor((clamped - min) / width);
    const bucket = buckets[index];
    if (bucket) bucket.count += 1;
  }
  return buckets;
};
