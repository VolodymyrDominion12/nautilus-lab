import React from 'react';
import type { DecisionDigest } from '../services/api';

/**
 * Always-visible summary of one session's decision log: how many bars, what the
 * robot did (outcomes), which regime it spent time in, and what blocked entries.
 *
 * The server already counts these (`decision_digest.py`); this just renders the
 * counts, so the "why" is one glance away instead of behind the LLM button.
 */

const OUTCOME_LABELS: Record<string, string> = {
  ENTRY_OPENED: 'Входи',
  REVERSE: 'Розвороти',
  EXIT: 'Виходи',
  FLATTEN_REGIME_CHANGE: 'Зміна режиму',
  STOP_LOSS: 'Стоп-лос',
  TAKE_PROFIT: 'Тейк-профіт',
  MANUAL_CLOSE: 'Ручне закриття',
  ENTRY_BLOCKED_RISK: 'Блоки входу',
  ENTRY_SKIPPED_PAUSED: 'Пауза',
  ENTRY_SKIPPED_SIZE: 'Розмір 0',
  HOLD_NOOP: 'Утримання',
  NO_SIGNAL: 'Без сигналу',
  WARMUP: 'Прогрів',
};

export const DecisionDigestSummary: React.FC<{ digest: DecisionDigest }> = ({ digest }) => (
  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-gray-400 border border-gray-800 rounded-lg px-3 py-2 bg-gray-950/40">
    <span>
      <span className="text-gray-500">Барів:</span>{' '}
      <span className="font-mono text-gray-200">{digest.bars}</span>
      {digest.bar_seq_gaps > 0 && (
        <span className="text-amber-300"> · пропусків {digest.bar_seq_gaps}</span>
      )}
      {digest.regime_switches > 0 && (
        <span className="text-gray-500"> · перемикань режиму {digest.regime_switches}</span>
      )}
    </span>
    {Object.keys(digest.outcomes).length > 0 && (
      <span className="flex flex-wrap gap-x-2 gap-y-0.5">
        {Object.entries(digest.outcomes).map(([code, count]) => (
          <span key={code} className="text-gray-400">
            <span className="text-gray-500">{OUTCOME_LABELS[code] ?? code}:</span>{' '}
            <span className="font-mono text-gray-200">{count}</span>
          </span>
        ))}
      </span>
    )}
    {Object.keys(digest.regime_share_pct).length > 0 && (
      <span className="flex flex-wrap gap-x-2 gap-y-0.5">
        {Object.entries(digest.regime_share_pct).map(([regime, pct]) => (
          <span key={regime} className="text-gray-400">
            <span className="font-mono text-gray-200">{regime}</span>{' '}
            <span className="font-mono text-gray-400">{pct}%</span>
          </span>
        ))}
      </span>
    )}
    {Object.keys(digest.blocked_by).length > 0 && (
      <span className="flex flex-wrap gap-x-2 gap-y-0.5 text-amber-300/90">
        <span className="text-gray-500">Блокувало:</span>
        {Object.entries(digest.blocked_by).map(([code, count]) => (
          <span key={code} className="font-mono">
            {code}: {count}
          </span>
        ))}
      </span>
    )}
    {digest.near_misses > 0 && (
      <span>
        <span className="text-gray-500">Майже-сигнали:</span>{' '}
        <span className="font-mono text-gray-200">{digest.near_misses}</span>
      </span>
    )}
  </div>
);
