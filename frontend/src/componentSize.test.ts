/**
 * Component size budget (docs/27 E-2.5: no component over 15 KB).
 *
 * A 57 KB component cannot be reviewed, and every change to it risks the parts nobody
 * touched. This test enforces a ratchet:
 * - a new or split file must stay under the limit;
 * - each file still over it (listed below) may only shrink;
 * - once a listed file is under the limit it must leave the list, so the budget
 *   tightens instead of quietly keeping the old allowance.
 *
 * The fix for a failure is to split the file (a hook, a panel, a pure `lib/` function),
 * not to raise a number here.
 */
import { describe, expect, test } from 'vitest';

const LIMIT_BYTES = 15 * 1024;

/** Still over the limit when the budget started (2026-09-25), capped at that size. */
const OVERSIZED: Record<string, number> = {
  './components/ResearchLab.tsx': 56_894,
  './components/LiveTradingTerminal.tsx': 49_656,
  './components/AlphaIdeasTab.tsx': 24_570,
  './components/CommandCenter.tsx': 23_002,
  './components/EquityCurveChart.tsx': 16_754,
};

const sources = import.meta.glob<string>('./**/*.tsx', {
  query: '?raw',
  import: 'default',
  eager: true,
});

const encoder = new TextEncoder();
const sizes = Object.entries(sources).map(
  ([path, text]): [path: string, bytes: number] => [path, encoder.encode(text).length],
);

describe('component size budget', () => {
  test('the glob sees the components', () => {
    expect(sizes.length).toBeGreaterThan(20);
  });

  test.each(sizes)('%s stays within its budget', (path, bytes) => {
    const cap = OVERSIZED[path];
    if (cap === undefined) {
      expect(bytes, `${path} is ${bytes} bytes; split it below ${LIMIT_BYTES}`).toBeLessThanOrEqual(
        LIMIT_BYTES,
      );
    } else {
      expect(bytes, `${path} grew past ${cap} bytes; split it instead`).toBeLessThanOrEqual(cap);
    }
  });

  test('every listed file still exists and is still over the limit', () => {
    const measured = new Map(sizes);
    for (const path of Object.keys(OVERSIZED)) {
      const bytes = measured.get(path);
      expect(bytes, `${path} is listed but no longer exists`).toBeDefined();
      expect(
        bytes,
        `${path} is now ${bytes} bytes, under the limit: remove it from OVERSIZED`,
      ).toBeGreaterThan(LIMIT_BYTES);
    }
  });
});
