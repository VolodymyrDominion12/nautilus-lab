import React, { useState } from 'react';
import {
  Award,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  FlaskConical,
  Trophy,
} from 'lucide-react';
import type { LeaderboardEntry } from '../../services/api';
import { formatPct, toNumber, toneOf, TONE_TEXT } from '../../lib/format';
import { LeaderboardRowDetails } from './LeaderboardRowDetails';

interface LeaderboardTableProps {
  entries: LeaderboardEntry[];
  onRunInLab: (entry: LeaderboardEntry) => void;
}

export const LeaderboardTable: React.FC<LeaderboardTableProps> = ({
  entries,
  onRunInLab,
}) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  const handleCopyCmd = (e: React.MouseEvent, entry: LeaderboardEntry) => {
    e.stopPropagation();
    navigator.clipboard.writeText(entry.reproduce_command);
    setCopiedId(entry.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const renderRankBadge = (index: number) => {
    if (index === 0) {
      return (
        <span className="inline-flex items-center gap-1 font-bold text-amber-300">
          <Trophy className="w-4 h-4 text-amber-400 fill-amber-400/20" />
          <span>#1</span>
        </span>
      );
    }
    if (index === 1) {
      return (
        <span className="inline-flex items-center gap-1 font-bold text-slate-300">
          <Award className="w-4 h-4 text-slate-300 fill-slate-300/20" />
          <span>#2</span>
        </span>
      );
    }
    if (index === 2) {
      return (
        <span className="inline-flex items-center gap-1 font-bold text-amber-600">
          <Award className="w-4 h-4 text-amber-600 fill-amber-600/20" />
          <span>#3</span>
        </span>
      );
    }
    return <span className="font-mono text-gray-500">#{index + 1}</span>;
  };

  return (
    <div className="overflow-x-auto border border-gray-800 rounded-2xl bg-gray-900/50">
      <table className="w-full text-left text-xs font-mono">
        <thead className="bg-[#0b101b] text-gray-400 uppercase text-[10px] tracking-wider border-b border-gray-800">
          <tr>
            <th className="py-3.5 px-4 w-14 text-center">Ранг</th>
            <th className="py-3.5 px-4">Стратегія / Ринок</th>
            <th className="py-3.5 px-4 text-right">OOS Return</th>
            <th className="py-3.5 px-4 text-right">Buy &amp; Hold</th>
            <th className="py-3.5 px-4 text-right">Excess (Альфа)</th>
            <th className="py-3.5 px-4 text-center">Фолди</th>
            <th className="py-3.5 px-4 text-right">Fills</th>
            <th className="py-3.5 px-4 text-center">Дії</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/60">
          {entries.map((entry, idx) => {
            const isExpanded = expandedId === entry.id;
            const oosVal = toNumber(entry.oos_return);
            const bhVal = toNumber(entry.buy_and_hold_return);
            const excessVal = toNumber(entry.excess_return);
            const isCopied = copiedId === entry.id;

            return (
              <React.Fragment key={entry.id}>
                <tr
                  onClick={() => toggleExpand(entry.id)}
                  className={`hover:bg-gray-800/40 transition-colors cursor-pointer ${
                    isExpanded ? 'bg-gray-800/30' : ''
                  }`}
                >
                  <td className="py-3.5 px-4 text-center">{renderRankBadge(idx)}</td>
                  <td className="py-3.5 px-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-gray-100 font-sans text-sm">
                        {entry.robot}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-blue-950/60 border border-blue-800/50 text-[10px] text-blue-300">
                        {entry.instrument_id}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-gray-800 border border-gray-700 text-[10px] text-gray-300">
                        {entry.timeframe}
                      </span>
                    </div>
                  </td>
                  <td className="py-3.5 px-4 text-right font-bold text-gray-200">
                    <span className={TONE_TEXT[toneOf(oosVal)]}>{formatPct(oosVal)}</span>
                  </td>
                  <td className="py-3.5 px-4 text-right text-gray-400">
                    {formatPct(bhVal)}
                  </td>
                  <td className="py-3.5 px-4 text-right">
                    <span
                      className={`font-bold px-2 py-0.5 rounded ${
                        excessVal != null && excessVal > 0
                          ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/50'
                          : 'text-gray-400'
                      }`}
                    >
                      {formatPct(excessVal)}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-center">
                    <span className="px-2 py-0.5 rounded bg-gray-800 text-gray-300 text-[11px]">
                      {entry.profitable_folds ?? `${entry.folds} f`}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-right text-gray-300 font-mono">
                    {entry.fills != null ? entry.fills.toLocaleString() : '—'}
                  </td>
                  <td className="py-3.5 px-4">
                    <div className="flex items-center justify-center gap-1.5">
                      <button
                        type="button"
                        onClick={(e) => handleCopyCmd(e, entry)}
                        className="p-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white transition-colors"
                        title="Скопіювати команду відтворення"
                      >
                        {isCopied ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRunInLab(entry);
                        }}
                        className="flex items-center gap-1 px-2 py-1 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 text-[11px] font-sans transition-colors"
                        title="Відкрити в Research Lab"
                      >
                        <FlaskConical className="w-3 h-3" />
                        <span>В Lab</span>
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpand(entry.id);
                        }}
                        className="p-1 text-gray-400 hover:text-gray-200"
                        title="Деталі"
                      >
                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
                {isExpanded && (
                  <tr>
                    <td colSpan={8} className="p-0">
                      <LeaderboardRowDetails entry={entry} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
