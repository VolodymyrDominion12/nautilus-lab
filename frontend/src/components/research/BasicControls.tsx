import React from 'react';
import { AlertTriangle } from 'lucide-react';

import { InfoTooltip } from '../InfoTooltip';
import type { ResearchForm } from '../../lib/researchForm';
import type { CatalogResponse, StrategySpec } from '../../services/api';

export type CatalogInstrument = CatalogResponse['instruments'][number];

interface BasicControlsProps {
  form: ResearchForm;
  update: (patch: Partial<ResearchForm>) => void;
  strategies: StrategySpec[];
  catalogInstruments: CatalogInstrument[];
  selectedInstrument: CatalogInstrument | null;
  catalogError: string | null;
}

/** Robot, data (instrument or synthetic bar count), folds and the in-sample fraction. */
export const BasicControls: React.FC<BasicControlsProps> = ({
  form,
  update,
  strategies,
  catalogInstruments,
  selectedInstrument,
  catalogError,
}) => {
  const { robot, source, bars, folds, isFraction, windowMode } = form;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4 items-end">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-1">
          <label className="text-xs font-medium text-gray-300">Robot</label>
          <InfoTooltip
            title="Торговий робот (Стратегія)"
            subtitle="Алгоритмічна модель генерації сигналів"
            content="Оберіть стратегію для тестування. Позначка «✓» означає, що робот підключений до бектест-рушія NautilusTrader. Позначка «(fail-closed)» — свідомий архітектурний захист: робот ще не має адаптера виконання і його запуск блокується."
            interpretation="Для старту початківцям рекомендується протестувати «regime» (режимний перемикач тренд/флет) або «ema» (базовий трендовий слідкувач)."
            size="xs"
          />
        </div>
        <select
          value={robot}
          onChange={(e) => update({ robot: e.target.value })}
          disabled={strategies.length === 0}
          className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {strategies.length === 0 ? (
            <option value="">Завантаження стратегій...</option>
          ) : (
            strategies.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name} {s.wired_in_backtest ? '✓' : '(fail-closed)'}
              </option>
            ))
          )}
        </select>
      </div>

      {source === 'catalog' ? (
        <div className="flex flex-col gap-1.5 xl:col-span-2">
          <div className="flex items-center gap-1">
            <label className="text-xs font-medium text-gray-300">
              Instrument {catalogInstruments.length > 1 && `(${catalogInstruments.length} in catalog)`}
            </label>
            <InfoTooltip
              title="Торговий інструмент (Символ)"
              subtitle="Історичні біржові котирування з локального каталогу"
              content="Фінансова пара (наприклад, ETHUSDT або BTCUSDT) у бінарному форматі Parquet. Дані завантажуються безпосередньо з публічних серверів Binance без необхідності вводити API-ключі."
              interpretation="Якщо потрібної монети немає в списку, перейдіть на вкладку «Parquet Catalog» і запустіть Ingest. Для надійного аналізу рекомендується мати не менше 3000-5000 свічок."
              size="xs"
            />
          </div>
          {catalogInstruments.length === 0 ? (
            // A disabled select with a single "no instruments" option is a dead control:
            // it opens nothing and explains nothing. Say what to do instead.
            <div className="bg-amber-950/30 border border-amber-800/50 text-amber-300 text-xs rounded-xl p-2.5 flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                У цьому каталозі немає завантажених даних. Відкрийте{' '}
                <span className="font-mono">Parquet Catalog</span> і запустіть завантаження (ingest)
                {catalogError ? ` (помилка каталогу: ${catalogError})` : ''}.
              </span>
            </div>
          ) : (
            <select
              value={selectedInstrument?.instrument_id ?? ''}
              onChange={(e) => update({ instrumentId: e.target.value })}
              className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono focus:border-blue-500 focus:outline-none"
            >
              {catalogInstruments.map((item) => (
                <option key={item.instrument_id} value={item.instrument_id}>
                  {item.raw_symbol} · {item.bars_count.toLocaleString()} bars ·{' '}
                  {item.first_date?.slice(0, 10) ?? '?'} → {item.last_date?.slice(0, 10) ?? '?'}
                </option>
              ))}
            </select>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5 xl:col-span-2">
          <div className="flex items-center gap-1">
            <label className="text-xs font-medium text-gray-300">Synthetic bars</label>
            <InfoTooltip term="synthetic_data" size="xs" />
          </div>
          <input
            type="number"
            value={bars}
            onChange={(e) => update({ bars: Number(e.target.value) })}
            className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono"
          />
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-1">
          <label className="text-xs font-medium text-gray-300">Fold{source === 'catalog' && `s`}</label>
          <InfoTooltip term="folds" size="xs" />
        </div>
        <select
          value={folds}
          onChange={(e) => update({ folds: Number(e.target.value) })}
          className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono"
        >
          <option value={1}>
            {source === 'catalog' ? '1 (одне вікно, без порівняння з ринком)' : '1 (один прогін)'}
          </option>
          <option value={2}>2 (мультивіконна валідація, рекомендовано)</option>
          <option value={4}>4 (квартальні вікна ринку)</option>
          <option value={8}>8 (глибокий стрес-тест стійкості)</option>
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-1">
          <label className="text-xs font-medium text-gray-300">
            IS fraction ({(isFraction * 100).toFixed(0)}% / {((1 - isFraction) * 100).toFixed(0)}%)
          </label>
          <InfoTooltip term="is_fraction" size="xs" />
        </div>
        <input
          type="number"
          step="0.05"
          min="0.4"
          max="0.9"
          value={isFraction}
          onChange={(e) => update({ isFraction: Number(e.target.value) })}
          disabled={windowMode === 'custom'}
          className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono disabled:text-gray-600"
        />
      </div>
    </div>
  );
};
