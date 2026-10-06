/**
 * Pure logic of the batch form's parameter panel: what the researcher typed about parameters,
 * turned into the two things the API understands — `env` (one value for every cell) and
 * `sweep` (one key, several values: one run per value).
 *
 * Why a parser and not just a textarea: a key repeated twice used to be *silently* collapsed
 * to its last value (`env[key] = value`), so "run it with 0.3 and with 0.42" quietly became
 * one run. Here a repeat means a dimension of the matrix — which is what it reads like, and
 * what the same syntax means in the panel's rows.
 *
 * The split of work with the API: the names of the sweep variants, the cross product, the
 * `MAX_VARIANTS` cap and every key check live in `application/batch_plan.py` — one
 * implementation for the form, the CLI and any script. This module only reads what a human
 * typed, and refuses the shapes it can already see are wrong.
 */

/** `KEY=value` for every cell, or `KEY=a;b` / a repeated key for a sweep. */
export type OverrideValues = Record<string, string>;

export interface OverrideParse {
  /** One value per key: applies to every cell of the batch. */
  env: OverrideValues;
  /** Several values per key: every cell runs once per combination. */
  sweep: Record<string, string[]>;
  error: string | null;
}

/** A settings key as `Settings` spells it (`DRAWDOWN_COOLDOWN_DAYS`), never lowercase. */
const SETTINGS_NAME = /^[A-Z][A-Z0-9_]*$/;

/** Within one row/line `;` separates values, so a comma stays a literal comma. */
export const VALUE_SEPARATOR = ';';

export const EMPTY_PARSE: OverrideParse = { env: {}, sweep: {}, error: null };

/**
 * Split one line's right-hand side into values.
 *
 * A comma is deliberately NOT a separator: `REGIME_LEGS=uptrend,range` is one string value
 * (docs/31), and splitting it would turn a switch into a sweep of two pieces of nonsense.
 */
export const splitValues = (raw: string): string[] =>
  raw
    .split(VALUE_SEPARATOR)
    .map((value) => value.trim())
    .filter((value) => value.length > 0);

/** One line or one panel row, before keys are grouped. */
interface Entry {
  key: string;
  values: string[];
  /** Where it came from, for the error message (`рядок 3`, `панель`). */
  where: string;
}

/**
 * Group entries by key and decide what each key means.
 *
 * Repeats *within one source* accumulate: `ENTER_TREND_ER=0.30` twice with two values is the
 * sweep the researcher asked for, and the same value twice is simply one value. One value
 * stays in `env` (a plain override costs no extra run), several become a sweep.
 */
function finish(entries: Entry[]): OverrideParse {
  const order: string[] = [];
  const grouped = new Map<string, { values: string[]; where: string }>();
  for (const entry of entries) {
    if (!SETTINGS_NAME.test(entry.key)) {
      return {
        ...EMPTY_PARSE,
        error: `${entry.where}: «${entry.key}» не схоже на назву налаштування (KEY=value)`,
      };
    }
    let bucket = grouped.get(entry.key);
    if (!bucket) {
      bucket = { values: [], where: entry.where };
      grouped.set(entry.key, bucket);
      order.push(entry.key);
    }
    for (const value of entry.values) {
      if (!bucket.values.includes(value)) bucket.values.push(value);
    }
  }
  const parse: OverrideParse = { env: {}, sweep: {}, error: null };
  for (const key of order) {
    const bucket = grouped.get(key) as { values: string[]; where: string };
    if (bucket.values.length === 0) {
      return { ...EMPTY_PARSE, error: `${bucket.where}: у ${key} немає жодного значення` };
    }
    if (bucket.values.length === 1) {
      parse.env[key] = bucket.values[0] as string;
    } else {
      parse.sweep[key] = bucket.values;
    }
  }
  return parse;
}

