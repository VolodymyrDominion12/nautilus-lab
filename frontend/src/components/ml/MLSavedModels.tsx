import React, { useMemo, useState } from 'react';
import { Check, Copy, RefreshCw, Search, Trash2 } from 'lucide-react';
import type { MlModelInfo } from '../../services/api';

interface Props {
  models: MlModelInfo[];
  refreshModels: () => void;
  onDeleteModel: (path: string) => Promise<void>;
}

export const MLSavedModels: React.FC<Props> = ({ models, refreshModels, onDeleteModel }) => {
  const [modelFilter, setModelFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedPath, setCopiedPath] = useState<string | null>(null);

  const handleCopyPath = (path: string) => {
    navigator.clipboard.writeText(path).then(() => {
      setCopiedPath(path);
      setTimeout(() => setCopiedPath(null), 2500);
    });
  };

  const filteredModels = useMemo(() => {
    return models.filter((m) => {
      const q = searchQuery.toLowerCase();
      const matchesSearch =
        searchQuery === '' ||
        m.filename.toLowerCase().includes(q) ||
        (m.instrument_id && m.instrument_id.toLowerCase().includes(q)) ||
        (m.robot && m.robot.toLowerCase().includes(q));

      if (!matchesSearch) return false;

      if (modelFilter === 'all') return true;
      if (modelFilter === 'formulaic') {
        return m.filename.includes('formulaic') || m.robot === 'formulaic_lgbm';
      }
      if (modelFilter === 'meta_label') {
        return m.filename.includes('meta_label') || m.robot === 'meta_label';
      }
      if (modelFilter === 'obi') {
        return m.filename.includes('obi') || m.robot === 'ml_obi';
      }
      return true;
    });
  }, [models, searchQuery, modelFilter]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-gray-100">Saved Models Inventory</h3>
          <span className="px-2 py-0.5 rounded-full bg-gray-800 text-gray-400 text-xs font-mono">
            {filteredModels.length} {filteredModels.length === 1 ? 'model' : 'models'}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center bg-gray-950 border border-gray-800 rounded-xl p-1 text-xs">
            {(['all', 'formulaic', 'meta_label', 'obi'] as const).map((filterKey) => (
              <button
                key={filterKey}
                type="button"
                onClick={() => setModelFilter(filterKey)}
                className={`px-2.5 py-1 rounded-lg transition-colors capitalize ${
                  modelFilter === filterKey
                    ? 'bg-gray-800 text-white font-medium'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {filterKey === 'obi' ? 'OBI' : filterKey.replace('_', '-')}
              </button>
            ))}
          </div>

          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-gray-500" />
            <input
              type="text"
              placeholder="Search models..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-gray-950 border border-gray-800 rounded-xl pl-8 pr-3 py-1.5 text-xs text-gray-200 font-mono w-44"
            />
          </div>

          <button
            type="button"
            onClick={refreshModels}
            className="p-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl text-xs flex items-center transition-colors"
            title="Refresh models list"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {filteredModels.length === 0 ? (
        <p className="text-sm text-gray-500 py-4 text-center">
          No trained models found matching criteria.
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filteredModels.map((model) => (
            <div
              key={model.path}
              className="flex flex-col justify-between gap-3 p-3.5 rounded-xl bg-gray-950 border border-gray-800 hover:border-gray-700 transition-all text-xs"
            >
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="font-mono font-semibold text-gray-200 truncate"
                    title={model.path}
                  >
                    {model.filename}
                  </span>
                  <span className="text-[11px] text-gray-500 shrink-0 font-mono">
                    {model.size_kb} KB
                  </span>
                </div>

                <div className="flex flex-wrap gap-1.5 items-center">
                  {model.instrument_id && (
                    <span className="px-2 py-0.5 rounded bg-blue-950/60 border border-blue-800/40 text-blue-300 font-mono text-[10px]">
                      {model.instrument_id}
                    </span>
                  )}
                  {model.robot && (
                    <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-300 font-mono text-[10px]">
                      {model.robot}
                    </span>
                  )}
                  {model.rows != null && (
                    <span className="text-gray-500 font-mono text-[10px]">
                      {model.rows.toLocaleString()} rows
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-gray-800/60 text-[11px] text-gray-500 font-mono">
                <span className="truncate max-w-[140px]" title={model.path}>
                  {model.path}
                </span>
                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    type="button"
                    onClick={() => handleCopyPath(model.path)}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors"
                    title="Copy model path for .env / Settings"
                  >
                    {copiedPath === model.path ? (
                      <>
                        <Check className="w-3 h-3 text-emerald-400" />
                        <span className="text-emerald-400">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3 h-3" />
                        <span>Copy</span>
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => onDeleteModel(model.path)}
                    className="p-1 rounded-lg hover:bg-red-950/50 text-gray-500 hover:text-red-400 transition-colors"
                    title="Delete model"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
