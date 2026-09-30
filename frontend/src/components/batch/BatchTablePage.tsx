import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, RefreshCw, Square } from 'lucide-react';
import { cancelBatch, fetchBatch } from '../../services/api';
import {
  blockedShare,
  buildBatchHash,
  rowWarnings,
  sortRows,
  STATUS_CLASS,
  topCounts,
  type BatchDetail,
  type SortKey,
} from '../../lib/batch';
import { TONE_TEXT, formatDateTime, formatPct, toneOf } from '../../lib/format';

interface BatchTablePageProps {
  batchId: string;
}

const COLUMNS: { key: SortKey; label: string; title: string }[] = [
  { key: 'cell', label: 'Прогін', title: 'робот_інструмент' },
  { key: 'mean_oos', label: 'Mean OOS', title: 'середня доходність OOS-фолдів після комісій' },
  { key: 'worst_oos', label: 'Worst', title: 'найгірший OOS-фолд' },
  { key: 'excess', label: 'vs B&H', title: 'mean OOS мінус buy&hold того ж вікна' },
  { key: 'trades', label: 'Угоди', title: 'закриті угоди в журналі всіх OOS-фолдів' },
  { key: 'win_rate', label: 'Win', title: 'частка прибуткових угод' },
  { key: 'blocked', label: 'Блоки', title: 'частка барів, де вхід заблоковано' },
];

/**
 * The table of one batch: a row per run, sortable, each row a link to its run page.
 *
 * Numbers come with the decision log's view of them — what the bars mostly did, what
 * blocked entries, and warnings (no trace, no trades, mostly blocked) — because a return
 * without its "why" is exactly what this page exists to avoid.
 */
export const BatchTablePage: React.FC<BatchTablePageProps> = ({ batchId }) => {
  const [batch, setBatch] = useState<BatchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('mean_oos');
  const [descending, setDescending] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setBatch((await fetchBatch(batchId)).batch);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => {
    void load();
  }, [load]);

  const running = batch?.status === 'running' || batch?.status === 'queued';
  useEffect(() => {
    if (!running) return undefined;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [running, load]);

  const rows = useMemo(
    () => (batch ? sortRows(batch.rows, sortKey, descending) : []),
    [batch, sortKey, descending],
  );

  const onSort = (key: SortKey) => {
    if (key === sortKey) setDescending(!descending);
    else {
      setSortKey(key);
      setDescending(key !== 'cell');
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center gap-3 border-b border-gray-800 pb-3">
        <a
          href={buildBatchHash({ page: 'list' })}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg border border-gray-700"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Пакети
        </a>
        <h2 className="text-lg font-bold text-gray-100">{batch?.label || batchId}</h2>
        {batch && (
          <span className={`text-xs font-mono ${STATUS_CLASS[batch.status] ?? ''}`}>
            {batch.status}
          </span>
        )}
        <span className="text-xs text-gray-500">{formatDateTime(batch?.created_at)}</span>
        {batch?.request && (
          <span className="text-xs text-gray-400 font-mono bg-gray-900/80 px-2 py-0.5 rounded border border-gray-800">
            {String(batch.request.interval ?? '1h')} · фолди: {String(batch.request.folds ?? '—')}
            {batch.request.days != null ? ` · ${String(batch.request.days)} дн.` : ' · вся історія'}
          </span>
        )}
        <div className="ml-auto flex gap-2">
          {running && (
            <button
              type="button"
              onClick={() => void cancelBatch(batchId).then(load)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-red-950/40 border border-red-800/60 rounded-lg text-red-300"
            >
              <Square className="w-3 h-3" /> Зупинити
            </button>
          )}
          <button
            type="button"
            onClick={() => void load()}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 border border-gray-700 rounded-lg text-gray-300"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Оновити
          </button>
        </div>
      </header>

      {batch?.note && (
        <div className="p-3 rounded-lg bg-amber-950/30 border border-amber-800/50 text-xs text-amber-200">
          {batch.note}
        </div>
      )}
      {error && <div className="text-xs text-red-400">{error}</div>}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-gray-500 text-[10px] uppercase">
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.key}
                  title={column.title}
                  onClick={() => onSort(column.key)}
                  className="text-left py-2 pr-3 cursor-pointer select-none hover:text-gray-300"
                >
                  {column.label}
                  {sortKey === column.key ? (descending ? ' ↓' : ' ↑') : ''}
                </th>
              ))}
              <th className="text-left pr-3">Що робили бари</th>
              <th className="text-left pr-3">Що блокувало</th>
              <th className="text-left">Стан</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const warnings = rowWarnings(row);
              const share = blockedShare(row);
              return (
                <tr key={row.cell_id} className="border-t border-gray-800 hover:bg-gray-800/30 align-top">
                  <td className="py-2 pr-3">
                    <a
                      href={buildBatchHash({ page: 'run', batchId, cellId: row.cell_id })}
                      className="text-blue-400 hover:text-blue-300 font-mono"
                    >
                      {row.cell_id}
                    </a>
                    <div className="text-[10px] text-gray-500">
                      {row.interval} · {row.numbers?.profitable ?? '—'} фолдів у плюсі
                    </div>
                  </td>
                  <td className={`pr-3 font-mono ${TONE_TEXT[toneOf(row.numbers?.mean_oos)]}`}>
                    {formatPct(row.numbers?.mean_oos)}
                  </td>
                  <td className={`pr-3 font-mono ${TONE_TEXT[toneOf(row.numbers?.worst_oos)]}`}>
                    {formatPct(row.numbers?.worst_oos)}
                  </td>
                  <td className={`pr-3 font-mono ${TONE_TEXT[toneOf(row.numbers?.mean_excess)]}`}>
                    {formatPct(row.numbers?.mean_excess)}
                  </td>
                  <td className="pr-3 font-mono text-gray-300">{row.trades?.closed ?? '—'}</td>
                  <td className="pr-3 font-mono text-gray-300">
                    {row.trades?.win_rate == null ? '—' : `${Math.round(row.trades.win_rate * 100)}%`}
                  </td>
                  <td className="pr-3 font-mono text-gray-300">
                    {share == null ? '—' : `${Math.round(share * 100)}%`}
                  </td>
                  <td className="pr-3 font-mono text-[10px] text-gray-400">
                    {topCounts(row.decisions?.outcomes)}
                  </td>
                  <td className="pr-3 font-mono text-[10px] text-gray-400">
                    {topCounts(row.decisions?.blocked_by, 2)}
                  </td>
                  <td>
                    <span className={`font-mono ${STATUS_CLASS[row.status] ?? 'text-gray-400'}`}>
                      {row.status}
                    </span>
                    {row.error && (
                      <div className="text-[10px] text-red-400/80 max-w-xs">{row.error}</div>
                    )}
                    {warnings.map((warning) => (
                      <div key={warning} className="flex items-center gap-1 text-[10px] text-amber-400">
                        <AlertTriangle className="w-3 h-3" /> {warning}
                      </div>
                    ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
