import React, { useCallback, useEffect, useState } from 'react';
import { Download, Layers, RefreshCw } from 'lucide-react';
import { fetchBatches, importDecisionSweep } from '../../services/api';
import { buildBatchHash, STATUS_CLASS, type BatchListRow } from '../../lib/batch';
import { formatDateTime } from '../../lib/format';
import { BatchLaunchForm } from './BatchLaunchForm';

/**
 * Batch backtests: launch a robots x instruments matrix and open any earlier batch.
 *
 * Each batch row is a real link (`#/batch/<id>`), so it opens in a new tab with a
 * middle click; the batch's own table links every run the same way.
 */
export const BatchListPage: React.FC = () => {
  const [batches, setBatches] = useState<BatchListRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setBatches((await fetchBatches()).batches);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const importSweep = async () => {
    try {
      const { batch_id } = await importDecisionSweep();
      window.location.hash = buildBatchHash({ page: 'batch', batchId: batch_id });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="flex items-center gap-3">
        <Layers className="w-5 h-5 text-blue-400" />
        <h2 className="text-lg font-bold text-gray-100">Пакетний бектест</h2>
        <span className="text-xs text-gray-500">
          матриця роботів × інструментів, walk-forward, журнал рішень кожного OOS-фолду
        </span>
      </header>

      <BatchLaunchForm
        onStarted={(batchId) => {
          window.location.hash = buildBatchHash({ page: 'batch', batchId });
        }}
      />

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-gray-100">Пакети</h3>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void importSweep()}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-950 border border-gray-700 rounded-lg text-gray-300 hover:bg-gray-800"
              title="reports/decision-sweep → пакет (лише останній фолд, старий формат логу)"
            >
              <Download className="w-3.5 h-3.5" /> Імпорт свіпу 29.09
            </button>
            <button
              type="button"
              onClick={() => void load()}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-950 border border-gray-700 rounded-lg text-gray-300 hover:bg-gray-800"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Оновити
            </button>
          </div>
        </div>
        {error && <div className="text-xs text-red-400">{error}</div>}
        {batches.length === 0 ? (
          <p className="text-xs text-gray-500">
            Пакетів ще немає. Запустіть новий або імпортуйте свіп 29.09.
          </p>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-gray-500 text-[10px] uppercase">
              <tr>
                <th className="text-left py-1.5">Пакет</th>
                <th className="text-left">Створено</th>
                <th className="text-left">Стан</th>
                <th className="text-left">Прогони</th>
                <th className="text-left">Роботи</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => (
                <tr key={batch.id} className="border-t border-gray-800 hover:bg-gray-800/30">
                  <td className="py-1.5">
                    <a
                      href={buildBatchHash({ page: 'batch', batchId: batch.id })}
                      className="text-blue-400 hover:text-blue-300 font-mono"
                    >
                      {batch.label || batch.id}
                    </a>
                    {batch.imported_from && (
                      <span className="ml-2 text-[10px] text-amber-400/80">імпорт</span>
                    )}
                  </td>
                  <td className="text-gray-400">{formatDateTime(batch.created_at)}</td>
                  <td className={STATUS_CLASS[batch.status] ?? 'text-gray-400'}>{batch.status}</td>
                  <td className="font-mono text-gray-300">
                    {batch.cells}
                    <span className="text-gray-500">
                      {' '}
                      ({Object.entries(batch.counts)
                        .map(([k, v]) => `${k} ${v}`)
                        .join(', ')}
                      )
                    </span>
                  </td>
                  <td className="text-gray-400 font-mono">{batch.robots.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
