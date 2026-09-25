/**
 * The Research Lab form steps (docs/27 E-2.5): what a preset, an archived run and a
 * reset do to the form, and what a run request carries in each mode.
 */
import { describe, expect, test } from 'vitest';

import {
  FORM_DEFAULTS,
  FORM_STORAGE_KEY,
  applyArchivedRun,
  applyPreset,
  loadSavedForm,
  resetSplit,
  restoreForm,
  specDefaults,
  toCliInput,
  toRunParams,
} from './researchForm';
import type { ResearchForm } from './researchForm';
import { cliCommand } from './research';

const base: ResearchForm = { ...FORM_DEFAULTS, robot: 'regime' };

describe('restoring the saved form', () => {
  test('missing fields fall back to defaults, the saved ones win', () => {
    const form = restoreForm({ folds: 4, useOptuna: true }, 'ema');
    expect(form.folds).toBe(4);
    expect(form.useOptuna).toBe(true);
    expect(form.isFraction).toBe(0.7);
    expect(form.robot).toBe('ema');
  });

  test('a saved robot beats the default robot', () => {
    expect(restoreForm({ robot: 'vpin_momentum' }, 'regime').robot).toBe('vpin_momentum');
  });

  test('unknown keys and nulls from an older version are dropped', () => {
    const saved = { folds: null, legacy: 'x' } as unknown as Partial<ResearchForm>;
    const form = restoreForm(saved, 'regime');
    expect(form.folds).toBe(FORM_DEFAULTS.folds);
    expect('legacy' in form).toBe(false);
  });

  test('broken or missing storage gives an empty form, not an exception', () => {
    expect(loadSavedForm(undefined)).toEqual({});
    expect(loadSavedForm({ getItem: () => '{not json' })).toEqual({});
    expect(loadSavedForm({ getItem: () => 'null' })).toEqual({});
    const stored = JSON.stringify({ folds: 8 });
    expect(loadSavedForm({ getItem: (key) => (key === FORM_STORAGE_KEY ? stored : null) })).toEqual({
      folds: 8,
    });
  });
});

describe('presets and reset', () => {
  test('a preset changes only the fields it names', () => {
    const form = applyPreset({ ...base, journal: true }, { folds: 4, usePbo: true, bars: undefined });
    expect(form.folds).toBe(4);
    expect(form.usePbo).toBe(true);
    expect(form.journal).toBe(true);
    expect(form.bars).toBe(base.bars);
  });

  test('reset restores the split and drops overrides, keeping robot and data', () => {
    const form = resetSplit({
      ...base,
      robot: 'ema',
      source: 'synthetic',
      folds: 8,
      isFraction: 0.5,
      embargoBars: 0,
      overrideParams: true,
      paramOverrides: { A: '1' },
    });
    expect([form.folds, form.isFraction, form.embargoBars]).toEqual([2, 0.7, 10]);
    expect(form.overrideParams).toBe(false);
    expect(form.paramOverrides).toEqual({});
    expect([form.robot, form.source]).toEqual(['ema', 'synthetic']);
  });
});

describe('restoring an archived run', () => {
  test('explicit dates switch to the custom window', () => {
    const { form, warning } = applyArchivedRun(base, {
      config_version: 2,
      robot: 'ema',
      is_fraction: '0.6',
      is_start: '2024-01-01',
      is_end: '2024-06-01',
      oos_start: '2024-06-02',
      param_overrides: { EMA_FAST: '12' },
    });
    expect(warning).toBeNull();
    expect(form.robot).toBe('ema');
    expect(form.isFraction).toBe(0.6);
    expect(form.windowMode).toBe('custom');
    expect([form.isStart, form.isEnd, form.oosStart, form.oosEnd]).toEqual([
      '2024-01-01',
      '2024-06-01',
      '2024-06-02',
      '',
    ]);
    expect(form.overrideParams).toBe(true);
    expect(form.paramOverrides).toEqual({ EMA_FAST: '12' });
  });

  test('a run without dates or overrides turns both off', () => {
    const start = { ...base, windowMode: 'custom' as const, overrideParams: true };
    const { form } = applyArchivedRun(start, { config_version: 2 });
    expect(form.windowMode).toBe('fraction');
    expect(form.overrideParams).toBe(false);
  });

  test('an old archive says that only part of it came back', () => {
    expect(applyArchivedRun(base, { robot: 'ema' }).warning).toMatch(/predates full config/);
  });

  test('an unknown source is ignored rather than trusted', () => {
    expect(applyArchivedRun(base, { source: 'parquet?' }).form.source).toBe(base.source);
  });
});

describe('the run request', () => {
  test('a catalog run sends the instrument and no bar count', () => {
    const params = toRunParams(base, 'ETHUSDT.SIM', 'catalog');
    expect(params.instrument_id).toBe('ETHUSDT.SIM');
    expect(params.bars).toBeUndefined();
    expect(params.catalog_path).toBe('catalog');
    expect(params.param_overrides).toEqual({});
  });

  test('a synthetic run sends the bar count, no instrument, never full-sample', () => {
    const params = toRunParams({ ...base, source: 'synthetic', fullSample: true }, 'X', '');
    expect(params.bars).toBe(base.bars);
    expect(params.instrument_id).toBeUndefined();
    expect(params.full_sample).toBe(false);
    expect(params.catalog_path).toBeUndefined();
  });

  test('dates are sent only in the custom window mode', () => {
    const dated = { ...base, isStart: '2024-01-01', oosEnd: '2024-12-31' };
    expect(toRunParams(dated, undefined, undefined).is_start).toBeUndefined();
    const custom = toRunParams({ ...dated, windowMode: 'custom' }, undefined, undefined);
    expect(custom.is_start).toBe('2024-01-01');
    expect(custom.is_end).toBeUndefined();
    expect(custom.oos_end).toBe('2024-12-31');
  });

  test('trial and block counts go only with their gate', () => {
    expect(toRunParams(base, undefined, undefined).optuna_trials).toBeUndefined();
    expect(toRunParams({ ...base, useOptuna: true }, undefined, undefined).optuna_trials).toBe(20);
    expect(toRunParams({ ...base, usePbo: true }, undefined, undefined).pbo_blocks).toBe(8);
  });

  test('overrides are sent only while the override switch is on', () => {
    const form = { ...base, paramOverrides: { A: '1' } };
    expect(toRunParams(form, undefined, undefined).param_overrides).toEqual({});
    expect(
      toRunParams({ ...form, overrideParams: true }, undefined, undefined).param_overrides,
    ).toEqual({ A: '1' });
  });

  test('the CLI command reproduces the same run', () => {
    const command = cliCommand(toCliInput({ ...base, folds: 4 }, 'ETHUSDT.SIM', 'catalog'));
    expect(command).toContain('--robot regime');
    expect(command).toContain('--catalog catalog');
    expect(command).toContain('--folds 4');
  });
});

test('spec defaults skip empty values and parameters without an env name', () => {
  expect(
    specDefaults([
      { env: 'A', default: 5 },
      { env: 'B', default: '' },
      { env: 'C', default: null },
      { default: 1 },
    ]),
  ).toEqual({ A: '5' });
});
