import React from 'react';
import type { GateVerdict } from '../../lib/batch';

const LABEL_CLASS: Record<string, string> = {
  PROMOTE: 'bg-emerald-950/60 text-emerald-300 border-emerald-800/50',
  REJECT: 'bg-red-950/60 text-red-300 border-red-800/50',
  INCOMPLETE: 'bg-amber-950/60 text-amber-300 border-amber-800/50',
};

/**
 * The promotion verdict (`application/promotion_gate.py`), shown wherever a run appears.
 *
 * It used to exist only as one line of log text, so the batch table — the screen built for
 * comparing cells — could not show the one number the comparison is for. `INCOMPLETE` is a
 * real answer, not an error: a cell that never ran the overfitting audit has `pbo` and
 * `dsr` unmeasured, and an unmeasured check must never read as a pass.
 */
export const GateBadge: React.FC<{ gate?: GateVerdict | null; size?: 'sm' | 'md' }> = ({
  gate,
  size = 'sm',
}) => {
  if (!gate) {
    return <span className="font-mono text-gray-600">—</span>;
  }
  const failing = gate.checks.filter((check) => check.status === 'fail');
  const unmeasured = gate.checks.filter((check) => check.status === 'not measured');
  const title = [
    gate.summary_line,
    ...gate.checks.map((check) => `${check.name}=${check.status}: ${check.detail}`),
  ].join('\n');
  return (
    <span className="flex flex-col gap-0.5" title={title}>
      <span
        className={`inline-block w-fit rounded border px-1.5 py-0.5 font-mono ${
          size === 'md' ? 'text-[11px]' : 'text-[10px]'
        } ${LABEL_CLASS[gate.label] ?? 'bg-gray-900 text-gray-400 border-gray-700'}`}
      >
        {gate.label}
      </span>
      {(failing.length > 0 || unmeasured.length > 0) && (
        <span className="text-[10px] text-gray-500">
          {failing.length > 0 && `${failing.length} fail`}
          {failing.length > 0 && unmeasured.length > 0 && ' · '}
          {unmeasured.length > 0 && `${unmeasured.length} not measured`}
        </span>
      )}
    </span>
  );
};
