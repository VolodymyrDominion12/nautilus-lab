import React from 'react';
import { Check, Layers, Play, RefreshCw, Sparkles, Square } from 'lucide-react';
import { MODEL_DEFINITIONS } from './types';
import type { SupportedModel } from './types';
import type { CatalogInstrument } from '../../services/api';
import { InfoTooltip } from '../InfoTooltip';

interface Props {
  selectedModels: SupportedModel[];
  onToggleModel: (id: SupportedModel) => void;
  onSelectAllModels: () => void;
  availableInstruments: CatalogInstrument[];
  selectedInstruments: string[];
  onToggleInstrument: (id: string) => void;
  onSelectAllInstruments: () => void;
  onClearInstruments: () => void;
  customInstrument: string;
  setCustomInstrument: (val: string) => void;
  onAddCustomInstrument: () => void;
  folds: number;
  setFolds: (val: number) => void;
  embargo: number;
  setEmbargo: (val: number) => void;
  horizon: number;
  setHorizon: (val: number) => void;
  start: string;
  setStart: (val: string) => void;
  end: string;
  setEnd: (val: string) => void;
  profitMultiple: string;
  setProfitMultiple: (val: string) => void;
  stopMultiple: string;
  setStopMultiple: (val: string) => void;
  volWindow: number;
  setVolWindow: (val: number) => void;
  threshold: string;
  setThreshold: (val: string) => void;
  running: boolean;
  totalTasks: number;
  onTrain: () => void;
  onCancel: () => void;
  onPollLog: () => void;
}

