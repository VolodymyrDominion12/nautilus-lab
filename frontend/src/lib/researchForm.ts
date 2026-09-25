/**
 * The Research Lab form as one value, and the pure steps that change it.
 *
 * It used to be 26 `useState` hooks inside a 57 KB component. Presets, archived runs,
 * reset and persistence each touched some of them by hand, and nothing could test those
 * steps without rendering the page. Here each is a function from form to form, so
 * `researchForm.test.ts` checks them directly (docs/27 E-2.5).
 */
import type { ResearchRunConfig, ResearchRunParams } from '../services/api';
import type { CliCommandInput } from './research';

export type DataSource = 'catalog' | 'synthetic';
export type WindowMode = 'fraction' | 'custom';

export interface ResearchForm {
  robot: string;
  source: DataSource;
  bars: number;
  folds: number;
  isFraction: number;
  embargoBars: number;
  useOptuna: boolean;
  optunaTrials: number;
  usePbo: boolean;
  pboBlocks: number;
  barVpin: boolean;
  tickVpin: boolean;
  hawkes: boolean;
  stressSlice: string;
  generateTearsheet: boolean;
  journal: boolean;
  notify: boolean;
  fullSample: boolean;
  windowMode: WindowMode;
  isStart: string;
  isEnd: string;
  oosStart: string;
  oosEnd: string;
  overrideParams: boolean;
  paramOverrides: Record<string, string>;
  instrumentId: string;
}

export const FORM_STORAGE_KEY = 'nautilus-lab:research-form:v2';

export const FORM_DEFAULTS: Omit<ResearchForm, 'robot'> = {
  source: 'catalog',
  bars: 3000,
  folds: 2,
  isFraction: 0.7,
  embargoBars: 10,
  useOptuna: false,
  optunaTrials: 20,
  usePbo: false,
  pboBlocks: 8,
  barVpin: false,
  tickVpin: false,
  hawkes: false,
  stressSlice: '',
  generateTearsheet: true,
  journal: false,
  notify: false,
  fullSample: false,
  windowMode: 'fraction',
  isStart: '',
  isEnd: '',
  oosStart: '',
  oosEnd: '',
  overrideParams: false,
  paramOverrides: {},
  instrumentId: '',
};

/** The saved form, completed with defaults. A field the saved copy lacks is not lost. */
export function restoreForm(saved: Partial<ResearchForm>, robot: string): ResearchForm {
  const known = Object.fromEntries(
    Object.entries(saved).filter(([key, value]) => key in FORM_DEFAULTS && value != null),
  ) as Partial<ResearchForm>;
  return { ...FORM_DEFAULTS, robot: saved.robot || robot, ...known };
}

