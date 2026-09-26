import React from 'react';
import { TONE_BORDER, TONE_TEXT } from '../lib/format';
import type { Tone } from '../lib/format';
import { InfoTooltip } from './InfoTooltip';
import type { GlossaryKey } from '../lib/glossary';

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: Tone;
  /** Small right-aligned tag, e.g. "in-sample only". */
  tag?: string;
  tagClassName?: string;
  /** Direct glossary key or custom tooltip content */
  infoKey?: GlossaryKey;
  infoTooltip?: React.ReactNode;
}

/** Automatically detects glossary key from standard metric labels if not explicitly passed */
const detectGlossaryKey = (label: string): GlossaryKey | undefined => {
  const normalized = label.toLowerCase().trim();
  if (normalized.includes('oos mean') || normalized.includes('oos return')) return 'oos_return';
  if (normalized.includes('in-sample') || normalized.includes('is mean')) return 'is_return';
  if (normalized.includes('buy & hold') || normalized.includes('buy&hold')) return 'buy_and_hold';
  if (normalized.includes('excess return') || normalized.includes('alpha')) return 'excess_return';
  if (normalized.includes('profitable folds')) return 'profitable_folds';
  if (normalized.includes('breakeven cost')) return 'breakeven_cost';
  if (normalized.includes('paid cost')) return 'paid_cost_rate';
  if (normalized.includes('cost headroom')) return 'cost_headroom';
  if (normalized === 'pbo' || normalized.includes('probability of backtest overfitting')) return 'pbo';
  if (normalized.includes('ending balance') || normalized.includes('balance')) return 'ending_balance';
  if (normalized.includes('deflated sharpe')) return 'deflated_sharpe';
  if (normalized.includes('haircut sharpe')) return 'haircut_sharpe';
  if (normalized.includes('sharpe')) return 'sharpe_like';
  if (normalized.includes('configurations tried') || normalized.includes('configurations')) return 'configurations_tried';
  if (normalized.includes('spread across folds') || normalized.includes('fold spread')) return 'fold_spread';
  if (normalized.includes('cscv splits') || normalized.includes('cscv')) return 'cscv';
  if (normalized.includes('drawdown')) return 'max_drawdown';
  if (normalized.includes('total oos fills') || normalized.includes('total fills') || normalized.includes('fills')) return 'total_fills';
  if (normalized.includes('data coverage')) return 'data_coverage';
  return undefined;
};

/** One number with the context needed to read it. Used across every result panel. */
export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  hint,
  tone = 'neutral',
  tag,
  tagClassName,
  infoKey,
  infoTooltip,
}) => {
  const resolvedKey = infoKey ?? detectGlossaryKey(label);

  return (
    <div className={`bg-gray-900 border ${TONE_BORDER[tone]} p-5 rounded-2xl flex flex-col gap-1`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{label}</span>
          {resolvedKey && <InfoTooltip term={resolvedKey} size="xs" />}
          {!resolvedKey && infoTooltip && <InfoTooltip content={infoTooltip} size="xs" />}
        </div>
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
};

