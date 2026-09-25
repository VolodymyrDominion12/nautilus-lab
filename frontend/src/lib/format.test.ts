/**
 * The formatting helpers every result panel shares (docs/27 E-2.4).
 *
 * The rule under test is the one in the module header: an unmeasured number stays
 * unmeasured. `null`, `''` and `NaN` must come out as "n/a" / neutral / unknown, never as
 * a zero that reads like a result.
 */

import { describe, expect, test } from 'vitest';

import {
  dateToUnixSeconds,
  describeStaleness,
  evidenceBadge,
  formatBps,
  formatDate,
  formatDateTime,
  formatElapsed,
  formatPct,
  toNumber,
  toneOf,
} from './format';

describe('toNumber', () => {
  const cases: [raw: string | number | null | undefined, expected: number | null][] = [
    [null, null],
    [undefined, null],
    ['', null],
    ['n/a', null],
    ['NaN', null],
    ['Infinity', null],
    ['0.0123', 0.0123],
    [-2, -2],
    ['0', 0],
  ];
  test.each(cases)('%j -> %j', (raw, expected) => {
    expect(toNumber(raw)).toBe(expected);
  });
});

describe('percent and basis points', () => {
  test('signs are explicit and missing values are n/a', () => {
    expect(formatPct(0.0123)).toBe('+1.23%');
    expect(formatPct(-0.05)).toBe('-5.00%');
    expect(formatPct(0)).toBe('0.00%');
    expect(formatPct(null)).toBe('n/a');
    expect(formatPct(Number.NaN)).toBe('n/a');
  });

  test('fees read in basis points', () => {
    expect(formatBps(0.0005)).toBe('5.0 bps');
    expect(formatBps(0.001, 2)).toBe('10.00 bps');
    expect(formatBps(undefined)).toBe('n/a');
  });
});

describe('toneOf', () => {
  test('an unmeasured number is neutral, not a loss', () => {
    expect(toneOf(null)).toBe('neutral');
    expect(toneOf(Number.NaN)).toBe('neutral');
    expect(toneOf(0)).toBe('neutral');
    expect(toneOf(0.01)).toBe('positive');
    expect(toneOf(-0.01)).toBe('negative');
  });
});

describe('dates', () => {
  test('ISO timestamps are shown in UTC without the T', () => {
    expect(formatDateTime('2026-09-25T10:15:30+03:00')).toBe('2026-09-25 07:15:30');
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('not a date')).toBe('not a date');
    expect(formatDate('2026-09-25T10:15:30Z')).toBe('2026-09-25');
  });

  test('dateToUnixSeconds reads the day at 00:00 UTC', () => {
    expect(dateToUnixSeconds('2024-01-01')).toBe(1704067200);
    expect(dateToUnixSeconds('2024-01-01T23:59:59Z')).toBe(1704067200);
    expect(dateToUnixSeconds('garbage')).toBeNull();
    expect(dateToUnixSeconds(null)).toBeNull();
  });
});

describe('formatElapsed', () => {
  const cases: [seconds: number | null, expected: string][] = [
    [5, '5s'],
    [80, '1m 20s'],
    [3_700, '1h 1m'],
    [59.9, '59s'],
    [-1, ''],
    [null, ''],
  ];
  test.each(cases)('%j seconds -> %j', (seconds, expected) => {
    expect(formatElapsed(seconds)).toBe(expected);
  });
});

describe('describeStaleness', () => {
  const now = Date.UTC(2026, 8, 25); // 2026-09-25

  const cases: [lastDate: string, days: number, level: string][] = [
    ['2026-09-25', 0, 'current'],
    ['2026-09-18', 7, 'current'],
    ['2026-09-17', 8, 'aging'],
    ['2026-08-26', 30, 'aging'],
    ['2026-08-25', 31, 'stale'],
  ];
  test.each(cases)('last bar %s is %i days old: %s', (lastDate, days, level) => {
    expect(describeStaleness(lastDate, now)).toEqual({ days, level });
  });

  test('an unparseable date is unknown, not fresh', () => {
    expect(describeStaleness('???', now)).toEqual({ days: null, level: 'unknown' });
    expect(describeStaleness(null, now)).toEqual({ days: null, level: 'unknown' });
  });
});

describe('evidenceBadge', () => {
  test('an in-sample number is labelled as selection only', () => {
    expect(evidenceBadge('in-sample-only').label).toContain('selection only');
    expect(evidenceBadge('out-of-sample').label).toContain('report this');
    expect(evidenceBadge('overfitting-audit').label).toContain('no PnL verdict');
    expect(evidenceBadge('none').label).toBe('no result yet');
  });
});
