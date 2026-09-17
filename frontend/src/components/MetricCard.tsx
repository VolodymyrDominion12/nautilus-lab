import React from 'react';
import { TONE_BORDER, TONE_TEXT } from '../lib/format';
import type { Tone } from '../lib/format';

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: Tone;
  /** Small right-aligned tag, e.g. "in-sample only". */
  tag?: string;
  tagClassName?: string;
}

/** One number with the context needed to read it. Used across every result panel. */
export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  hint,
  tone = 'neutral',
  tag,
  tagClassName,
}) => (
  <div className={`bg-gray-900 border ${TONE_BORDER[tone]} p-5 rounded-2xl flex flex-col gap-1`}>
    <div className="flex items-start justify-between gap-2">
      <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{label}</span>
      {tag && (
        <span
          className={`text-[10px] font-mono px-1.5 py-0.5 rounded border whitespace-nowrap ${
            tagClassName ?? 'bg-gray-950 text-gray-400 border-gray-800'
          }`}
        >
          {tag}
        </span>
      )}
    </div>
    <span className={`text-2xl font-bold font-mono ${TONE_TEXT[tone]}`}>{value}</span>
    {hint && <span className="text-[11px] text-gray-500 mt-1 leading-tight">{hint}</span>}
  </div>
);
