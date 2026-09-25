import React from 'react';
import { Settings2 } from 'lucide-react';

import type { ResearchSummary } from '../../services/api';

/** The conditions a finished run used, as archived with it. */
export const RunConditions: React.FC<{ summary: ResearchSummary }> = ({ summary }) => (
  <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 flex flex-col gap-2">
    <div className="flex items-center gap-2">
      <Settings2 className="w-4 h-4 text-gray-400" />
      <h3 className="text-xs font-bold text-gray-100">Conditions of this run</h3>
      <span className="text-[10px] text-gray-500">
        archived in reports/history, restorable from the history panel
      </span>
    </div>
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono text-gray-400">
      <span>run: {summary.run_type}</span>
      <span>source: {summary.source ?? 'n/a'}</span>
      {summary.config?.folds != null && <span>folds: {summary.config.folds}</span>}
      {summary.config?.is_fraction && <span>is_fraction: {summary.config.is_fraction}</span>}
      {summary.config?.embargo_bars != null && (
        <span>embargo: {summary.config.embargo_bars}</span>
      )}
      <span>optuna: {String(summary.config?.use_optuna ?? false)}</span>
      <span>pbo: {String(summary.config?.pbo ?? false)}</span>
      <span>vpin: {String(summary.config?.bar_vpin ?? false)}</span>
      {summary.config?.stress_slice && <span>slice: {summary.config.stress_slice}</span>}
      {summary.config?.instrument_id && <span>instrument: {summary.config.instrument_id}</span>}
      {summary.starting_equity != null && (
        <span>starting equity: ${summary.starting_equity.toLocaleString()}</span>
      )}
      {summary.config?.param_overrides &&
        Object.keys(summary.config.param_overrides).length > 0 && (
          <span className="text-amber-400/80">
            overrides: {Object.entries(summary.config.param_overrides)
              .map(([key, value]) => `${key}=${value}`)
              .join(' ')}
          </span>
        )}
    </div>
  </div>
);
