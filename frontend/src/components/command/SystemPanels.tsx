import React from 'react';
import { Brain, Database } from 'lucide-react';

import { describeStaleness } from '../../lib/format';
import type { CommandCenterResponse } from '../../services/api';

/** Trained models, and the catalog, robots and data freshness of this server. */
export const SystemPanels: React.FC<{ data: CommandCenterResponse | null }> = ({ data }) => {
  const staleness = describeStaleness(data?.catalog_last_date);
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Brain className="w-5 h-5 text-emerald-400" />
          <h3 className="font-semibold text-gray-100">Trained models</h3>
        </div>
        {(data?.models?.length ?? 0) === 0 ? (
          <p className="text-sm text-gray-500">No models in models/</p>
        ) : (
          <div className="space-y-2">
            {data?.models?.map((model) => (
              <div
                key={model.path}
                className="flex justify-between text-sm p-2 rounded-lg bg-gray-950 border border-gray-800 font-mono"
              >
                <span className="text-gray-200">{model.filename}</span>
                <span className="text-gray-500">{model.size_kb} KB</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Database className="w-5 h-5 text-cyan-400" />
          <h3 className="font-semibold text-gray-100">System</h3>
        </div>
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-gray-500">Catalog</dt>
            <dd className="text-gray-300 font-mono truncate max-w-[60%]">
              {data?.catalog_path ?? '—'}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Robots wired</dt>
            <dd className="text-gray-300">
              {data?.robots?.wired?.length ?? 0} / {data?.robots?.total ?? 0}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-gray-500">Wired names</dt>
            <dd className="text-gray-300 font-mono text-[11px] text-right">
              {data?.robots?.wired?.join(', ') ?? '—'}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Live trading</dt>
            <dd className="text-emerald-400">disabled by design</dd>
          </div>
          {data?.catalog_last_date && (
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500">Data last date</dt>
              <dd className="flex items-center gap-2">
                <span className="text-gray-300 font-mono text-xs">
                  {data.catalog_last_date.slice(0, 19)}
                </span>
                {staleness.level !== 'unknown' && (
                  <span
                    className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
                      staleness.level === 'current'
                        ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50'
                        : staleness.level === 'aging'
                          ? 'bg-amber-950/60 text-amber-300 border-amber-800/50'
                          : 'bg-red-950/60 text-red-300 border-red-800/50'
                    }`}
                  >
                    {staleness.days}d old
                  </span>
                )}
              </dd>
            </div>
          )}
          {staleness.level === 'stale' && (
            <p className="text-[11px] text-red-300/90">
              The newest bar is {staleness.days} days old, so a walk-forward here studies the
              past rather than the recent market. Run an incremental klines ingest before
              reporting a result.
            </p>
          )}
          {data?.catalog_total_bars != null && data.catalog_total_bars > 0 && (
            <div className="flex justify-between gap-3">
              <dt className="text-gray-500">Total bars stored</dt>
              <dd className="text-gray-300 font-mono text-xs">
                {data.catalog_total_bars.toLocaleString()}
              </dd>
            </div>
          )}
        </dl>
      </div>
    </div>
  );
};
