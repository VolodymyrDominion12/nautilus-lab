import React, { useState } from 'react';
import {
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Flame,
  Lightbulb,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  Zap,
} from 'lucide-react';

import type { HypothesisItem } from '../../services/api';

export type TestInResearch = (config: { robot: string; formula?: string; notes?: string }) => void;

interface HypothesisCardProps {
  item: HypothesisItem;
  idx: number;
  onTestInResearch?: TestInResearch;
}

/** One drafted hypothesis: direction, horizon, formula, mechanism and kill condition. */
export const HypothesisCard: React.FC<HypothesisCardProps> = ({ item, idx, onTestInResearch }) => {
  const [isCopied, setIsCopied] = useState(false);
  const isLong = item.expected_sign === 1;
  const hasUnknown = Boolean(item.unknown_identifiers && item.unknown_identifiers.length > 0);
  const copyFormula = () => {
    navigator.clipboard.writeText(item.formula).then(() => {
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 1500);
    });
  };

  return (
    <div
      key={item.name || idx}
      className="bg-gray-950 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3.5 hover:border-gray-700 transition-colors"
    >
      {/* Top info */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="w-6 h-6 rounded-lg bg-gray-900 border border-gray-800 flex items-center justify-center font-mono text-xs text-gray-400">
            {idx + 1}
          </span>
          <span className="font-semibold text-gray-100 font-mono text-sm">
            {item.name}
          </span>
          <span
            className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${
              isLong
                ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/60'
                : 'bg-rose-950/80 text-rose-400 border border-rose-800/60'
            }`}
          >
            {isLong ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
            {isLong ? '+1 LONG' : '-1 SHORT'}
          </span>
          <span className="inline-flex items-center gap-1 text-xs text-gray-400 bg-gray-900 px-2 py-0.5 rounded-md border border-gray-800">
            <Clock className="w-3 h-3 text-gray-500" />
            {item.horizon_bars} bars
          </span>
        </div>

        {hasUnknown ? (
          <span className="text-xs text-amber-400 bg-amber-950/50 border border-amber-800/50 px-2 py-0.5 rounded-md flex items-center gap-1">
            <TriangleAlert className="w-3.5 h-3.5" />
            Unknown feature: {item.unknown_identifiers?.join(', ')}
          </span>
        ) : (
          <span className="text-xs text-emerald-400 bg-emerald-950/40 border border-emerald-800/40 px-2 py-0.5 rounded-md flex items-center gap-1">
            <CheckCircle2 className="w-3.5 h-3.5" />
            DSL Verified
          </span>
        )}
      </div>

      {/* Formula block */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span className="font-mono">Formula DSL</span>
          <div className="flex items-center gap-3">
            {onTestInResearch && (
              <button
                type="button"
                onClick={() =>
                  onTestInResearch({
                    robot: 'formulaic_lgbm',
                    formula: item.formula,
                    notes: `Hypothesis ${item.name}: ${item.formula}`,
                  })
                }
                className="flex items-center gap-1 text-purple-400 hover:text-purple-300 transition-colors font-medium"
                title="Open Research Lab and test this formula with formulaic_lgbm robot"
              >
                <Zap className="w-3 h-3 text-yellow-400" />
                <span>Test in Research</span>
              </button>
            )}
            <button
              type="button"
              onClick={copyFormula}
              className="flex items-center gap-1 text-amber-400 hover:text-amber-300 transition-colors"
            >
              {isCopied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
              {isCopied ? 'Copied!' : 'Copy formula'}
            </button>
          </div>
        </div>
        <div className="p-3 bg-gray-900 border border-gray-800/90 rounded-xl font-mono text-xs text-amber-200/90 break-all select-all">
          {item.formula}
        </div>
      </div>

      {/* Mechanism & Kill condition */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-1">
        <div className="p-3 bg-gray-900/60 border border-gray-800/60 rounded-xl flex flex-col gap-1.5">
          <span className="font-semibold text-gray-300 flex items-center gap-1.5">
            <Lightbulb className="w-3.5 h-3.5 text-amber-400" />
            Економічний механізм (Mechanism)
          </span>
          <p className="text-gray-400 leading-relaxed">
            {item.mechanism}
          </p>
        </div>

        <div className="p-3 bg-gray-900/60 border border-gray-800/60 rounded-xl flex flex-col gap-1.5">
          <span className="font-semibold text-rose-300 flex items-center gap-1.5">
            <Flame className="w-3.5 h-3.5 text-rose-400" />
            Умова спростування (Kill Condition)
          </span>
          <p className="text-gray-400 leading-relaxed">
            {item.kill_condition}
          </p>
        </div>
      </div>
    </div>
  );
};
