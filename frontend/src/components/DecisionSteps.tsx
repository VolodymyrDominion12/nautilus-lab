import React from 'react';
import type { TradeDecisionStep } from '../services/api';

/**
 * The robot's reasoning chain for one bar, with each verdict colored and thresholds
 * shown next to the numbers they were measured against.
 *
 * The raw step list is data (`stage`/`component`/`verdict`/`result`/`values`/
 * `thresholds`); this component is the presentation, shared by the Decision Log
 * panel and the trade timeline so a `block` always looks like a block in both.
 */

const VERDICT_STYLES: Record<string, string> = {
  pass: 'text-emerald-300 border-emerald-600/40 bg-emerald-950/30',
  block: 'text-red-300 border-red-600/50 bg-red-950/40',
  modify: 'text-amber-300 border-amber-600/40 bg-amber-950/30',
  emit: 'text-blue-300 border-blue-600/40 bg-blue-950/30',
  skip: 'text-gray-400 border-gray-600/40 bg-gray-800/40',
  info: 'text-gray-400 border-gray-600/40 bg-gray-800/40',
};

const STAGE_LABELS: Record<string, string> = {
  warmup: 'Прогрів',
  regime: 'Режим',
  filter: 'Фільтр',
  strategy: 'Стратегія',
  plan: 'План',
  gate: 'Гейт',
  execution: 'Виконання',
  intrabar: 'У барі',
};

const kv = (values?: Record<string, unknown>): string[] =>
  values ? Object.entries(values).map(([key, value]) => `${key}=${String(value)}`) : [];

export const DecisionSteps: React.FC<{ steps?: TradeDecisionStep[] }> = ({ steps }) => {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="space-y-1.5">
      {steps.map((step, index) => {
        const values = kv(step.values);
        const thresholds = kv(step.thresholds);
        return (
          <div key={index} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="text-[9px] uppercase tracking-wide text-gray-600 w-20 shrink-0">
              {STAGE_LABELS[step.stage ?? ''] ?? step.stage}
            </span>
            <span className="text-gray-200 font-medium">{step.component}</span>
            <span
              className={`text-[9px] px-1.5 py-0.5 rounded border ${
                VERDICT_STYLES[step.verdict ?? ''] ?? 'border-gray-700 text-gray-400'
              }`}
            >
              {step.verdict}
            </span>
            {step.result && <span className="text-amber-200/80">→ {step.result}</span>}
            {values.length > 0 && <span className="text-gray-500">{values.join(', ')}</span>}
            {thresholds.length > 0 && (
              <span className="text-purple-300/80">пороги: {thresholds.join(', ')}</span>
            )}
          </div>
        );
      })}
    </div>
  );
};