/** The panel's rows: one key and the values typed for it (`;`-separated). */
export const parseParamRows = (rows: { key: string; values: string }[]): OverrideParse =>
  finish(
    rows.map((row) => ({ key: row.key.trim(), values: splitValues(row.values), where: 'панель' })),
  );

/**
 * The free-text box: `KEY=value`, one per line.
 *
 * A repeated key is a sweep dimension (`DONCHIAN_PERIOD=20` then `=40` → two runs), and
 * `KEY=a;b` says the same thing on one line. `#` starts a comment.
 */
export const parseOverrideText = (text: string): OverrideParse => {
  const entries: Entry[] = [];
  const lines = text.split('\n');
  for (let index = 0; index < lines.length; index += 1) {
    const line = (lines[index] as string).trim();
    if (!line || line.startsWith('#')) continue;
    const where = `рядок ${index + 1}`;
    const at = line.indexOf('=');
    if (at <= 0) {
      return { ...EMPTY_PARSE, error: `${where}: очікую KEY=value, а не «${line}»` };
    }
    entries.push({
      key: line.slice(0, at).trim(),
      values: splitValues(line.slice(at + 1)),
      where,
    });
  }
  return finish(entries);
};

const sameValues = (left: string[], right: string[]): boolean =>
  left.length === right.length && [...left].sort().join('\u0000') === [...right].sort().join('\u0000');

/**
 * Both sources at once: the panel's rows and the free-text lines.
 *
 * A key named by both sources is fine while they agree; asking for two different sets of
 * values for one key is refused, because guessing which one the researcher meant is how a
 * batch runs the wrong matrix for hours.
 */
export const mergeOverrides = (...parses: OverrideParse[]): OverrideParse => {
  const merged: OverrideParse = { env: {}, sweep: {}, error: null };
  for (const parse of parses) {
    if (parse.error) return parse;
    for (const [key, value] of Object.entries(parse.env)) {
      const known = merged.sweep[key] ?? (merged.env[key] === undefined ? null : [merged.env[key] as string]);
      if (known !== null && !sameValues(known, [value])) {
        return { ...EMPTY_PARSE, error: `${key} задано двічі з різними значеннями — лиши одне` };
      }
      if (known === null) merged.env[key] = value;
    }
    for (const [key, values] of Object.entries(parse.sweep)) {
      const known = merged.sweep[key] ?? (merged.env[key] === undefined ? null : [merged.env[key] as string]);
      if (known !== null) {
        if (!sameValues(known, values)) {
          return { ...EMPTY_PARSE, error: `${key} задано двічі з різними значеннями — лиши одне` };
        }
        continue;
      }
      delete merged.env[key];
      merged.sweep[key] = values;
    }
  }
  return merged;
};

/**
 * How many runs one cell of the matrix becomes. Combinations multiply, because two swept keys
 * are a grid: `2 x 3` values is six runs, not three (`batch_plan.sweep_variants`).
 */
export const sweepCombinations = (sweep: Record<string, string[]>): number =>
  Object.values(sweep).reduce((total, values) => total * Math.max(values.length, 1), 1);

/**
 * How many variants a sweep adds to the matrix — 0 without a sweep, and `N` for `N` values.
 *
 * Not `combinations - 1`: the sweep *is* the variants (a swept key of three values gives three
 * cells per robot × symbol, not a base run plus two), which is why `sweepCombinations` starts at
 * one and this one starts at zero.
 */
export const sweepVariantCount = (sweep: Record<string, string[]>): number =>
  Object.keys(sweep).length === 0 ? 0 : sweepCombinations(sweep);

/** What to say when the matrix no longer fits the planner's `MAX_VARIANTS` (null = it fits). */
export const variantBudgetWarning = (
  count: number,
  maxVariants: number | undefined,
): string | null => {
  if (!maxVariants || count <= maxVariants) return null;
  return (
    `Варіантів ${count} — більше за ліміт ${maxVariants}: кожен множить усю матрицю ` +
    '(роботи × інструменти). Сервер відмовить; прибери значення.'
  );
};
