import React, { useState } from 'react';
import { Play } from 'lucide-react';
import { resumeBatch } from '../../services/api';
import { resumeBlockedReason, unfinishedCells, type BatchDetail } from '../../lib/batch';

const guardOf = (batch: BatchDetail | null) =>
  batch
    ? resumeBlockedReason({
        status: batch.status,
        counts: batch.progress?.counts,
        imported_from: batch.imported_from,
      })
    : 'пакет ще не завантажено';

interface ResumeButtonProps {
  batchId: string;
  batch: BatchDetail | null;
  onDone: () => Promise<void>;
  onError: (message: string | null) => void;
}

/**
 * "Продовжити" on the batch page: run only the cells a stopped batch never finished.
 *
 * Shown for a batch whose process died (`lost`: reboot, sleep, OOM, closed terminal) or that
 * was cancelled, as long as cells without a result remain (`POST /api/batches/{id}/resume`).
 * Finished cells keep their numbers; a cell cut off mid-run starts over from a clean log.
 */
export const BatchResumeButton: React.FC<ResumeButtonProps> = ({
  batchId,
  batch,
  onDone,
  onError,
}) => {
  const [busy, setBusy] = useState(false);
  if (guardOf(batch) !== null) return null;

  const resume = async () => {
    setBusy(true);
    try {
      const result = await resumeBatch(batchId);
      onError(result.status === 'nothing_to_resume' ? (result.message ?? null) : null);
      await onDone();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => void resume()}
      className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-amber-950/40 hover:bg-amber-950/70 border border-amber-800/60 rounded-lg text-amber-200 transition-colors disabled:opacity-50"
      title="Догнати клітинки, які не завершились; готові результати лишаються як є"
    >
      <Play className="w-3.5 h-3.5" /> Продовжити ({unfinishedCells(batch?.progress?.counts)})
    </button>
  );
};

/** Why a batch shows `lost`, and what "Продовжити" will do about it. */
export const LostBatchBanner: React.FC<{ batch: BatchDetail | null }> = ({ batch }) => {
  if (batch?.status !== 'lost') return null;
  const unfinished = unfinishedCells(batch.progress?.counts);
  return (
    <div className="p-3 rounded-lg bg-red-950/30 border border-red-800/50 text-xs text-red-200">
      Процес пакета зупинився, не дописавши результат (перезавантаження, сон, нестача пам'яті
      чи закритий термінал).
      {unfinished > 0 && ` Незавершених клітинок: ${unfinished}.`} «Продовжити» запустить лише
      їх; готові клітинки й їхні числа лишаються.
    </div>
  );
};
