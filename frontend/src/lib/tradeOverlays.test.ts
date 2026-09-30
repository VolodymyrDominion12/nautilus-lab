import { describe, expect, test } from 'vitest';
import { extraPasses, histogram, overlaySeries } from './tradeOverlays';

const bars = [0, 3600, 7200, 10800].map((time) => ({
  time,
  open: 1,
  high: 1,
  low: 1,
  close: 1,
  volume: 1,
}));
const at = (seconds: number) => new Date(seconds * 1000 + 3599_999).toISOString();

describe('trade overlays', () => {
  test('draws price-scale values and the stop path, skips oscillators', () => {
    const rows = [0, 3600, 7200].map((t, i) => ({
      ts: at(t),
      steps: [
        {
          stage: 'strategy',
          component: 'UptrendBreakout',
          values: { prior_high: 100 + i, ema: '90.5', dist_to_breakout_pct: -0.2 },
        },
        { stage: 'regime', component: 'RegimeClassifier', values: { er: 0.4 } },
      ],
      states: { stop_loss: String(95 + i) },
    }));
    const series = overlaySeries(rows, bars);
    expect(series.map((s) => s.key)).toEqual(['ema', 'prior_high', 'stop_loss']);
    const stop = series.find((s) => s.key === 'stop_loss');
    expect(stop?.step).toBe(true);
    expect(stop?.points.map((p) => p.value)).toEqual([95, 96, 97]);
  });

  test('a single point is not a line; rows off the chart are dropped', () => {
    const rows = [{ ts: at(0), steps: [{ stage: 'strategy', values: { ema: 1 } }], states: {} }];
    expect(overlaySeries(rows, bars)).toEqual([]);
    expect(overlaySeries([{ ts: at(999_999), steps: [], states: { stop_loss: 1 } }], bars)).toEqual([]);
  });
});

describe('margins', () => {
  test('extra passes count readings just short of the threshold', () => {
    expect(extraPasses([-12, -4.9, -0.1, 0, 3], 5)).toBe(2);
    expect(extraPasses([-12, -4.9, -0.1, 0, 3], 0)).toBe(0);
  });

  test('histogram clamps outliers into the edge buckets', () => {
    const buckets = histogram([-80, -1, 0, 1, 99], { min: -10, max: 10, width: 5 });
    expect(buckets.map((b) => b.count)).toEqual([1, 1, 2, 1]);
  });
});
