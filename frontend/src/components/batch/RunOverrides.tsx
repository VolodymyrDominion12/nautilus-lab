import React from 'react';

import { overridePairs } from '../../lib/batch';

interface RunOverridesProps {
  /** The settings this cell was launched with (`batch.json` → `cells[].env`). */
  env: Record<string, string> | undefined;
}

/**
 * What this run was actually told — the batch's overrides for this cell.
 *
 * The values were already stored in `batch.json` and served by `GET …/runs/{cell}`, but the page
 * never showed them: a cell reached its OOS numbers without the screen saying which parameter
 * combination produced them. With a sweep that is no longer optional reading — six cells differ
 * only in these values, and the cell id alone (`…__ENTER_TREND_ER_0_42_02`) is a name, not a
 * configuration.
 */
export const RunOverrides: React.FC<RunOverridesProps> = ({ env }) => {
  const pairs = overridePairs(env);
  if (pairs.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="text-gray-500 uppercase tracking-wide text-[10px]">Параметри прогону</span>
      {pairs.map(([key, value]) => (
        <span
          key={key}
          className="px-1.5 py-0.5 rounded bg-gray-950 border border-gray-800 font-mono text-gray-300"
        >
          {key}={value}
        </span>
      ))}
    </div>
  );
};
