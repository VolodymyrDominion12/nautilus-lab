import { describe, expect, test } from 'vitest';

import {
  mergeOverrides,
  parseOverrideText,
  parseParamRows,
  splitValues,
  sweepCombinations,
  sweepVariantCount,
  variantBudgetWarning,
} from './batchSweep';

describe('splitting values', () => {
  test('a semicolon is the sweep separator, a comma is not', () => {
    expect(splitValues('0.30;0.42')).toEqual(['0.30', '0.42']);
    // `REGIME_LEGS=uptrend,range` is ONE string value (docs/31), not two runs.
    expect(splitValues('uptrend,range')).toEqual(['uptrend,range']);
  });

  test('blank entries are dropped, not turned into empty runs', () => {
    expect(splitValues(' 0.3 ; ;0.4; ')).toEqual(['0.3', '0.4']);
  });
});

describe('the free-text box', () => {
  test('one line per key is one override for every cell', () => {
    expect(parseOverrideText('DRAWDOWN_COOLDOWN_DAYS=7\nRISK_PER_TRADE=0.01')).toEqual({
      env: { DRAWDOWN_COOLDOWN_DAYS: '7', RISK_PER_TRADE: '0.01' },
      sweep: {},
      error: null,
    });
  });

  test('a key repeated with another value becomes a sweep, not a silent last-wins', () => {
    const parsed = parseOverrideText('ENTER_TREND_ER=0.30\nENTER_TREND_ER=0.42');
    expect(parsed.error).toBeNull();
    expect(parsed.sweep).toEqual({ ENTER_TREND_ER: ['0.30', '0.42'] });
    expect(parsed.env).toEqual({});
  });

  test('the same value twice is one run, not an error', () => {
    const parsed = parseOverrideText('STOP_PCT=0.01\nSTOP_PCT=0.01');
    expect(parsed.error).toBeNull();
    expect(parsed.env).toEqual({ STOP_PCT: '0.01' });
  });

  test('one line can carry the whole sweep', () => {
    expect(parseOverrideText('BB_K=2;2.5;3').sweep).toEqual({ BB_K: ['2', '2.5', '3'] });
  });

  test('comments and blank lines are ignored', () => {
    expect(parseOverrideText('# чому саме так\n\nSTOP_PCT=0.01')).toEqual({
      env: { STOP_PCT: '0.01' },
      sweep: {},
      error: null,
    });
  });

  test('a line that is not KEY=value is refused with its number', () => {
    const parsed = parseOverrideText('STOP_PCT=0.01\nщось не те');
    expect(parsed.error).toContain('рядок 2');
  });

  test('a lowercase key is refused: Settings would ignore it', () => {
    expect(parseOverrideText('stop_pct=0.01').error).toContain('налаштування');
  });

  test('a key repeated three times sweeps all three values', () => {
    const parsed = parseOverrideText('ENTER_TREND_ER=0.30\nENTER_TREND_ER=0.42\nENTER_TREND_ER=0.50');
    expect(parsed.error).toBeNull();
    expect(parsed.sweep).toEqual({ ENTER_TREND_ER: ['0.30', '0.42', '0.50'] });
  });

  test('a repeated value is not a second run', () => {
    const parsed = parseOverrideText('ENTER_TREND_ER=0.30;0.42\nENTER_TREND_ER=0.30');
    expect(parsed.error).toBeNull();
    expect(parsed.sweep).toEqual({ ENTER_TREND_ER: ['0.30', '0.42'] });
  });
});

describe('the parameter panel rows', () => {
  test('a row with one value is a plain override', () => {
    expect(parseParamRows([{ key: 'ENTER_TREND_ER', values: '0.30' }])).toEqual({
      env: { ENTER_TREND_ER: '0.30' },
      sweep: {},
      error: null,
    });
  });

  test('a row with several values sweeps that parameter', () => {
    const parsed = parseParamRows([
      { key: 'ENTER_TREND_ER', values: '0.30;0.42' },
      { key: 'STOP_PCT', values: '0.01' },
    ]);
    expect(parsed.sweep).toEqual({ ENTER_TREND_ER: ['0.30', '0.42'] });
    expect(parsed.env).toEqual({ STOP_PCT: '0.01' });
  });

  test('an empty row is not a value: it changes nothing', () => {
    expect(parseParamRows([{ key: 'ENTER_TREND_ER', values: '   ' }]).error).toContain(
      'немає жодного значення',
    );
  });
});

describe('merging the panel and the box', () => {
  test('agreement passes, disagreement is refused', () => {
    const row = parseParamRows([{ key: 'STOP_PCT', values: '0.01' }]);
    expect(mergeOverrides(row, parseOverrideText('RISK_PER_TRADE=0.005')).env).toEqual({
      STOP_PCT: '0.01',
      RISK_PER_TRADE: '0.005',
    });
    const clash = mergeOverrides(row, parseOverrideText('STOP_PCT=0.02'));
    expect(clash.error).toContain('задано двічі');
  });
});

describe('counting the matrix', () => {
  test('two swept keys multiply, because they form a grid', () => {
    expect(sweepCombinations({ A: ['1', '2'], B: ['1', '2', '3'] })).toBe(6);
  });

  test('nothing swept is one run per cell', () => {
    expect(sweepCombinations({})).toBe(1);
  });

  test('a sweep adds one variant per combination, no sweep adds none', () => {
    // Three values give three cells, not a base run plus two: the sweep *is* the variants.
    expect(sweepVariantCount({ ENTER_TREND_ER: ['0.3', '0.4', '0.5'] })).toBe(3);
    expect(sweepVariantCount({ A: ['1', '2'], B: ['1', '2'] })).toBe(4);
    expect(sweepVariantCount({})).toBe(0);
  });

  test('the cap warning appears only past the served limit', () => {
    expect(variantBudgetWarning(8, 8)).toBeNull();
    expect(variantBudgetWarning(9, 8)).toContain('більше за ліміт 8');
    // Before the status query answers, no limit is known and nothing is claimed.
    expect(variantBudgetWarning(99, undefined)).toBeNull();
  });
});
