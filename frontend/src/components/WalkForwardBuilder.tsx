import React from 'react';
import { CalendarRange } from 'lucide-react';
import { CatalogChart } from './CatalogChart';

interface WalkForwardBuilderProps {
  mode: 'fraction' | 'custom';
  onModeChange: (mode: 'fraction' | 'custom') => void;
  isFraction: number;
  isStart: string;
  isEnd: string;
  oosStart: string;
  oosEnd: string;
  onIsStartChange: (value: string) => void;
  onIsEndChange: (value: string) => void;
  onOosStartChange: (value: string) => void;
  onOosEndChange: (value: string) => void;
  catalogFirstDate?: string | null;
  catalogLastDate?: string | null;
  instrumentId?: string;
  catalogPath?: string;
}

const toDateInput = (iso: string | null | undefined): string => {
  if (!iso) return '';
  return iso.slice(0, 10);
};

export const WalkForwardBuilder: React.FC<WalkForwardBuilderProps> = ({
  mode,
  onModeChange,
  isFraction,
  isStart,
  isEnd,
  oosStart,
  oosEnd,
  onIsStartChange,
  onIsEndChange,
  onOosStartChange,
  onOosEndChange,
  catalogFirstDate,
  catalogLastDate,
  instrumentId,
  catalogPath,
}) => {
  const isEndTime = isEnd ? Math.floor(new Date(`${isEnd}T00:00:00Z`).getTime() / 1000) : null;
  const oosStartTime = oosStart
    ? Math.floor(new Date(`${oosStart}T00:00:00Z`).getTime() / 1000)
    : null;

  return (
    <div className="bg-gray-950/50 border border-gray-800 rounded-2xl p-4 flex flex-col gap-4">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CalendarRange className="w-4 h-4 text-blue-400" />
          <div>
            <h3 className="text-sm font-semibold text-gray-100">Walk-Forward Window</h3>
            <p className="text-[11px] text-gray-500">
              In-sample is for parameter selection only. Out-of-sample is the report.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 bg-gray-900 p-1 border border-gray-800 rounded-xl">
          <button
            type="button"
            onClick={() => onModeChange('fraction')}
            className={`px-3 py-1 text-xs rounded-lg ${
              mode === 'fraction' ? 'bg-blue-600 text-white' : 'text-gray-400'
            }`}
          >
            Anchored fraction
          </button>
          <button
            type="button"
            onClick={() => onModeChange('custom')}
            className={`px-3 py-1 text-xs rounded-lg ${
              mode === 'custom' ? 'bg-blue-600 text-white' : 'text-gray-400'
            }`}
          >
            Custom UTC dates
          </button>
        </div>
      </div>

      {mode === 'fraction' ? (
        <div className="text-xs text-gray-400 font-mono">
          Using {(isFraction * 100).toFixed(0)}% in-sample / {((1 - isFraction) * 100).toFixed(0)}%
          out-of-sample split with embargo from settings.
          {catalogFirstDate && catalogLastDate && (
            <span className="block mt-1 text-gray-500">
              Catalog range: {catalogFirstDate.slice(0, 10)} → {catalogLastDate.slice(0, 10)}
            </span>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400">IS start (UTC)</span>
            <input
              type="date"
              value={toDateInput(isStart)}
              onChange={(e) => onIsStartChange(e.target.value)}
              className="bg-gray-950 border border-gray-800 rounded-xl p-2 font-mono text-gray-200"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400">IS end exclusive</span>
            <input
              type="date"
              value={toDateInput(isEnd)}
              onChange={(e) => onIsEndChange(e.target.value)}
              className="bg-gray-950 border border-gray-800 rounded-xl p-2 font-mono text-gray-200"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400">OOS start</span>
            <input
              type="date"
              value={toDateInput(oosStart)}
              onChange={(e) => onOosStartChange(e.target.value)}
              className="bg-gray-950 border border-gray-800 rounded-xl p-2 font-mono text-gray-200"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400">OOS end exclusive</span>
            <input
              type="date"
              value={toDateInput(oosEnd)}
              onChange={(e) => onOosEndChange(e.target.value)}
              className="bg-gray-950 border border-gray-800 rounded-xl p-2 font-mono text-gray-200"
            />
          </label>
        </div>
      )}

      <CatalogChart
        instrumentId={instrumentId}
        catalogPath={catalogPath}
        limit={500}
        height={240}
        isEndTime={mode === 'custom' ? isEndTime : null}
        oosStartTime={mode === 'custom' ? oosStartTime : null}
      />
    </div>
  );
};
