import React from 'react';
import type { GateVerdict } from '../../lib/batch';
import { GateBadge } from './GateBadge';

interface GateSummaryProps {
  gate: GateVerdict | null;
  /** Present only when the dashboard can open another tab; the button hides without it. */
  onPromoteCandidate?: () => void;
}

/**
 * The promotion verdict in full: the badge, every check, and what to do about it.
 *
 * A batch cell can never be PROMOTE — it runs no overfitting audit and carries no
 * registration — and saying only "REJECT" would leave the reader to guess whether the idea
 * failed or was never tested properly. The candidate button is the honest next step: the
 * same robot, instrument and fold count, with the audit half switched on.
 */
export const GateSummary: React.FC<GateSummaryProps> = ({ gate, onPromoteCandidate }) => {
  if (!gate) return null;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-3">
        <GateBadge gate={gate} size="md" />
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono">
          {gate.checks.map((check) => (
            <span
              key={check.name}
              title={check.detail}
              className={
                check.status === 'pass'
                  ? 'text-emerald-400/80'
                  : check.status === 'fail'
                    ? 'text-red-400/80'
                    : 'text-gray-500'
              }
            >
              {check.name}={check.status}
            </span>
          ))}
        </div>
      </div>
      {gate.label !== 'PROMOTE' && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-[11px] text-gray-500">
            Клітинка пакета не рахує PBO/DSR і не має пререєстрації, тож її вердикт не може бути
            PROMOTE. Кандидата переганяють окремо: Research Lab із аудитом і тими самими фолдами, а
            гіпотезу записують до прогону.
          </p>
          {onPromoteCandidate && (
            <button
              type="button"
              onClick={onPromoteCandidate}
              className="px-2.5 py-1 text-[11px] rounded-lg border border-purple-800/60 bg-purple-950/40 text-purple-200 hover:bg-purple-900/40"
              title="Відкрити Research Lab із цим роботом, інструментом і кількістю фолдів; аудит увімкнеться, гіпотезу вписуєте ви"
            >
              Перегнати як кандидата
            </button>
          )}
        </div>
      )}
    </div>
  );
};
