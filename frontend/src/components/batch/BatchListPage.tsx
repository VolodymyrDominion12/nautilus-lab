import React, { useCallback, useEffect, useState } from 'react';
import { Download, Hammer, Layers, Play, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import {
  deleteBatch,
  fetchBatches,
  importDecisionSweep,
  restartBatch,
  resumeBatch,
  retryBatch,
} from '../../services/api';
import {
  buildBatchHash,
  restartBlockedReason,
  resumeBlockedReason,
  resumeHint,
  retryBlockedReason,
  restartHint,
  unfinishedCells,
  STATUS_CLASS,
  type BatchListRow,
} from '../../lib/batch';
import { formatDateTime } from '../../lib/format';
import { BatchLaunchForm } from './BatchLaunchForm';

/**
 * Batch backtests: launch a robots x instruments matrix and open any earlier batch.
 *
 * Each batch row is a real link (`#/batch/<id>`), so it opens in a new tab with a
 * middle click; the batch's own table links every run the same way.
 *
 * A row can be deleted or re-run. "Перезапустити" is not "запустити ще раз": the batch's
 * artifacts are deleted first (`POST /api/batches/{id}/restart`, `batch_store.reset_batch`),
 * so the numbers the table shows afterwards are the new run's and not a mix of the two.
 * "Продовжити" is the opposite: a batch that stopped half-way (the machine rebooted, the
 * process was killed, or it was cancelled) keeps every finished cell and runs only the rest
 * (`POST /api/batches/{id}/resume`).
 */
export const BatchListPage: React.FC = () => {
  const [batches, setBatches] = useState<BatchListRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [restartingId, setRestartingId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [resumingId, setResumingId] = useState<string | null>(null);
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

  const handleDelete = async (batchId: string, label?: string) => {
    const name = label || batchId;
    if (!window.confirm(`Видалити пакет "${name}" та всі результати його прогонів, угод і логів?`)) {
      return;
    }
    setDeletingId(batchId);
    setError(null);
    try {
      await deleteBatch(batchId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingId(null);
    }
  };

  const handleRestart = async (batch: BatchListRow) => {
    const name = batch.label || batch.id;
    const confirmed = window.confirm(
      `Перезапустити пакет "${name}"?\n\n` +
        'Старі результати, журнали рішень, угоди, кеш таблиці та журнал спроб буде ' +
        'видалено, і той самий прогін запуститься заново під тим самим id.',
    );
    if (!confirmed) return;
    setRestartingId(batch.id);
    setError(null);
    try {
      await restartBatch(batch.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRestartingId(null);
    }
  };

  const handleRetry = async (batch: BatchListRow) => {
    const name = batch.label || batch.id;
    const failed = batch.counts?.failed ?? 0;
    const blocked = batch.counts?.blocked ?? 0;
    const confirmed = window.confirm(
      `Повторити невдалі клітинки пакета "${name}"?\n\n` +
        `Буде перезапущено лише ті, у яких немає результату (failed: ${failed}, blocked: ${blocked}). ` +
        'Клітинки з результатом, їхні числа, журнали рішень і угоди лишаються як є.',
    );
    if (!confirmed) return;
    setRetryingId(batch.id);
    setError(null);
    try {
      const result = await retryBatch(batch.id);
      if (result.status === 'nothing_to_retry') {
        setError(result.message ?? 'Немає клітинок без результату.');
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRetryingId(null);
    }
  };

  const handleResume = async (batch: BatchListRow) => {
    setResumingId(batch.id);
    setError(null);
    try {
      const result = await resumeBatch(batch.id);
      if (result.status === 'nothing_to_resume') {
        setError(result.message ?? 'Усі клітинки завершені.');
      } else {
        window.location.hash = buildBatchHash({ page: 'batch', batchId: batch.id });
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setResumingId(null);
    }
  };

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
                <th className="text-right py-1.5 pr-2">Дія</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => {
                const restartReason = restartBlockedReason(batch);
                const retryReason = retryBlockedReason(batch);
                const resumeReason = resumeBlockedReason(batch);
                const hint = restartHint(batch);
                const resumed = resumeHint(batch);
                const busyHere =
                  deletingId === batch.id ||
                  restartingId === batch.id ||
                  retryingId === batch.id ||
                  resumingId === batch.id;
                return (
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
                    <td className="text-gray-400">
                      {formatDateTime(batch.created_at)}
                      {hint && <div className="text-[10px] text-gray-500">{hint}</div>}
                      {resumed && <div className="text-[10px] text-gray-500">{resumed}</div>}
                    </td>
                    <td className={STATUS_CLASS[batch.status] ?? 'text-gray-400'}>
                      {batch.status}
                    </td>
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
                    <td className="text-right py-1.5 pr-2">
                      <div className="inline-flex items-center gap-1">
                        {resumeReason === null && (
                          <button
                            type="button"
                            disabled={busyHere}
                            onClick={() => void handleResume(batch)}
                            className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-amber-300 hover:text-amber-200 hover:bg-amber-950/40 border border-amber-800/60 rounded transition-colors disabled:opacity-40"
                            title={`Продовжити з місця зупинки: ${unfinishedCells(batch.counts)} незавершених клітинок, готові лишаються як є`}
                          >
                            <Play
                              className={`w-3.5 h-3.5 ${resumingId === batch.id ? 'animate-pulse' : ''}`}
                            />
                            <span>Продовжити</span>
                          </button>
                        )}
                        <button
                          type="button"
                          disabled={busyHere || retryReason !== null}
                          onClick={() => void handleRetry(batch)}
                          className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-emerald-400 hover:text-emerald-300 hover:bg-emerald-950/40 border border-transparent hover:border-emerald-800/60 rounded transition-colors disabled:opacity-40"
                          title={
                            retryReason ??
                            'Догнати лише невдалі клітинки: результат решти лишається на місці'
                          }
                        >
                          <Hammer
                            className={`w-3.5 h-3.5 ${retryingId === batch.id ? 'animate-spin' : ''}`}
                          />
                          <span>Повторити невдалі</span>
                        </button>
                        <button
                          type="button"
                          disabled={busyHere || restartReason !== null}
                          onClick={() => void handleRestart(batch)}
                          className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-blue-400 hover:text-blue-300 hover:bg-blue-950/40 border border-transparent hover:border-blue-800/60 rounded transition-colors disabled:opacity-40"
                          title={
                            restartReason ??
                            'Видалити результати цього пакета і запустити той самий прогін заново'
                          }
                        >
                          <RotateCcw
                            className={`w-3.5 h-3.5 ${restartingId === batch.id ? 'animate-spin' : ''}`}
                          />
                          <span>Перезапустити</span>
                        </button>
                        <button
                          type="button"
                          disabled={busyHere}
                          onClick={() => void handleDelete(batch.id, batch.label)}
                          className="inline-flex items-center gap-1 px-2 py-1 text-[11px] text-red-400 hover:text-red-300 hover:bg-red-950/40 border border-transparent hover:border-red-800/60 rounded transition-colors disabled:opacity-50"
                          title="Видалити цей пакет і всі його результати бектестів, угод і логів"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          <span>Видалити</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
