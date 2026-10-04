import React from 'react';

import type { IngestSeries } from '../../services/api';
import {
  SERIES_BY_SOURCE,
  archiveTarget,
  ingestWarnings,
  symbolPresets,
  usesInterval,
} from '../../lib/ingestForm';
import type { IngestFormState } from '../../lib/ingestForm';

const SERIES_LABELS: Record<IngestSeries, [label: string, hint: string]> = {
  klines: ['Klines', 'OHLCV bars (spot / perp)'],
  premium_index: ['Prem Index', 'perp basis mark vs index'],
  funding: ['Funding', 'perp settlements'],
  trades: ['Trades', 'ticks for VPIN/Hawkes'],
  depth: ['Depth', 'live L2 snapshots'],
};

const INTERVALS = ['1d', '4h', '1h', '15m', '5m', '1m'] as const;

interface ToggleProps<T extends string> {
  options: readonly (readonly [value: T, label: string, title?: string])[];
  value: T;
  onChange: (value: T) => void;
  columns?: string;
}

function Toggle<T extends string>({ options, value, onChange, columns }: ToggleProps<T>) {
  return (
    <div className={`grid ${columns ?? 'grid-cols-2'} gap-1.5`}>
      {options.map(([option, label, title]) => (
        <button
          key={option}
          type="button"
          title={title}
          onClick={() => onChange(option)}
          className={`px-2 py-2 rounded-xl text-xs font-medium border transition-colors ${
            value === option
              ? 'bg-blue-600/15 text-blue-300 border-blue-500/40'
              : 'bg-gray-950 text-gray-400 border-gray-800 hover:text-gray-200'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

const Label: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <label className="text-xs font-medium text-gray-300 block mb-1">{children}</label>
);

const inputClass =
  'w-full bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 font-mono';

interface IngestFormProps {
  form: IngestFormState;
  onChange: (patch: Partial<IngestFormState>) => void;
}

/** Source, market, series, symbols, interval and window of an ingest, plus warnings. */
export const IngestForm: React.FC<IngestFormProps> = ({ form, onChange }) => {
  const allowed = SERIES_BY_SOURCE[form.source];
  const warnings = ingestWarnings(form);

  const setSource = (source: IngestFormState['source']) =>
    onChange({
      source,
      series: SERIES_BY_SOURCE[source].includes(form.series) ? form.series : 'klines',
      symbols: source === 'rest' && form.symbols === 'all' ? 'BTCUSDT,ETHUSDT' : form.symbols,
    });

  return (
    <div className="flex flex-col gap-3 mt-2">
      <div>
        <Label>Source</Label>
        <Toggle
          value={form.source}
          onChange={setSource}
          options={[
            ['archive', 'Archive (history)', 'data.binance.vision: SHA256-verified, delisted coins'],
            ['rest', 'REST / live', 'public REST endpoints and WebSockets'],
          ]}
        />
      </div>

      <div>
        <Label>Series</Label>
        <Toggle
          columns="grid-cols-3"
          value={form.series}
          onChange={(series) => onChange({ series })}
          options={allowed.map((item) => [item, SERIES_LABELS[item][0], SERIES_LABELS[item][1]])}
        />
      </div>

      {form.source === 'archive' && form.series === 'klines' && (
        <div>
          <Label>Market</Label>
          <Toggle
            value={form.market}
            onChange={(market) => onChange({ market })}
            options={[
              ['spot', 'Spot'],
              ['um', 'USD-M perps'],
            ]}
          />
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-gray-300">Symbols</span>
          <div className="flex items-center gap-1 text-[10px]">
            {symbolPresets(form).map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => onChange({ symbols: preset.value })}
                className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-300 hover:text-white hover:bg-gray-700"
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
        <input
          type="text"
          value={form.symbols}
          onChange={(event) => onChange({ symbols: event.target.value })}
          placeholder={form.source === 'archive' ? 'BTCUSDT,ETHUSDT or all' : 'BTCUSDT or BTCUSDT-PERP'}
          className={inputClass}
        />
      </div>

      {usesInterval(form.series) && (
        <div>
          <Label>Bar interval</Label>
          <Toggle
            columns="grid-cols-6"
            value={form.interval}
            onChange={(interval) => onChange({ interval })}
            options={INTERVALS.map((item) => [item, item] as const)}
          />
        </div>
      )}

      {form.series !== 'depth' && (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label>Start (UTC)</Label>
            <input
              type="date"
              value={form.start}
              onChange={(event) => onChange({ start: event.target.value })}
              className={inputClass}
            />
          </div>
          <div>
            <Label>End, exclusive</Label>
            <input
              type="date"
              value={form.end}
              onChange={(event) => onChange({ end: event.target.value })}
              className={inputClass}
            />
          </div>
        </div>
      )}

      {form.source === 'archive' && (
        <p className="text-[11px] text-gray-500">
          Writes to <span className="font-mono text-gray-300">{archiveTarget(form)}</span> and
          stores a quality report beside it.
        </p>
      )}

      {warnings.map((warning) => (
        <p
          key={warning}
          className="text-[11px] text-amber-300 bg-amber-950/40 border border-amber-800/40 rounded-lg px-2 py-1.5"
        >
          {warning}
        </p>
      ))}
    </div>
  );
};
