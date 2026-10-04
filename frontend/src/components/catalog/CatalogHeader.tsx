import React from 'react';
import { BarChart2, Database, Download, LayoutGrid, RefreshCw, Table } from 'lucide-react';

import type { CatalogResponse, CatalogSummary } from '../../services/api';

export type CatalogViewMode = 'cards' | 'matrix' | 'details' | 'ingest';

interface CatalogHeaderProps {
  catalog: CatalogResponse | undefined;
  catalogOptions: CatalogSummary[];
  selectedCatalogPath: string;
  onCatalogChange: (path: string) => void;
  loading: boolean;
  onRefresh: () => void;
  viewMode: CatalogViewMode;
  onViewModeChange: (mode: CatalogViewMode) => void;
}

/** Which catalog is selected, view mode selector, and overall metrics. */
export const CatalogHeader: React.FC<CatalogHeaderProps> = ({
  catalog,
  catalogOptions,
  selectedCatalogPath,
  onCatalogChange,
  loading,
  onRefresh,
  viewMode,
  onViewModeChange,
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
    <div className="flex flex-col gap-4 bg-gray-900 border border-gray-800 p-5 rounded-2xl">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <Database className="w-6 h-6 text-blue-400" />
            <h2 className="text-xl font-bold text-gray-100">Parquet Data Catalogs</h2>
            {catalog?.bar_interval && (
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-emerald-950/70 text-emerald-300 border-emerald-800/60 font-semibold">
                {catalog.bar_interval} bars
              </span>
            )}
            {catalog?.market_type && catalog.market_type !== 'unknown' && (
              <span
                className={`text-[10px] font-semibold tracking-wider px-2 py-0.5 rounded-md border ${
                  catalog.market_type === 'perp'
                    ? 'bg-purple-950/70 text-purple-300 border-purple-800/50'
                    : 'bg-blue-950/70 text-blue-300 border-blue-800/50'
                }`}
              >
                {catalog.market_type.toUpperCase()}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-400 mt-1">
            Multilateral storage for Binance Spot and USD-M Perpetuals across all timeframes.
          </p>

          <div className="mt-3 flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="text-xs text-gray-500">Active dataset:</label>
            <select
              value={selectedCatalogPath}
              onChange={(e) => onCatalogChange(e.target.value)}
              className="bg-gray-950 border border-gray-800 text-xs text-gray-200 rounded-xl px-3 py-1.5 font-mono min-w-[260px] focus:border-blue-500 focus:outline-none"
            >
              {catalogOptions.map((item) => (
                <option key={item.path} value={item.path}>
                  {item.name || item.path.split('/').pop()} · {item.market_type?.toUpperCase()} (
                  {item.total_instruments} inst., {item.bar_interval})
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

        {/* View Mode Switcher & Refresh Button */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
          <div className="flex items-center bg-gray-950 p-1 rounded-xl border border-gray-800">
            <button
              type="button"
              onClick={() => onViewModeChange('cards')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                viewMode === 'cards'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5" />
              <span>Datasets Hub</span>
            </button>
            <button
              type="button"
              onClick={() => onViewModeChange('matrix')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                viewMode === 'matrix'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Table className="w-3.5 h-3.5" />
              <span>Coverage Matrix</span>
            </button>
            <button
              type="button"
              onClick={() => onViewModeChange('details')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                viewMode === 'details'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <BarChart2 className="w-3.5 h-3.5" />
              <span>Inspector</span>
            </button>
            <button
              type="button"
              onClick={() => onViewModeChange('ingest')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                viewMode === 'ingest'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download & Ingest</span>
            </button>
          </div>

          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs font-medium rounded-xl transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>
    </div>
  );
};
