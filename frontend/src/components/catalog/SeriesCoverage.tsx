import React from 'react';
import { Layers } from 'lucide-react';

import type { DataHealthInstrument } from '../../services/api';
import type { CatalogInstrument } from './InstrumentCards';

interface SeriesCoverageProps {
  health: DataHealthInstrument[];
  instruments: CatalogInstrument[];
}

/**
 * Which optional series sit beside the bars. One catalog is four independent trees, and
 * the engine reads a missing optional series as an empty one, so "the bars are here" says
 * nothing about whether a tick-level filter would have had any data behind it.
 */
export const SeriesCoverage: React.FC<SeriesCoverageProps> = ({ health, instruments }) => {
  if (health.length === 0) return null;
  const seriesRows = health.map((item) => {
    const inst = instruments.find((candidate) => candidate.instrument_id === item.instrument_id);
    return { item, symbol: inst?.raw_symbol ?? item.instrument_id };
  });
  const tickReady = health.some((item) => item.ticks.present);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-cyan-400" />
          <h3 className="text-sm font-bold text-gray-100">Series beside the bars</h3>
        </div>
        <span
          className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${
            tickReady
              ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50'
              : 'bg-amber-950/60 text-amber-300 border-amber-800/50'
          }`}
        >
          {tickReady
            ? 'tick filters usable'
            : 'no ticks: tick VPIN / Hawkes would run on defaults'}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono">
          <thead className="text-gray-500">
            <tr>
              <th className="text-left p-1.5">instrument</th>
              <th className="text-right p-1.5">bars</th>
              <th className="text-right p-1.5">taker flow</th>
              <th className="text-right p-1.5">ticks</th>
              <th className="text-right p-1.5">depth</th>
              <th className="text-left p-1.5">ticks until</th>
              <th className="text-right p-1.5">funding</th>
            </tr>
          </thead>
          <tbody className="text-gray-300">
            {seriesRows.map(({ item, symbol }) => (
              <tr key={item.instrument_id} className="border-t border-gray-800/60">
                <td className="p-1.5 text-blue-300">
                  {symbol}
                  {item.symbol && <span className="text-gray-600"> · {item.symbol}</span>}
                </td>
                <td className="p-1.5 text-right">{item.bars.rows?.toLocaleString() ?? 'n/a'}</td>
                <td className="p-1.5 text-right">
                  {item.taker_flow.present ? (
                    <span className="text-emerald-400">
                      {item.taker_flow.rows?.toLocaleString() ?? 'yes'}
                    </span>
                  ) : (
                    <span className="text-amber-400">missing</span>
                  )}
                </td>
                <td className="p-1.5 text-right">
                  {item.ticks.present ? (
                    <span className="text-emerald-400">
                      {item.ticks.rows?.toLocaleString() ?? `${item.ticks.files} files`}
                    </span>
                  ) : (
                    <span className="text-amber-400">missing</span>
                  )}
                </td>
                <td className="p-1.5 text-right">
                  {item.orderbook.present ? (
                    <span className="text-emerald-400">
                      {item.orderbook.rows?.toLocaleString() ??
                        `${item.orderbook.files} files`}
                    </span>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </td>
                <td className="p-1.5 text-gray-500">
                  {item.ticks.last ? item.ticks.last.slice(0, 10) : '—'}
                </td>
                <td className="p-1.5 text-right">
                  {item.funding.present ? (
                    <span className="text-emerald-400">
                      {item.funding.rows?.toLocaleString() ?? 'yes'}
                    </span>
                  ) : (
                    <span className="text-amber-400">missing</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-gray-600">
        Tick spans are UTC-day resolution (one Parquet shard per day), so the last day is the
        newest day present, not the newest tick. An empty optional series is read as an empty
        one by the engine — it does not fail the run.
      </p>
    </div>
  );
};
