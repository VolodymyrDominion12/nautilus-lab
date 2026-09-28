import React from 'react';
import type { TradeDecisionRow } from '../services/api';

/**
 * A one-glance strip of a session's decisions: every closed bar is a thin segment
 * colored by its regime, with a dot marking the pivotal outcomes (entry, exit, stop,
 * block). It answers "was the robot mostly in range, and where did it actually act?"
 * without opening the rows underneath.
 */

const REGIME_COLORS: Record<string, string> = {
  uptrend: '#10b981',
  downtrend: '#ef4444',
  range: '#64748b',
  WARMUP: '#1f2937',
  UNKNOWN: '#1f2937',
  '': '#1f2937',
};

const MARKERS: Record<string, { color: string; label: string }> = {
  ENTRY_OPENED: { color: '#10b981', label: 'Вхід' },
  REVERSE: { color: '#a78bfa', label: 'Розворот' },
  EXIT: { color: '#38bdf8', label: 'Вихід' },
  FLATTEN_REGIME_CHANGE: { color: '#a78bfa', label: 'Зміна режиму' },
  STOP_LOSS: { color: '#ef4444', label: 'Стоп' },
  TAKE_PROFIT: { color: '#10b981', label: 'Тейк' },
  MANUAL_CLOSE: { color: '#f59e0b', label: 'Ручне закриття' },
  ENTRY_BLOCKED_RISK: { color: '#f59e0b', label: 'Блок' },
  ENTRY_SKIPPED_PAUSED: { color: '#f59e0b', label: 'Пауза' },
  ENTRY_SKIPPED_SIZE: { color: '#f59e0b', label: 'Розмір 0' },
};

const STEP = 4; // px per bar: 3px segment + 1px gap

export const RegimeTimeline: React.FC<{ logs: TradeDecisionRow[] }> = ({ logs }) => {
  const bars = logs.filter((row) => row.kind !== 'intrabar');
  if (bars.length === 0) return null;

  const width = bars.length * STEP;
  const stripY = 10;
  const stripH = 14;

  return (
    <div className="border border-gray-800 rounded-lg px-3 py-2 bg-gray-950/40">
      <div className="text-[10px] text-gray-500 mb-1">
        Режими та ключові події ({bars.length} барів)
      </div>
      <div className="overflow-x-auto">
        <svg width={width} height={stripY + stripH} viewBox={`0 0 ${width} ${stripY + stripH}`}>
          {bars.map((row, index) => (
            <rect
              key={index}
              x={index * STEP}
              y={stripY}
              width={STEP - 1}
              height={stripH}
              fill={REGIME_COLORS[row.regime ?? ''] ?? REGIME_COLORS.UNKNOWN}
            >
              <title>{`${row.ts} · ${row.regime ?? '—'} · ${row.outcome ?? ''}`}</title>
            </rect>
          ))}
          {bars.map((row, index) => {
            if (!row.outcome) return null;
            const marker = MARKERS[row.outcome];
            if (!marker) return null;
            return (
              <circle
                key={`m${index}`}
                cx={index * STEP + (STEP - 1) / 2}
                cy={4}
                r={2.5}
                fill={marker.color}
              >
                <title>{`${row.ts} · ${marker.label} (${row.outcome})`}</title>
              </circle>
            );
          })}
        </svg>
      </div>
      <div className="flex flex-wrap gap-3 text-[9px] text-gray-500 mt-1">
        <span>
          <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: '#10b981' }} />
          uptrend
        </span>
        <span>
          <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: '#ef4444' }} />
          downtrend
        </span>
        <span>
          <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: '#64748b' }} />
          range
        </span>
        <span>
          <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: '#1f2937' }} />
          warmup / —
        </span>
      </div>
    </div>
  );
};
