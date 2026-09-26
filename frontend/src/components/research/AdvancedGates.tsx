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
            <span className="text-[10px] text-gray-500">
              Захисний розрив між вибірками, щоб дані не заглядали в майбутнє.
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
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
                Bar-level VPIN (фільтр за обʼємом барів)
              </label>
              <InfoTooltip term="bar_vpin" size="xs" />
            </div>
            <span className="text-[10px] text-gray-500 pl-5">
              Оцінка токсичності за свічками — блокує вхід проти одностороннього напливу.
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
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
                Tick-level VPIN (точний фільтр за тіками)
              </label>
              <InfoTooltip term="tick_vpin" size="xs" />
            </div>
            <span className="text-[10px] text-gray-500 pl-5">
              Точний поділ агресора з угод (trades)
              {tickDataAvailable === false
                ? ' — у каталозі відсутні тіки'
                : tickDataAvailable === true
                  ? ' — тікові дані наявні'
                  : ' — статус невідомий'}
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={hawkes}
                  onChange={(e) => update({ hawkes: e.target.checked })}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Hawkes intensity (фільтр спалахів активності)
              </label>
              <InfoTooltip term="hawkes" size="xs" />
            </div>
            <span className="text-[10px] text-gray-500 pl-5">
              Захист від каскадних ліквідацій на тіках; активний лише для{' '}
              {hawkesRobots.join(', ') || 'роутера regime'}.
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
              <input
                type="checkbox"
                checked={generateTearsheet}
                onChange={(e) => update({ generateTearsheet: e.target.checked })}
                disabled={usePbo}
                className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0 disabled:opacity-50"
              />
              Згенерувати HTML Tearsheet {usePbo && '(недоступно для PBO)'}
            </label>
            <InfoTooltip term="tearsheet" size="xs" />
          </div>

          <div className="flex items-center gap-1.5">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
              <input
                type="checkbox"
                checked={journal}
                onChange={(e) => update({ journal: e.target.checked })}
                className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
              />
              Додати запис у research/journal.md
            </label>
            <InfoTooltip
              title="Запис у журнал досліджень"
              content="Автоматично фіксує параметри запуску, отриманий OOS та рішення у файл research/journal.md і на Kanban-дошці."
              interpretation="Корисно новачкам для відстеження власних експериментів та уникнення повторних прогонів збиткових налаштувань."
              size="xs"
            />
          </div>

          <div className="flex items-center gap-1.5">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
              <input
                type="checkbox"
                checked={notify}
                onChange={(e) => update({ notify: e.target.checked })}
                className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
              />
              Сповістити про завершення (Telegram / Webhook)
            </label>
            <InfoTooltip
              title="Сповіщення про результат"
              content="Надсилає повідомлення у Telegram або системний вебхук після закінчення тривалого прогону бектесту."
              size="xs"
            />
          </div>

          {source === 'catalog' && (
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-amber-300">
                <input
                  type="checkbox"
                  checked={fullSample}
                  onChange={(e) => update({ fullSample: e.target.checked })}
                  className="rounded bg-gray-950 border-gray-700 text-amber-500 focus:ring-0"
                />
                Full-sample (In-sample only, без перевірки OOS)
              </label>
              <InfoTooltip term="full_sample" size="xs" />
            </div>
          )}

          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-gray-400">Stress slice (Стрес-період)</span>
              <InfoTooltip term="stress_slice" size="xs" />
            </div>
            <select
              value={stressSlice}
              onChange={(e) => update({ stressSlice: e.target.value })}
              disabled={stressSlices.length === 0}
              className="bg-gray-950 border border-gray-800 text-xs text-gray-300 rounded-lg p-1.5 disabled:opacity-50"
            >
              <option value="">Повний діапазон (без стрес-зрізу)</option>
              {stressSlice && !stressSlices.some((slice) => slice.name === stressSlice) && (
                <option value={stressSlice}>{stressSlice} (невідомий бекенду)</option>
              )}
              {stressSlices.map((slice) => {
                const covers = sliceOverlapsCatalog(slice, selectedInstrument);
                return (
                  <option key={slice.name} value={slice.name}>
                    {slice.name} ({slice.start.slice(0, 10)} → {slice.end.slice(0, 10)})
                    {covers ? '' : ' — поза межами каталогу'}
                  </option>
                );
              })}
            </select>
            <span className="text-[10px] text-gray-500">
              {stressSlices.length === 0
                ? 'Бекенд не передав конфігурацій стрес-зрізів.'
                : 'Замінює вікно завантаження на період відомих криз для стрес-тесту.'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