export const MLConfigPanel: React.FC<Props> = ({
  selectedModels,
  onToggleModel,
  onSelectAllModels,
  availableInstruments,
  selectedInstruments,
  onToggleInstrument,
  onSelectAllInstruments,
  onClearInstruments,
  customInstrument,
  setCustomInstrument,
  onAddCustomInstrument,
  folds,
  setFolds,
  embargo,
  setEmbargo,
  horizon,
  setHorizon,
  start,
  setStart,
  end,
  setEnd,
  profitMultiple,
  setProfitMultiple,
  stopMultiple,
  setStopMultiple,
  volWindow,
  setVolWindow,
  threshold,
  setThreshold,
  running,
  totalTasks,
  onTrain,
  onCancel,
  onPollLog,
}) => {
  const hasMetaLabel = selectedModels.includes('meta_label');
  const hasObi = selectedModels.includes('obi');

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Models selection */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-400" />
            <h3 className="font-semibold text-sm text-gray-100">1. Select Models</h3>
          </div>
          <button
            type="button"
            onClick={onSelectAllModels}
            className="text-xs text-emerald-400 hover:text-emerald-300 font-medium"
          >
            Select All
          </button>
        </div>

        <div className="space-y-2">
          {MODEL_DEFINITIONS.map((def) => {
            const isChecked = selectedModels.includes(def.id);
            return (
              <div
                key={def.id}
                onClick={() => onToggleModel(def.id)}
                className={`cursor-pointer p-3 rounded-xl border transition-all text-xs flex flex-col gap-1.5 ${
                  isChecked
                    ? 'bg-emerald-950/20 border-emerald-500/50 shadow-sm'
                    : 'bg-gray-950 border-gray-800/80 hover:border-gray-700 opacity-75'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => {}}
                      className="w-3.5 h-3.5 rounded border-gray-700 text-emerald-600 focus:ring-emerald-500"
                    />
                    <span className="font-semibold text-gray-200">{def.name}</span>
                  </div>
                  <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-gray-800 text-gray-300 border border-gray-700">
                    {def.badge}
                  </span>
                </div>
                <p className="text-[11px] text-gray-400 pl-5.5 leading-normal">{def.desc}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. Pairs selection */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-blue-400" />
            <h3 className="font-semibold text-sm text-gray-100">2. Select Trading Pairs</h3>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <button
              type="button"
              onClick={onSelectAllInstruments}
              className="text-blue-400 hover:text-blue-300 font-medium"
            >
              All Pairs
            </button>
            <span className="text-gray-600">|</span>
            <button
              type="button"
              onClick={onClearInstruments}
              className="text-gray-400 hover:text-gray-300 font-medium"
            >
              Clear
            </button>
          </div>
        </div>

        {availableInstruments.length > 0 ? (
          <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto pr-1">
            {availableInstruments.map((inst) => {
              const isSelected = selectedInstruments.includes(inst.instrument_id);
              return (
                <button
                  key={inst.instrument_id}
                  type="button"
                  onClick={() => onToggleInstrument(inst.instrument_id)}
                  className={`px-3 py-1.5 rounded-xl border text-xs font-mono transition-all flex items-center gap-1.5 ${
                    isSelected
                      ? 'bg-blue-950/40 border-blue-500/60 text-blue-200 font-semibold shadow-sm'
                      : 'bg-gray-950 border-gray-800 text-gray-400 hover:border-gray-700'
                  }`}
                >
                  {isSelected && <Check className="w-3 h-3 text-blue-400" />}
                  <span>{inst.raw_symbol || inst.instrument_id}</span>
                  <span className="text-[10px] text-gray-500">
                    ({Math.round(inst.bars_count / 1000)}k)
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className="text-xs text-gray-500">No instruments loaded from catalog yet.</p>
        )}

        <div className="flex gap-2 pt-1">
          <input
            type="text"
            placeholder="Or custom symbol (e.g. SOL/USDT.BINANCE)"
            value={customInstrument}
            onChange={(e) => setCustomInstrument(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onAddCustomInstrument()}
            className="flex-1 bg-gray-950 border border-gray-800 rounded-xl px-3 py-1.5 text-xs font-mono text-gray-200"
          />
          <button
            type="button"
            onClick={onAddCustomInstrument}
            className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-xl text-xs font-medium"
          >
            Add
          </button>
        </div>
      </div>

      {/* 3. CV & Parameters */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 space-y-4">
        <h3 className="font-semibold text-sm text-gray-100">3. Cross-Validation & Window</h3>

        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="flex items-center gap-1 mb-1">
              <label className="text-xs text-gray-400">Folds</label>
              <InfoTooltip term="folds" size="xs" />
            </div>
            <input
              type="number"
              value={folds}
              onChange={(e) => setFolds(Number(e.target.value))}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono text-gray-200"
            />
          </div>
          <div>
            <div className="flex items-center gap-1 mb-1">
              <label className="text-xs text-gray-400">Embargo</label>
              <InfoTooltip term="embargo_bars" size="xs" />
            </div>
            <input
              type="number"
              value={embargo}
              onChange={(e) => setEmbargo(Number(e.target.value))}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono text-gray-200"
            />
          </div>
          <div>
            <div className="flex items-center gap-1 mb-1">
              <label className="text-xs text-gray-400">Horizon</label>
              <InfoTooltip term="ml_horizon" size="xs" />
            </div>
            <input
              type="number"
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-sm font-mono text-gray-200"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Start (inclusive)</label>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono text-gray-200"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">End (exclusive)</label>
            <input
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono text-gray-200"
            />
          </div>
        </div>

        {hasMetaLabel && (
          <div className="pt-3 border-t border-gray-800/80 space-y-3">
            <span className="text-xs font-semibold text-amber-400">
              Triple Barrier Settings (Meta-label)
            </span>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[11px] text-gray-400">Profit Mult (TP)</label>
                <input
                  type="text"
                  value={profitMultiple}
                  onChange={(e) => setProfitMultiple(e.target.value)}
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1 text-xs font-mono text-gray-200"
                />
              </div>
              <div>
                <label className="text-[11px] text-gray-400">Stop Mult (SL)</label>
                <input
                  type="text"
                  value={stopMultiple}
                  onChange={(e) => setStopMultiple(e.target.value)}
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1 text-xs font-mono text-gray-200"
                />
              </div>
              <div>
                <label className="text-[11px] text-gray-400">Vol Window</label>
                <input
                  type="number"
                  value={volWindow}
                  onChange={(e) => setVolWindow(Number(e.target.value))}
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1 text-xs font-mono text-gray-200"
                />
              </div>
              <div>
                <label className="text-[11px] text-gray-400">Threshold Prob</label>
                <input
                  type="text"
                  value={threshold}
                  onChange={(e) => setThreshold(e.target.value)}
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1 text-xs font-mono text-gray-200"
                />
              </div>
            </div>
          </div>
        )}

        {hasObi && (
          <div className="pt-3 border-t border-gray-800/80 space-y-1.5 text-xs">
            <span className="font-semibold text-purple-400">OBI Settings (Order Book)</span>
            <p className="text-[11px] text-gray-400 leading-normal">
              Requires L2 book snapshots in the catalog (ingested via{' '}
              <code className="text-gray-300">lab ingest --depth</code>).
            </p>
          </div>
        )}

        <div className="pt-2 flex gap-2">
          <button
            type="button"
            onClick={onTrain}
            disabled={running || totalTasks === 0}
            className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white rounded-xl py-3 text-sm font-semibold transition-all shadow-md shadow-emerald-950/40"
          >
            <Play className="w-4 h-4 fill-white" />
            {running
              ? 'Training in progress…'
              : totalTasks > 1
                ? `Train Matrix (${totalTasks} tasks: ${selectedModels.length} models × ${selectedInstruments.length} pairs)`
                : 'Train Model (1 task)'}
          </button>
          {running && (
            <button
              type="button"
              onClick={onCancel}
              title="Cancel Training Job"
              className="px-4 flex items-center gap-2 bg-red-950/50 hover:bg-red-900/60 border border-red-800/40 text-red-300 rounded-xl text-sm transition-colors"
            >
              <Square className="w-4 h-4" />
            </button>
          )}
          <button
            type="button"
            onClick={onPollLog}
            title="Refresh log"
            className="px-3.5 bg-gray-800 hover:bg-gray-700 rounded-xl text-gray-300 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
