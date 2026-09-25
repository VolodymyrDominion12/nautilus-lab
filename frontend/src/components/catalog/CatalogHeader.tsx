import React from 'react';
import { Database, RefreshCw } from 'lucide-react';

import type { CatalogResponse, CatalogSummary } from '../../services/api';

interface CatalogHeaderProps {
  catalog: CatalogResponse | undefined;
  catalogOptions: CatalogSummary[];
  selectedCatalogPath: string;
  onCatalogChange: (path: string) => void;
  loading: boolean;
  onRefresh: () => void;
}

/** Which catalog is selected, what it holds overall, and the refresh button. */
export const CatalogHeader: React.FC<CatalogHeaderProps> = ({
  catalog,
  catalogOptions,
  selectedCatalogPath,
  onCatalogChange,
  loading,
  onRefresh,
}) => {
  const instruments = catalog?.instruments ?? [];
  const totalBars = instruments.reduce((sum, item) => sum + item.bars_count, 0);
  const firstOverall = instruments
    .map((item) => item.first_date)
    .filter((value): value is string => Boolean(value))
    .sort()[0];
  const lastOverall = instruments
    .map((item) => item.last_date)
    .filter((value): value is string => Boolean(value))
    .sort()
    .reverse()[0];

  return (
  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gray-900 border border-gray-800 p-6 rounded-2xl">
    <div className="flex-1">
      <div className="flex items-center gap-2">
        <Database className="w-6 h-6 text-blue-400" />
        <h2 className="text-xl font-bold text-gray-100">Parquet Data Catalog</h2>
        {catalog?.bar_interval && (
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-gray-950 text-gray-300 border-gray-800">
            {catalog.bar_interval} bars
          </span>
        )}
      </div>
      <p className="text-sm text-gray-400 mt-1">
        One catalog directory holds one bar interval. Selection here drives research, ML and the
        charts below.
      </p>
      <div className="mt-3 flex flex-col sm:flex-row gap-2 sm:items-center">
        <label className="text-xs text-gray-500">Catalog path</label>
        <select
          value={selectedCatalogPath}
          onChange={(e) => onCatalogChange(e.target.value)}
          className="bg-gray-950 border border-gray-800 text-sm text-gray-200 rounded-xl px-3 py-2 font-mono min-w-[240px]"
        >
          {catalogOptions.map((item) => (
            <option key={item.path} value={item.path}>
              {item.path} ({item.total_instruments} inst.)
            </option>
          ))}
          {catalogOptions.length === 0 && (
            <option value={selectedCatalogPath}>{selectedCatalogPath || 'catalog'}</option>
          )}
        </select>
      </div>

      {instruments.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] font-mono text-gray-400">
          <span>
            instruments: <span className="text-gray-200">{catalog?.total_instruments ?? 0}</span>
          </span>
          <span>
            bars: <span className="text-gray-200">{totalBars.toLocaleString()}</span>
          </span>
          {firstOverall && lastOverall && (
            <span>
              coverage:{' '}
              <span className="text-gray-200">
                {firstOverall.slice(0, 10)} → {lastOverall.slice(0, 10)}
              </span>
            </span>
          )}
        </div>
      )}
    </div>

    <button
      type="button"
      onClick={onRefresh}
      disabled={loading}
      className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium rounded-xl transition-colors self-start md:self-auto"
    >
      <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
      Refresh
    </button>
  </div>
  );
};
