import React, { useMemo, useState } from 'react';
import {
  Calendar,
  CheckCircle2,
  Database,
  Download,
} from 'lucide-react';
import type { CatalogSummary } from '../../services/api';

interface CatalogCardsHubProps {
  catalogs: CatalogSummary[];
  selectedCatalogPath: string;
  onSelectCatalog: (path: string) => void;
  onOpenIngest?: () => void;
}

export const CatalogCardsHub: React.FC<CatalogCardsHubProps> = ({
  catalogs,
  selectedCatalogPath,
  onSelectCatalog,
  onOpenIngest,
}) => {
  const [marketFilter, setMarketFilter] = useState<'all' | 'spot' | 'perp'>('all');
  const [intervalFilter, setIntervalFilter] = useState<string>('all');

  const intervals = useMemo(() => {
    const set = new Set<string>();
    for (const c of catalogs) {
      if (c.bar_interval) set.add(c.bar_interval);
    }
    return Array.from(set).sort();
  }, [catalogs]);

  const filteredCatalogs = useMemo(() => {
    return catalogs.filter((c) => {
      if (marketFilter !== 'all' && c.market_type !== marketFilter) return false;
      if (intervalFilter !== 'all' && c.bar_interval !== intervalFilter) return false;
      return true;
    });
  }, [catalogs, marketFilter, intervalFilter]);

  const totalBarsAcrossAll = useMemo(
    () => catalogs.reduce((sum, c) => sum + (c.total_bars ?? 0), 0),
    [catalogs],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Header and Filter Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-gray-900 border border-gray-800 p-4 rounded-2xl">
        <div className="flex items-center gap-3">
          <Database className="w-5 h-5 text-blue-400" />
          <div>
            <h3 className="text-sm font-bold text-gray-100 flex items-center gap-2">
              Discovered Datasets ({catalogs.length})
              <span className="text-xs font-mono font-normal text-gray-400">
                · {totalBarsAcrossAll.toLocaleString()} total bars
              </span>
            </h3>
            <p className="text-xs text-gray-400">
              Select any directory to inspect coverage, preview prices, or run walk-forward research.
            </p>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* Market filter */}
          <div className="flex items-center bg-gray-950 p-1 rounded-xl border border-gray-800">
            {(['all', 'spot', 'perp'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMarketFilter(m)}
                className={`px-2.5 py-1 rounded-lg font-medium transition-colors ${
                  marketFilter === m
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {m === 'all' ? 'All Markets' : m.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Interval filter */}
          {intervals.length > 1 && (
            <div className="flex items-center bg-gray-950 p-1 rounded-xl border border-gray-800">
              <button
                type="button"
                onClick={() => setIntervalFilter('all')}
                className={`px-2.5 py-1 rounded-lg font-mono font-medium transition-colors ${
                  intervalFilter === 'all'
                    ? 'bg-emerald-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                All TF
              </button>
              {intervals.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setIntervalFilter(tf)}
                  className={`px-2.5 py-1 rounded-lg font-mono font-medium transition-colors ${
                    intervalFilter === tf
                      ? 'bg-emerald-600 text-white shadow-sm'
                      : 'text-gray-400 hover:text-gray-200'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>
          )}

          {onOpenIngest && (
            <button
              type="button"
              onClick={onOpenIngest}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium rounded-xl transition-colors shadow-sm ml-auto"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download & Ingest Data</span>
            </button>
          )}
        </div>
      </div>

      {/* Grid of Catalog Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredCatalogs.map((item) => {
          const isSelected =
            selectedCatalogPath === item.path ||
            selectedCatalogPath === item.name ||
            selectedCatalogPath.endsWith(`/${item.name}`);

          const spanDays =
            item.first_date && item.last_date
              ? Math.round(
                  (Date.parse(item.last_date) - Date.parse(item.first_date)) / 86_400_000,
                )
              : null;

          return (
            <div
              key={item.path}
              onClick={() => onSelectCatalog(item.path)}
              className={`p-5 rounded-2xl border transition-all cursor-pointer flex flex-col justify-between gap-4 ${
                isSelected
                  ? 'bg-gray-900/90 border-blue-500/80 shadow-lg shadow-blue-950/30 ring-1 ring-blue-500/40'
                  : 'bg-gray-900/70 border-gray-800/90 hover:border-gray-700 hover:bg-gray-900'
              }`}
            >
              <div className="flex flex-col gap-3">
                {/* Card Header */}
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h4 className="font-mono text-base font-bold text-gray-100 flex items-center gap-2">
                      {item.name || item.path.split('/').pop()}
                      {isSelected && (
                        <span className="flex items-center gap-1 text-[11px] font-sans font-medium px-2 py-0.5 rounded-full bg-blue-950/80 text-blue-300 border border-blue-800/60">
                          <CheckCircle2 className="w-3 h-3 text-blue-400" />
                          Active
                        </span>
                      )}
                    </h4>
                    <span className="text-[11px] font-mono text-gray-500 truncate block max-w-[280px]">
                      {item.path}
                    </span>
                  </div>

                  {/* Market & Interval Badges */}
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <span
                      className={`text-[10px] font-semibold tracking-wider px-2 py-0.5 rounded-md border ${
                        item.market_type === 'perp'
                          ? 'bg-purple-950/70 text-purple-300 border-purple-800/50'
                          : item.market_type === 'spot'
                            ? 'bg-blue-950/70 text-blue-300 border-blue-800/50'
                            : 'bg-amber-950/70 text-amber-300 border-amber-800/50'
                      }`}
                    >
                      {item.market_type ? item.market_type.toUpperCase() : 'UNKNOWN'}
                    </span>
                    {item.bar_interval && (
                      <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-emerald-950/70 text-emerald-300 border border-emerald-800/50">
                        {item.bar_interval}
                      </span>
                    )}
                  </div>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-3 gap-2 py-2 border-y border-gray-800/70 text-xs">
                  <div>
                    <span className="text-gray-500 block text-[11px]">Instruments</span>
                    <span className="font-mono font-bold text-gray-200">
                      {item.total_instruments} pairs
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[11px]">Total Bars</span>
                    <span className="font-mono font-bold text-gray-200">
                      {(item.total_bars ?? 0).toLocaleString()}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[11px]">Timespan</span>
                    <span className="font-mono text-gray-300">
                      {spanDays ? `${(spanDays / 365).toFixed(1)} yrs` : '—'}
                    </span>
                  </div>
                </div>

                {/* Dates coverage */}
                <div className="flex items-center gap-1.5 text-[11px] font-mono text-gray-400">
                  <Calendar className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                  <span>
                    {item.first_date ? item.first_date.slice(0, 10) : 'n/a'} →{' '}
                    {item.last_date ? item.last_date.slice(0, 10) : 'n/a'}
                  </span>
                </div>

                {/* Auxiliary side series badges */}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {item.has_funding && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-400 border border-emerald-800/40">
                      Funding
                    </span>
                  )}
                  {item.has_premium_index && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-950/60 text-indigo-400 border border-indigo-800/40">
                      Premium Index
                    </span>
                  )}
                  {item.has_taker_flow && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-950/60 text-cyan-400 border border-cyan-800/40">
                      Taker Flow
                    </span>
                  )}
                  {item.has_ticks && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-400 border border-amber-800/40">
                      Agg Trades
                    </span>
                  )}
                </div>
              </div>

              {/* Bottom selection button */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectCatalog(item.path);
                  }}
                  className={`w-full py-2 px-3 text-xs font-semibold rounded-xl transition-all ${
                    isSelected
                      ? 'bg-blue-600 text-white hover:bg-blue-500 shadow-sm'
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-white'
                  }`}
                >
                  {isSelected ? 'Currently Selected' : 'Select Dataset'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
