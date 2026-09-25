import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

import { InfoTooltip } from '../InfoTooltip';
import { sliceOverlapsCatalog } from '../../lib/research';
import type { ResearchForm } from '../../lib/researchForm';
import type { StressSliceInfo } from '../../services/api';
import type { CatalogInstrument } from './BasicControls';

interface AdvancedGatesProps {
  form: ResearchForm;
  update: (patch: Partial<ResearchForm>) => void;
  /** Tick coverage of the selected instrument; null = the health endpoint has not said. */
  tickDataAvailable: boolean | null;
  hawkesRobots: string[];
  stressSlices: StressSliceInfo[];
  selectedInstrument: CatalogInstrument | null;
}

/** The collapsible gates: Optuna, PBO, embargo, VPIN, Hawkes, outputs, stress slice. */
export const AdvancedGates: React.FC<AdvancedGatesProps> = ({
  form,
  update,
  tickDataAvailable,
  hawkesRobots,
  stressSlices,
  selectedInstrument,
}) => {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const {
    source,
    embargoBars,
    useOptuna,
    optunaTrials,
    usePbo,
    pboBlocks,
    barVpin,
    tickVpin,
    hawkes,
    stressSlice,
    generateTearsheet,
    journal,
    notify,
    fullSample,
  } = form;
  return (
    <div>
      <button
        type="button"
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium"
      >
        {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        {showAdvanced ? 'Hide advanced gates' : 'Show advanced gates (Optuna, PBO, embargo, VPIN, Hawkes, journal)'}
      </button>

      {showAdvanced && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4 mt-2 border-t border-gray-800/80">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={useOptuna}
                  onChange={(e) => update({ useOptuna: e.target.checked })}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Bayesian selection (Optuna TPE)
              </label>
              <InfoTooltip term="optuna_trials" size="xs" />
            </div>
            {useOptuna && (
              <div className="flex items-center gap-2 pl-5">
                <span className="text-[11px] text-gray-400">Trials:</span>
                <input
                  type="number"
                  value={optunaTrials}
                  onChange={(e) => update({ optunaTrials: Number(e.target.value) })}
                  className="w-20 bg-gray-950 border border-gray-800 text-xs rounded p-1 font-mono"
                />
              </div>
            )}
            {useOptuna && fullSample && (
              <span className="text-[10px] text-red-400 pl-5">
                Cannot be combined with full-sample.
              </span>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={usePbo}
                  onChange={(e) => update({ usePbo: e.target.checked })}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Overfitting audit (PBO / CSCV)
              </label>
              <InfoTooltip term="pbo" size="xs" />
            </div>
            {usePbo && (
              <div className="flex items-center gap-2 pl-5">
                <span className="text-[11px] text-gray-400">Blocks:</span>
                <input
                  type="number"
                  value={pboBlocks}
                  onChange={(e) => update({ pboBlocks: Number(e.target.value) })}
                  className="w-20 bg-gray-950 border border-gray-800 text-xs rounded p-1 font-mono"
                />
              </div>
            )}
            {usePbo && (
              <span className="text-[10px] text-gray-500 pl-5">
                Simulates blocks × configurations runs; no tearsheet, no single PnL verdict.
              </span>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-gray-400">Purged embargo bars</span>
              <InfoTooltip term="embargo_bars" size="xs" />
            </div>
            <input
              type="number"
              value={embargoBars}
              onChange={(e) => update({ embargoBars: Number(e.target.value) })}
              className="bg-gray-950 border border-gray-800 text-xs text-gray-200 rounded-lg p-1.5 font-mono"
            />
            <span className="text-[10px] text-gray-600">
              A gap between the legs so overlapping bars cannot leak forward.
            </span>
          </div>

          <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
            <input
              type="checkbox"
              checked={barVpin}
              onChange={(e) => {
                update({ barVpin: e.target.checked });
                if (e.target.checked) update({ tickVpin: false });
              }}
              className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
            />
            Bar-level VPIN regime filter (volume proxy)
          </label>

          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
              <input
                type="checkbox"
                checked={tickVpin}
                onChange={(e) => {
                  update({ tickVpin: e.target.checked });
                  if (e.target.checked) update({ barVpin: false });
                }}
                className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
              />
              Tick-level VPIN regime filter
            </label>
            <span className="text-[10px] text-gray-600 pl-5">
              Real aggressor split from aggregated trades
              {tickDataAvailable === false
                ? ' — no tick series in this catalog'
                : tickDataAvailable === true
                  ? ' — tick series present'
                  : ' — coverage unknown'}
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
              <input
                type="checkbox"
                checked={hawkes}
                onChange={(e) => update({ hawkes: e.target.checked })}
                className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
              />
              Hawkes intensity filter
            </label>
            <span className="text-[10px] text-gray-600 pl-5">
              Clustered-flow gate built from the same tick series; runs only for{' '}
              {hawkesRobots.join(', ') || 'the regime router'}.
            </span>
          </div>

          <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
            <input
              type="checkbox"
              checked={generateTearsheet}
              onChange={(e) => update({ generateTearsheet: e.target.checked })}
              disabled={usePbo}
              className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0 disabled:opacity-50"
            />
            Generate HTML tearsheet {usePbo && '(not available for PBO)'}
          </label>

          <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
            <input
              type="checkbox"
              checked={journal}
              onChange={(e) => update({ journal: e.target.checked })}
              className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
            />
            Append a row to research/journal.md
          </label>

          <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
            <input
              type="checkbox"
              checked={notify}
              onChange={(e) => update({ notify: e.target.checked })}
              className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
            />
            Notify on completion (Telegram / webhook)
          </label>

          {source === 'catalog' && (
            <label className="flex items-center gap-2 cursor-pointer text-xs text-amber-300">
              <input
                type="checkbox"
                checked={fullSample}
                onChange={(e) => update({ fullSample: e.target.checked })}
                className="rounded bg-gray-950 border-gray-700 text-amber-500 focus:ring-0"
              />
              Full-sample (in-sample only, no split)
            </label>
          )}

          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-gray-400">Stress slice</span>
            <select
              value={stressSlice}
              onChange={(e) => update({ stressSlice: e.target.value })}
              disabled={stressSlices.length === 0}
              className="bg-gray-950 border border-gray-800 text-xs text-gray-300 rounded-lg p-1.5 disabled:opacity-50"
            >
              <option value="">Full range (no slice)</option>
              {/* The list and its dates come from the backend (`domain/stress_slices.py`),
                  so a slice renamed or moved in code cannot linger here as a stale label.
                  A value restored from an archived run is kept visible but flagged. */}
              {stressSlice && !stressSlices.some((slice) => slice.name === stressSlice) && (
                <option value={stressSlice}>{stressSlice} (unknown to this backend)</option>
              )}
              {stressSlices.map((slice) => {
                const covers = sliceOverlapsCatalog(slice, selectedInstrument);
                return (
                  <option key={slice.name} value={slice.name}>
                    {slice.name} ({slice.start.slice(0, 10)} → {slice.end.slice(0, 10)})
                    {covers ? '' : ' — outside this catalog'}
                  </option>
                );
              })}
            </select>
            <span className="text-[10px] text-gray-600">
              {stressSlices.length === 0
                ? 'The backend did not report any stress slices, so none can be selected.'
                : 'A slice replaces the load window, so it must lie inside the catalog\u2019s own range; the dates above are the ones the backend will use.'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
