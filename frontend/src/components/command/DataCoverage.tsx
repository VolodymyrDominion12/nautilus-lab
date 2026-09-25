import React from 'react';
import { CheckCircle, Database } from 'lucide-react';

import type { CommandCenterResponse } from '../../services/api';

/** Which optional series (taker flow, ticks, depth, funding) sit beside the bars. */
export const DataCoverage: React.FC<{ data: CommandCenterResponse | null }> = ({ data }) => {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Database className="w-5 h-5 text-cyan-400" />
          <h3 className="font-semibold text-gray-100">Data coverage</h3>
        </div>
        {data?.catalog_bar_interval && (
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-gray-950 text-gray-300 border-gray-800">
            {data.catalog_bar_interval} bars
          </span>
        )}
      </div>
      {(data?.data_series?.length ?? 0) === 0 ? (
        <p className="text-sm text-gray-500">
          This catalog holds no bar series yet. Run an ingest from the Parquet Catalog tab.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] font-mono">
              <thead className="text-gray-500">
                <tr>
                  <th className="text-left p-1.5">instrument</th>
                  <th className="text-right p-1.5">bars</th>
                  <th className="text-left p-1.5">bars until</th>
                  <th className="text-center p-1.5">taker flow</th>
                  <th className="text-center p-1.5">ticks</th>
                  <th className="text-center p-1.5">depth</th>
                  <th className="text-center p-1.5">funding</th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                {(data?.data_series ?? []).map((row) => (
                  <tr key={row.instrument_id} className="border-t border-gray-800/60">
                    <td className="p-1.5 text-blue-300">{row.instrument_id}</td>
                    <td className="p-1.5 text-right">{row.bars.toLocaleString()}</td>
                    <td className="p-1.5 text-gray-500">{row.bars_last?.slice(0, 10) ?? '—'}</td>
                    <td className="p-1.5 text-center">
                      {row.taker_flow ? (
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-400 inline" />
                      ) : (
                        <span className="text-amber-400">missing</span>
                      )}
                    </td>
                    <td className="p-1.5 text-center">
                      {row.ticks ? (
                        <span className="text-emerald-400">
                          {row.tick_rows?.toLocaleString() ?? 'yes'}
                        </span>
                      ) : (
                        <span className="text-amber-400">missing</span>
                      )}
                    </td>
                    <td className="p-1.5 text-center">
                      {row.orderbook ? (
                        <span className="text-emerald-400">
                          {row.orderbook_rows?.toLocaleString() ?? 'yes'}
                        </span>
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                    <td className="p-1.5 text-center">
                      {row.funding ? (
                        <CheckCircle className="w-3.5 h-3.5 text-emerald-400 inline" />
                      ) : (
                        <span className="text-amber-400">missing</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-gray-500">
            A missing optional series does not fail a run: the engine reads it as empty. A
            tick-level VPIN or Hawkes filter chosen without ticks therefore measures its own
            defaults, which is why the research form refuses that combination.
          </p>
        </>
      )}
    </div>
  );
};
