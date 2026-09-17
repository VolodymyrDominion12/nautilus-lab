import React, { useMemo } from 'react';
import { AlertTriangle, CalendarRange } from 'lucide-react';
import { CatalogChart } from './CatalogChart';
import { dateToUnixSeconds } from '../lib/format';
import { fractionBoundaries } from '../lib/research';
import type { WindowBoundaries } from '../lib/windowBands';

interface WalkForwardBuilderProps {
  mode: 'fraction' | 'custom';
  onModeChange: (mode: 'fraction' | 'custom') => void;
  isFraction: number;
  embargoBars: number;
  folds: number;
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
  catalogBarsCount?: number | null;
  instrumentId?: string;
  catalogPath?: string;
  barInterval?: string;
}

const toDateInput = (iso: string | null | undefined): string => (iso ? iso.slice(0, 10) : '');

export const WalkForwardBuilder: React.FC<WalkForwardBuilderProps> = ({
  mode,
  onModeChange,
  isFraction,
  embargoBars,
  folds,
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
  catalogBarsCount,
  instrumentId,
  catalogPath,
  barInterval,
}) => {
  const boundaries = useMemo<WindowBoundaries>(() => {
    if (mode === 'custom') {
      return {
        isStart: dateToUnixSeconds(isStart),
        isEnd: dateToUnixSeconds(isEnd),
        oosStart: dateToUnixSeconds(oosStart),
        oosEnd: dateToUnixSeconds(oosEnd),
      };
    }
    return fractionBoundaries({
      firstDate: catalogFirstDate,
      lastDate: catalogLastDate,
      barsCount: catalogBarsCount,
      isFraction,
      embargoBars,
    });
  }, [
    mode,
    isStart,
    isEnd,
    oosStart,
    oosEnd,
    catalogFirstDate,
    catalogLastDate,
    catalogBarsCount,
    isFraction,
    embargoBars,
  ]);

  const dateIssues: string[] = [];
  if (mode === 'custom') {
    if (isStart && isEnd && isStart >= isEnd) dateIssues.push('IS start must be before IS end.');
    if (isEnd && oosStart && oosStart < isEnd) {
      dateIssues.push('OOS start is before IS end: the legs would overlap, which is look-ahead.');
    }
    if (oosStart && oosEnd && oosStart >= oosEnd) dateIssues.push('OOS start must be before OOS end.');
  }

  const approximate = mode === 'fraction' && !(catalogBarsCount && catalogBarsCount > 1);

  return (
    <div className="bg-gray-950/50 border border-gray-800 rounded-2xl p-4 flex flex-col gap-4">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CalendarRange className="w-4 h-4 text-blue-400" />
          <div>
            <h3 className="text-sm font-semibold text-gray-100">Walk-Forward Window</h3>
            <p className="text-[11px] text-gray-500">
              Amber is the parameter-selection window. Green is the forecast that gets reported.
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
            disabled={folds > 1}
            title={folds > 1 ? 'Multi-window runs derive their own windows' : undefined}
            className={`px-3 py-1 text-xs rounded-lg ${
              mode === 'custom' ? 'bg-blue-600 text-white' : 'text-gray-400'
            } ${folds > 1 ? 'opacity-40 cursor-not-allowed' : ''}`}
          >
            Custom UTC dates
          </button>
        </div>
      </div>

      {mode === 'fraction' ? (
        <div className="text-xs text-gray-400 font-mono">
          {(isFraction * 100).toFixed(0)}% in-sample / {((1 - isFraction) * 100).toFixed(0)}%
          out-of-sample, embargo {embargoBars} bars.
          {catalogFirstDate && catalogLastDate && (
            <span className="block mt-1 text-gray-500">
              Catalog range: {catalogFirstDate.slice(0, 10)} → {catalogLastDate.slice(0, 10)}
              {catalogBarsCount ? ` · ${catalogBarsCount.toLocaleString()} bars` : ''}
            </span>
          )}
          {folds > 1 && (
            <span className="block mt-1 text-gray-500">
              With {folds} folds the engine derives {folds} rolling windows of its own; the bands
              below show the last one it would use.
            </span>
          )}
          {approximate && (
            <span className="block mt-1 text-amber-400/80">
              Bar count unknown, so the boundary is time-proportional and may be off by a bar.
            </span>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-400">
              IS start (UTC) <span className="text-gray-600">— selection</span>
            </span>
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
            <span className="text-gray-400">
              OOS start <span className="text-emerald-500/70">— report</span>
            </span>
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

      {dateIssues.length > 0 && (
        <div className="flex flex-col gap-1">
          {dateIssues.map((issue) => (
            <div key={issue} className="flex items-start gap-2 text-[11px] text-red-400">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{issue}</span>
            </div>
          ))}
        </div>
      )}

      <CatalogChart
        instrumentId={instrumentId}
        catalogPath={catalogPath}
        barInterval={barInterval}
        limit={500}
        height={260}
        boundaries={boundaries}
        title={`${instrumentId ?? 'catalog'} — walk-forward window`}
      />
    </div>
  );
};
