import React, { useMemo, useState } from 'react';
import { Check, Search, Table } from 'lucide-react';
import type { CatalogSummary } from '../../services/api';

interface CatalogCoverageMatrixProps {
  catalogs: CatalogSummary[];
  allSymbols?: string[];
  selectedCatalogPath: string;
  onSelectCatalog: (path: string) => void;
}

export const CatalogCoverageMatrix: React.FC<CatalogCoverageMatrixProps> = ({
  catalogs,
  allSymbols = [],
  selectedCatalogPath,
  onSelectCatalog,
}) => {
  const [search, setSearch] = useState('');

  // Extract all unique symbols either from allSymbols or aggregated from catalogs
  const uniqueSymbols = useMemo(() => {
    if (allSymbols && allSymbols.length > 0) {
      return allSymbols;
    }
    const set = new Set<string>();
    for (const c of catalogs) {
      if (c.symbol_counts) {
        for (const sym of Object.keys(c.symbol_counts)) {
          set.add(sym);
        }
      }
      if (c.symbols) {
        for (const s of c.symbols) {
          set.add(s.replace(/-PERP$/, '').replace('/', ''));
        }
      }
    }
    return Array.from(set).sort();
  }, [catalogs, allSymbols]);

  const filteredSymbols = useMemo(() => {
    if (!search.trim()) return uniqueSymbols;
    const q = search.toLowerCase();
    return uniqueSymbols.filter((s) => s.toLowerCase().includes(q));
  }, [uniqueSymbols, search]);

  const formatCount = (count: number): string => {
    if (count >= 100_000) return `${(count / 1000).toFixed(0)}k`;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
    return String(count);
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      {/* Header and Search */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Table className="w-5 h-5 text-cyan-400" />
          <div>
            <h3 className="text-sm font-bold text-gray-100 flex items-center gap-2">
              Cross-Dataset Coverage Matrix
              <span className="text-xs font-normal text-gray-400 font-mono">
                ({filteredSymbols.length} of {uniqueSymbols.length} symbols)
              </span>
            </h3>
            <p className="text-xs text-gray-400">
              Overview of all crypto symbols across Spot, Perpetual, and historical datasets.
            </p>
          </div>
        </div>

        <div className="relative min-w-[220px]">
          <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search symbol (e.g. BTC)..."
            className="w-full bg-gray-950 border border-gray-800 text-xs text-gray-200 rounded-xl pl-9 pr-3 py-1.5 focus:border-blue-500 focus:outline-none"
          />
        </div>
      </div>

      {/* Coverage Matrix Table */}
      <div className="overflow-x-auto border border-gray-800/80 rounded-xl">
        <table className="w-full text-xs font-mono">
          <thead className="bg-gray-950/80 text-gray-400 border-b border-gray-800">
            <tr>
              <th className="text-left p-3 font-semibold text-gray-300 min-w-[130px]">
                Symbol
              </th>
              {catalogs.map((cat) => {
                const isSelected =
                  selectedCatalogPath === cat.path ||
                  selectedCatalogPath === cat.name ||
                  selectedCatalogPath.endsWith(`/${cat.name}`);

                return (
                  <th
                    key={cat.path}
                    onClick={() => onSelectCatalog(cat.path)}
                    className={`text-center p-2.5 cursor-pointer transition-colors hover:bg-gray-800/60 min-w-[110px] ${
                      isSelected
                        ? 'bg-blue-950/40 text-blue-300 border-b-2 border-blue-500'
                        : 'text-gray-300'
                    }`}
                  >
                    <div className="flex flex-col items-center gap-0.5">
                      <span className="font-bold text-[11px] truncate max-w-[120px]">
                        {cat.name || cat.path.split('/').pop()}
                      </span>
                      <div className="flex items-center gap-1 text-[10px]">
                        <span
                          className={`px-1 py-0.2 rounded font-sans font-medium ${
                            cat.market_type === 'perp'
                              ? 'text-purple-300'
                              : cat.market_type === 'spot'
                                ? 'text-blue-300'
                                : 'text-amber-300'
                          }`}
                        >
                          {cat.market_type?.toUpperCase()}
                        </span>
                        {cat.bar_interval && (
                          <span className="text-emerald-400 font-bold">
                            {cat.bar_interval}
                          </span>
                        )}
                      </div>
                    </div>
                  </th>
                );
              })}
              <th className="text-center p-2.5 font-semibold text-gray-400 min-w-[90px]">
                Funding
              </th>
              <th className="text-center p-2.5 font-semibold text-gray-400 min-w-[90px]">
                Premium
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/60 text-gray-300">
            {filteredSymbols.map((sym) => {
              // Check funding or premium availability across catalogs
              const hasFundingAnywhere = catalogs.some(
                (c) => c.has_funding && (c.symbols?.some((s) => s.includes(sym)) ?? true),
              );
              const hasPremiumAnywhere = catalogs.some(
                (c) => c.has_premium_index && (c.symbols?.some((s) => s.includes(sym)) ?? true),
              );

              return (
                <tr key={sym} className="hover:bg-gray-800/40 transition-colors">
                  <td className="p-3 font-bold text-gray-200 flex items-center gap-1.5">
                    <span className="text-blue-400">{sym}</span>
                  </td>

                  {catalogs.map((cat) => {
                    const isSelected =
                      selectedCatalogPath === cat.path ||
                      selectedCatalogPath === cat.name ||
                      selectedCatalogPath.endsWith(`/${cat.name}`);

                    const count = cat.symbol_counts ? cat.symbol_counts[sym] : undefined;
                    const present =
                      count !== undefined
                        ? count > 0
                        : cat.symbols?.some(
                            (s) => s.replace('/', '').replace('-PERP', '') === sym,
                          );

                    return (
                      <td
                        key={cat.path}
                        onClick={() => onSelectCatalog(cat.path)}
                        className={`text-center p-2 cursor-pointer ${
                          isSelected ? 'bg-blue-950/20' : ''
                        }`}
                      >
                        {present ? (
                          <span className="inline-block px-2 py-0.5 rounded-full bg-emerald-950/60 text-emerald-400 border border-emerald-800/40 text-[11px] font-semibold hover:border-emerald-600 transition-colors">
                            {count !== undefined ? `${formatCount(count)}` : 'yes'}
                          </span>
                        ) : (
                          <span className="text-gray-700 select-none">—</span>
                        )}
                      </td>
                    );
                  })}

                  {/* Funding Rate indicator */}
                  <td className="text-center p-2">
                    {hasFundingAnywhere ? (
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-emerald-950/70 text-emerald-400 border border-emerald-800/50">
                        <Check className="w-3 h-3" />
                      </span>
                    ) : (
                      <span className="text-gray-700">—</span>
                    )}
                  </td>

                  {/* Premium Index indicator */}
                  <td className="text-center p-2">
                    {hasPremiumAnywhere ? (
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-indigo-950/70 text-indigo-400 border border-indigo-800/50">
                        <Check className="w-3 h-3" />
                      </span>
                    ) : (
                      <span className="text-gray-700">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-[11px] text-gray-500 font-mono pt-1">
        <span>Click any column header or cell to select that catalog dataset.</span>
        <span>Green pills show bar counts; checkmarks indicate auxiliary rate coverage.</span>
      </div>
    </div>
  );
};