export function loadSavedForm(storage: Pick<Storage, 'getItem'> | undefined): Partial<ResearchForm> {
  try {
    const raw = storage?.getItem(FORM_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? (parsed as Partial<ResearchForm>) : {};
  } catch {
    return {};
  }
}

/** A preset sets only what it names; everything else stays as the user left it. */
export function applyPreset(form: ResearchForm, preset: Partial<ResearchForm>): ResearchForm {
  const defined = Object.fromEntries(
    Object.entries(preset).filter(([, value]) => value !== undefined),
  ) as Partial<ResearchForm>;
  return { ...form, ...defined };
}

/**
 * The form an archived run was launched with. `warning` is set for runs archived before
 * the full config was captured (config_version < 2): only their basic fields come back.
 */
export function applyArchivedRun(
  form: ResearchForm,
  config: ResearchRunConfig,
): { form: ResearchForm; warning: string | null } {
  const next: ResearchForm = { ...form };
  if (config.robot) next.robot = config.robot;
  if (config.source === 'catalog' || config.source === 'synthetic') next.source = config.source;
  if (typeof config.bars === 'number') next.bars = config.bars;
  if (typeof config.folds === 'number') next.folds = config.folds;
  if (config.is_fraction) next.isFraction = Number(config.is_fraction);
  if (typeof config.embargo_bars === 'number') next.embargoBars = config.embargo_bars;
  if (typeof config.use_optuna === 'boolean') next.useOptuna = config.use_optuna;
  if (typeof config.optuna_trials === 'number') next.optunaTrials = config.optuna_trials;
  if (typeof config.pbo === 'boolean') next.usePbo = config.pbo;
  if (typeof config.pbo_blocks === 'number') next.pboBlocks = config.pbo_blocks;
  if (typeof config.bar_vpin === 'boolean') next.barVpin = config.bar_vpin;
  if (typeof config.tick_vpin === 'boolean') next.tickVpin = config.tick_vpin;
  if (typeof config.hawkes === 'boolean') next.hawkes = config.hawkes;
  if (typeof config.stress_slice === 'string') next.stressSlice = config.stress_slice;
  if (typeof config.generate_tearsheet === 'boolean') next.generateTearsheet = config.generate_tearsheet;
  if (typeof config.journal === 'boolean') next.journal = config.journal;
  if (typeof config.notify === 'boolean') next.notify = config.notify;
  if (typeof config.full_sample === 'boolean') next.fullSample = config.full_sample;
  if (config.instrument_id) next.instrumentId = config.instrument_id;
  if (config.is_start) {
    next.windowMode = 'custom';
    next.isStart = config.is_start;
    next.isEnd = config.is_end ?? '';
    next.oosStart = config.oos_start ?? '';
    next.oosEnd = config.oos_end ?? '';
  } else {
    next.windowMode = 'fraction';
  }
  if (config.param_overrides && Object.keys(config.param_overrides).length > 0) {
    next.overrideParams = true;
    next.paramOverrides = config.param_overrides;
  } else {
    next.overrideParams = false;
  }
  return { form: next, warning: archivedRunWarning(config) };
}

/** Runs archived before the full config was captured restore only their basic fields. */
export function archivedRunWarning(config: ResearchRunConfig): string | null {
  return config.config_version === 2
    ? null
    : 'This archived run predates full config capture, so only its basic fields can be restored.';
}

/** "Reset form": the split and the overrides go back to defaults; the robot and data stay. */
export function resetSplit(form: ResearchForm): ResearchForm {
  return {
    ...form,
    folds: FORM_DEFAULTS.folds,
    isFraction: FORM_DEFAULTS.isFraction,
    embargoBars: FORM_DEFAULTS.embargoBars,
    paramOverrides: {},
    overrideParams: false,
  };
}

/** What POST /api/research receives. Fields that do not apply to this mode are left out. */
export function toRunParams(
  form: ResearchForm,
  instrumentId: string | undefined,
  catalogPath: string | undefined,
): ResearchRunParams {
  const custom = form.windowMode === 'custom';
  const catalog = form.source === 'catalog';
  return {
    robot: form.robot,
    source: form.source,
    bars: form.source === 'synthetic' ? form.bars : undefined,
    folds: form.folds,
    is_fraction: form.isFraction,
    embargo_bars: form.embargoBars,
    use_optuna: form.useOptuna,
    optuna_trials: form.useOptuna ? form.optunaTrials : undefined,
    pbo: form.usePbo,
    pbo_blocks: form.usePbo ? form.pboBlocks : undefined,
    bar_vpin: form.barVpin,
    tick_vpin: form.tickVpin,
    hawkes: form.hawkes,
    stress_slice: form.stressSlice || undefined,
    generate_tearsheet: form.generateTearsheet,
    journal: form.journal,
    notify: form.notify,
    full_sample: catalog ? form.fullSample : false,
    instrument_id: catalog ? instrumentId : undefined,
    is_start: custom ? form.isStart || undefined : undefined,
    is_end: custom ? form.isEnd || undefined : undefined,
    oos_start: custom ? form.oosStart || undefined : undefined,
    oos_end: custom ? form.oosEnd || undefined : undefined,
    param_overrides: form.overrideParams ? form.paramOverrides : {},
    catalog_path: catalogPath || undefined,
  };
}

/** The input of `cliCommand`, the "Copy CLI" button. */
export function toCliInput(
  form: ResearchForm,
  instrumentId: string | undefined,
  catalogPath: string | undefined,
): CliCommandInput {
  return {
    robot: form.robot,
    source: form.source,
    bars: form.bars,
    folds: form.folds,
    isFraction: form.isFraction,
    embargoBars: form.embargoBars,
    useOptuna: form.useOptuna,
    optunaTrials: form.optunaTrials,
    pbo: form.usePbo,
    pboBlocks: form.pboBlocks,
    barVpin: form.barVpin,
    tickVpin: form.tickVpin,
    hawkes: form.hawkes,
    stressSlice: form.stressSlice,
    generateTearsheet: form.generateTearsheet,
    journal: form.journal,
    notify: form.notify,
    fullSample: form.fullSample,
    catalogPath,
    instrumentId,
    windowMode: form.windowMode,
    isStart: form.isStart,
    isEnd: form.isEnd,
    oosStart: form.oosStart,
    oosEnd: form.oosEnd,
  };
}

/** Spec defaults for the override inputs, keyed by env name. */
export function specDefaults(params: { env?: string; default?: unknown }[]): Record<string, string> {
  const defaults: Record<string, string> = {};
  for (const param of params) {
    if (param.env && param.default != null && param.default !== '') {
      defaults[param.env] = String(param.default);
    }
  }
  return defaults;
}
