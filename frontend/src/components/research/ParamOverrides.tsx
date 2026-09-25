import React from 'react';

import type { ResearchForm } from '../../lib/researchForm';
import type { StrategySpec } from '../../services/api';

interface ParamOverridesProps {
  form: ResearchForm;
  update: (patch: Partial<ResearchForm>) => void;
  strategy: StrategySpec | undefined;
}

/** Per-run robot parameters that replace the saved .env values, when switched on. */
export const ParamOverrides: React.FC<ParamOverridesProps> = ({ form, update, strategy }) => {
  const { overrideParams, paramOverrides } = form;
  const selectedStrategyInfo = strategy;
  return (
    <div className="border-t border-gray-800/80 pt-4">
      <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
        <input
          type="checkbox"
          checked={overrideParams}
          onChange={(e) => update({ overrideParams: e.target.checked })}
          className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
        />
        Override robot parameters for this run
      </label>
      <p className="text-[10px] text-gray-500 mt-1 ml-6">
        {overrideParams
          ? 'These values replace the saved .env settings for this run only.'
          : 'Off: the run uses the values from the Settings tab (.env).'}
      </p>

      {overrideParams && selectedStrategyInfo && selectedStrategyInfo.params?.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
          {selectedStrategyInfo.params
            .filter((param) => param.env)
            .slice(0, 12)
            .map((param) => (
              <label key={param.env} className="flex flex-col gap-1 text-[11px]">
                <span className="font-mono text-gray-500">
                  {param.env} <span className="text-gray-600">default {String(param.default)}</span>
                </span>
                <input
                  type="text"
                  value={paramOverrides[param.env] ?? ''}
                  onChange={(e) =>
                    update({ paramOverrides: { ...paramOverrides, [param.env]: e.target.value } })
                  }
                  className="bg-gray-950 border border-gray-800 rounded-lg p-2 font-mono text-gray-200"
                />
              </label>
            ))}
        </div>
      )}
    </div>
  );
};
