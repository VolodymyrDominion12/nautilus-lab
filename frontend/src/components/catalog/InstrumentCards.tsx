import React from 'react';
import { CheckCircle, Clock } from 'lucide-react';

import { formatBps } from '../../lib/format';
import type { CatalogResponse } from '../../services/api';

export type CatalogInstrument = CatalogResponse['instruments'][number];

interface InstrumentCardsProps {
  instruments: CatalogInstrument[];
  /** The instrument the price preview shows. */
  selected: string | undefined;
  onChart: (instrumentId: string) => void;
}

/** One card per instrument: bars, fees, coverage, and the "chart this" switch. */
export const InstrumentCards: React.FC<InstrumentCardsProps> = ({ instruments, selected, onChart }) => (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {instruments.length > 0 ? (
        instruments.map((inst) => {
          const spanDays =
            inst.first_date && inst.last_date
              ? Math.round(
                  (Date.parse(inst.last_date) - Date.parse(inst.first_date)) / 86_400_000,
                )
              : null;
          return (
            <div
              key={inst.instrument_id}
              className={`bg-gray-900 border p-5 rounded-2xl flex flex-col gap-3 transition-colors ${
                selected === inst.instrument_id ? 'border-blue-600/60' : 'border-gray-800'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-lg font-bold text-gray-100">{inst.raw_symbol}</span>
                <span className="px-2.5 py-0.5 text-xs font-medium bg-blue-950/60 text-blue-400 border border-blue-800/50 rounded-full">
                  {inst.quote_currency}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-xs pt-2 border-t border-gray-800/80">
                <div>
                  <span className="text-gray-500 block">Bars</span>
                  <span className="font-mono text-sm font-semibold text-gray-200">
                    {inst.bars_count.toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 block">Taker fee</span>
                  <span className="font-mono text-sm text-gray-300">
                    {formatBps(inst.taker_fee, 2)}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 block">Maker fee</span>
                  <span className="font-mono text-sm text-gray-300">
                    {formatBps(inst.maker_fee, 2)}
                  </span>
                </div>
              </div>

              <div className="text-xs pt-2 border-t border-gray-800/80 flex flex-col gap-1 text-gray-400 font-mono">
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-gray-500" />
                  <span className="text-gray-500">From:</span> {inst.first_date?.slice(0, 19) || 'n/a'}
                </div>
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-gray-500" />
                  <span className="text-gray-500">To:</span> {inst.last_date?.slice(0, 19) || 'n/a'}
                </div>
                {spanDays != null && (
                  <div className="text-gray-500">
                    span: {spanDays.toLocaleString()} days ·{' '}
                    {spanDays > 0 ? Math.round(inst.bars_count / spanDays) : '?'} bars/day
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between gap-2 mt-1">
                <span className="flex items-center gap-1 text-xs text-emerald-400">
                  <CheckCircle className="w-3.5 h-3.5" />
                  <span>Ready for walk-forward</span>
                </span>
                <button
                  type="button"
                  onClick={() => onChart(inst.instrument_id)}
                  className={`text-[11px] px-2 py-0.5 rounded-lg border ${
                    selected === inst.instrument_id
                      ? 'bg-blue-600 text-white border-blue-500'
                      : 'bg-gray-950 text-gray-400 border-gray-800 hover:text-gray-200'
                  }`}
                >
                  chart this
                </button>
              </div>
            </div>
          );
        })
      ) : (
        <div className="col-span-full p-8 bg-gray-900 border border-gray-800 rounded-2xl text-center text-gray-500">
          No instruments found in this catalog. Run an ingest below to download Binance klines.
        </div>
      )}
    </div>
);
