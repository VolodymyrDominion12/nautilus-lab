import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { strategiesQuery } from '../../services/queries';
import { parseOverrideText, parseParamRows, sweepCombinations } from '../../lib/batchSweep';
import { parseVariants } from '../../lib/batch';
import { InfoTooltip } from '../InfoTooltip';

interface BatchParamPanelProps {
  /** The robots the matrix will run: their specs decide which parameters are offered. */
  robots: string[];
  /** Raw text per settings key; `;` separates the values of a sweep. */
  values: Record<string, string>;
  setValues: (next: Record<string, string>) => void;
  /** The free-text box (`KEY=value`, repeats sweep) and the hypotheses box, moved here. */
  envText: string;
  setEnvText: (v: string) => void;
  variantsText: string;
  setVariantsText: (v: string) => void;
  /** How many variants the matrix already has (hypotheses + sweep combinations). */
  variantCount: number;
  maxVariants: number | undefined;
}

const input = 'bg-gray-950 border border-gray-800 rounded-lg px-2 py-1 text-xs font-mono text-gray-200';

/** The badge on a parameter the walk-forward re-selects on the in-sample block. */
const GridBadge: React.FC<{ grid: number }> = ({ grid }) => (
  <span
    className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30"
    title={
      `Сітка підбору рухає цей параметр на in-sample (${grid} значень у спеці), тож значення, ` +
      'яке ти задаси, буде перебите вибраним на IS і до OOS-прогону не дійде. ' +
      'Такі параметри фіксують не тут, а преєстрацією — див. docs/31.'
    }
  >
    підбирається на IS
  </span>
);

/**
 * The batch's parameters: the shared settings every cell gets, and the values that turn into
 * extra runs.
 *
 * Three things it does that the old single textarea could not:
 *
 * 1. it offers the parameters of the selected robots from their *specs*
 *    (`GET /api/strategies`), with each one's default visible, so nobody has to remember
 *    `DONCHIAN_PERIOD` or read `.env` to find a name;
 * 2. several values (`0.30;0.42`, or the same key twice below) mean several runs — one cell
 *    per value, which is the whole point of a parameter sweep;
 * 3. it says which of those keys the walk-forward re-selects on IS and therefore overwrites:
 *    the value would never reach the run, and the silence about that used to cost a
 *    researcher an afternoon (`application/param_grid.py::gridded_env_names`).
 *
 * The parameters are shared by every cell of the batch — that is what `env` means — so a robot
 * that does not read a key simply ignores it. The panel groups them by the robot whose spec
 * declares them, and `specs/_validator.py` keeps those declarations equal to the code.
 */
export const BatchParamPanel: React.FC<BatchParamPanelProps> = ({
  robots,
  values,
  setValues,
  envText,
  setEnvText,
  variantsText,
  setVariantsText,
  variantCount,
  maxVariants,
}) => {
  const strategies = useQuery(strategiesQuery()).data?.strategies ?? [];
  const specs = robots
    .map((robot) => strategies.find((spec) => spec.name === robot))
    .filter((spec): spec is NonNullable<typeof spec> => Boolean(spec));

  const rowParse = parseParamRows(
    Object.entries(values).map(([key, value]) => ({ key, values: value })),
  );
  const textParse = parseOverrideText(envText);
  const combinations = sweepCombinations({ ...rowParse.sweep, ...textParse.sweep });
  const variantError = parseVariants(variantsText).error;
  const overBudget = maxVariants !== undefined && variantCount > maxVariants;

  const setValue = (key: string, value: string) => setValues({ ...values, [key]: value });

  return (
    <div className="flex flex-col gap-3 border-t border-gray-800 pt-4">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wide text-gray-500">
          Параметри прогонів
        </span>
        <InfoTooltip
          size="xs"
          title="Параметри прогонів"
          content={
            'Значення тут спільні для всіх клітинок пакета (як і поле KEY=value нижче). ' +
            'Кілька значень через «;» — це кілька прогонів: кожне значення отримує власну ' +
            'клітинку. Робот, який цей ключ не читає, просто його ігнорує.'
          }
        />
        {combinations > 1 && (
          <span className="text-[10px] text-blue-300">
            свіп: {combinations} прогонів на клітинку
          </span>
        )}
      </div>

      {specs.length === 0 && (
        <p className="text-[11px] text-gray-500">
          Обери роботів — і тут з'являться їхні параметри зі специфікацій (разом зі значеннями
          за замовчуванням).
        </p>
      )}

      {specs.map((spec) => (
        <details key={spec.name} className="bg-gray-950/60 border border-gray-800 rounded-lg">
          <summary className="cursor-pointer px-3 py-1.5 text-xs text-gray-300">
            <span className="font-mono text-gray-200">{spec.name}</span>
            <span className="text-gray-500">
              {' '}
              · параметрів: {spec.params.length}
              {spec.grid_source === 'default_branch' && ' · сітка: чужа (regime)'}
            </span>
          </summary>
          <div className="px-3 pb-3 pt-1 grid grid-cols-1 md:grid-cols-2 gap-2">
            {spec.params.map((param) => {
              const gridded = (param.grid?.length ?? 0) > 0;
              const raw = values[param.env] ?? '';
              return (
                <label key={param.env} className="flex flex-col gap-0.5">
                  <span className="flex items-center gap-1.5 text-[10px] font-mono text-gray-500">
                    {param.env}
                    <span className="text-gray-600">default {String(param.default)}</span>
                    {gridded && <GridBadge grid={param.grid?.length ?? 0} />}
                  </span>
                  <input
                    className={`${input} ${gridded ? 'border-amber-900/60' : ''}`}
                    placeholder="значення або 0.3;0.4"
                    value={raw}
                    onChange={(e) => setValue(param.env, e.target.value)}
                    title={param.description ?? undefined}
                  />
                </label>
              );
            })}
          </div>
        </details>
      ))}

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
        Ще налаштування: KEY=value, по рядку (повторення ключа = окремий прогін)
        <textarea
          className={`${input} h-16`}
          placeholder={'BACKTEST_DAYS=30\nENTER_TREND_ER=0.30\nENTER_TREND_ER=0.42'}
          value={envText}
          onChange={(e) => setEnvText(e.target.value)}
        />
      </label>

      <label className="flex flex-col gap-1 text-[10px] uppercase tracking-wide text-gray-500">
        Варіанти (гіпотези): [НАЗВА] і KEY=value під нею — кожен прогін виконається для кожного
        варіанта
        <textarea
          className={`${input} h-20 ${variantError ? 'border-red-800' : ''}`}
          placeholder={'[H0]\nREGIME_LEGS=uptrend,downtrend\n\n[H1]\nREGIME_LEGS=uptrend,downtrend\nENTRY_FILTER_HTF_TREND=true'}
          value={variantsText}
          onChange={(e) => setVariantsText(e.target.value)}
        />
      </label>

      {variantError && <div className="text-xs text-red-400">{variantError}</div>}
      {rowParse.error && <div className="text-xs text-red-400">{rowParse.error}</div>}
      {textParse.error && <div className="text-xs text-red-400">{textParse.error}</div>}
      {overBudget && (
        <div className="text-xs text-amber-400">
          Варіантів {variantCount} — більше за ліміт {maxVariants}: кожен множить усю матрицю.
          Сервер відмовить; прибери значення.
        </div>
      )}
    </div>
  );
};
