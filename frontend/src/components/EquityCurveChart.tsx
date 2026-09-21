import React, { useMemo, useState } from 'react';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Calendar,
  Percent,
  TrendingDown,
} from 'lucide-react';
import { formatPct, toNumber } from '../lib/format';
import type { FoldSummary } from '../services/api';

interface EquityCurveChartProps {
  folds: FoldSummary[];
  startingEquity?: number | null;
  title?: string;
}

interface EquityPoint {
  foldIndex: number;
  label: string;
  startDate: string;
  endDate: string;
  foldOosReturn: number;
  foldBhReturn: number;
  cumulativeOosReturn: number;
  cumulativeBhReturn: number;
  equityValue: number;
  bhEquityValue: number;
  drawdownPct: number;
  maxFoldDrawdown: number;
  fills: number;
}

export const EquityCurveChart: React.FC<EquityCurveChartProps> = ({
  folds,
  startingEquity = 10000,
  title = 'Out-of-Sample Cumulative Trajectory',
}) => {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const points = useMemo<EquityPoint[]>(() => {
    if (!folds || folds.length === 0) return [];

    const baseEquity = startingEquity && startingEquity > 0 ? startingEquity : 10000;
    let currentEquity = baseEquity;
    let currentBhEquity = baseEquity;
    let peakEquity = baseEquity;

    const list: EquityPoint[] = [];

    // Initial starting point (Fold 0 baseline)
    const firstStart = folds[0]?.window?.out_of_sample_start || '';
    list.push({
      foldIndex: 0,
      label: 'Start',
      startDate: firstStart,
      endDate: firstStart,
      foldOosReturn: 0,
      foldBhReturn: 0,
      cumulativeOosReturn: 0,
      cumulativeBhReturn: 0,
      equityValue: baseEquity,
      bhEquityValue: baseEquity,
      drawdownPct: 0,
      maxFoldDrawdown: 0,
      fills: 0,
    });

    folds.forEach((fold, idx) => {
      const oosRet = toNumber(fold.oos_return_raw) ?? 0;
      const bhRet = toNumber(fold.buy_and_hold_return_raw) ?? 0;

      currentEquity = currentEquity * (1 + oosRet);
      currentBhEquity = currentBhEquity * (1 + bhRet);

      if (currentEquity > peakEquity) {
        peakEquity = currentEquity;
      }
      const dd = peakEquity > 0 ? (currentEquity - peakEquity) / peakEquity : 0;
      const foldMetricsDd = fold.oos_metrics?.max_drawdown ?? 0;

      list.push({
        foldIndex: idx + 1,
        label: `Fold ${idx + 1}`,
        startDate: fold.window?.out_of_sample_start || '',
        endDate: fold.window?.out_of_sample_end || '',
        foldOosReturn: oosRet,
        foldBhReturn: bhRet,
        cumulativeOosReturn: (currentEquity - baseEquity) / baseEquity,
        cumulativeBhReturn: (currentBhEquity - baseEquity) / baseEquity,
        equityValue: currentEquity,
        bhEquityValue: currentBhEquity,
        drawdownPct: dd,
        maxFoldDrawdown: Math.max(Math.abs(dd), foldMetricsDd),
        fills: fold.fills ?? 0,
      });
    });

    return list;
  }, [folds, startingEquity]);

  if (points.length < 2) return null;

  const totalOos = points[points.length - 1]?.cumulativeOosReturn ?? 0;
  const totalBh = points[points.length - 1]?.cumulativeBhReturn ?? 0;
  const maxDd = Math.max(...points.map((p) => Math.abs(p.drawdownPct)), 0);
  const profitableFolds = folds.filter((f) => (toNumber(f.oos_return_raw) ?? 0) > 0).length;
  const winRate = folds.length > 0 ? (profitableFolds / folds.length) * 100 : 0;

  // Chart dimensions
  const width = 640;
  const height = 210;
  const ddHeight = 65;
  const padding = { top: 16, right: 24, bottom: 20, left: 52 };

  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  // Value bounds for Equity curve
  const allEquities = points.flatMap((p) => [p.equityValue, p.bhEquityValue]);
  const minEq = Math.min(...allEquities);
  const maxEq = Math.max(...allEquities);
  const eqRange = maxEq - minEq || 1;
  const eqMinWithPad = minEq - eqRange * 0.05;
  const eqMaxWithPad = maxEq + eqRange * 0.05;
  const eqSpan = eqMaxWithPad - eqMinWithPad || 1;

  const getX = (idx: number) => padding.left + (idx / (points.length - 1)) * chartW;
  const getY = (val: number) => padding.top + chartH - ((val - eqMinWithPad) / eqSpan) * chartH;

  // Drawdown Y (0 at top of DD pane, maxDd at bottom)
  const ddSpan = Math.max(maxDd, 0.05);
  const getDdY = (dd: number) => (Math.abs(dd) / ddSpan) * (ddHeight - 16);

  // Build SVG Paths
  const oosPath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(p.equityValue).toFixed(1)}`)
    .join(' ');

  const oosAreaPath = `${oosPath} L ${getX(points.length - 1).toFixed(1)} ${getY(eqMinWithPad).toFixed(1)} L ${getX(0).toFixed(1)} ${getY(eqMinWithPad).toFixed(1)} Z`;

  const bhPath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(p.bhEquityValue).toFixed(1)}`)
    .join(' ');

  const ddPath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getDdY(p.drawdownPct).toFixed(1)}`)
    .join(' ');

  const ddAreaPath = `${ddPath} L ${getX(points.length - 1).toFixed(1)} 0 L ${getX(0).toFixed(1)} 0 Z`;

  const activePoint = hoverIndex !== null && hoverIndex >= 0 ? points[hoverIndex] : null;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-emerald-400" />
          <h3 className="text-sm font-bold text-gray-100">{title}</h3>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-gray-950 text-gray-400 border border-gray-800">
            {folds.length} OOS folds chained
          </span>
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <span className="flex items-center gap-1.5 text-emerald-400">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block" />
            Robot (OOS)
          </span>
          <span className="flex items-center gap-1.5 text-gray-400">
            <span className="w-2.5 h-0.5 bg-gray-400 inline-block border-t border-dashed" />
            Buy &amp; Hold
          </span>
        </div>
      </div>

      {/* Quick Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wider">Total OOS Return</div>
          <div
            className={`text-base font-bold font-mono mt-0.5 flex items-center gap-1 ${
              totalOos >= 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {totalOos >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
            {formatPct(totalOos)}
          </div>
        </div>

        <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wider">Buy &amp; Hold Baseline</div>
          <div
            className={`text-base font-bold font-mono mt-0.5 flex items-center gap-1 ${
              totalBh >= 0 ? 'text-gray-300' : 'text-red-400/80'
            }`}
          >
            {formatPct(totalBh)}
          </div>
        </div>

        <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wider">Max Drawdown</div>
          <div className="text-base font-bold font-mono mt-0.5 text-amber-400 flex items-center gap-1">
            <TrendingDown className="w-4 h-4 text-amber-400" />
            {formatPct(-maxDd)}
          </div>
        </div>

        <div className="bg-gray-950/80 border border-gray-800/80 rounded-xl p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wider">Folds Win Rate</div>
          <div className="text-base font-bold font-mono mt-0.5 text-blue-400 flex items-center gap-1">
            <Percent className="w-4 h-4 text-blue-400" />
            {winRate.toFixed(0)}%
            <span className="text-[10px] text-gray-500 font-normal">
              ({profitableFolds}/{folds.length})
            </span>
          </div>
        </div>
      </div>

      {/* Main SVG Chart Container */}
      <div className="relative bg-gray-950 border border-gray-800/80 rounded-xl p-2 select-none overflow-hidden">
        {/* Equity Curve SVG */}
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-auto overflow-visible"
          onMouseLeave={() => setHoverIndex(null)}
        >
          <defs>
            <linearGradient id="oosGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="ddGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ef4444" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#ef4444" stopOpacity="0.05" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const y = padding.top + chartH * ratio;
            const val = eqMaxWithPad - ratio * eqSpan;
            return (
              <g key={ratio}>
                <line
                  x1={padding.left}
                  y1={y}
                  x2={width - padding.right}
                  y2={y}
                  stroke="#1f2937"
                  strokeWidth="1"
                  strokeDasharray="2,3"
                />
                <text
                  x={padding.left - 6}
                  y={y + 3}
                  textAnchor="end"
                  className="fill-gray-600 text-[9px] font-mono"
                >
                  ${Math.round(val).toLocaleString()}
                </text>
              </g>
            );
          })}

          {/* Baseline Line & Fill */}
          <path d={oosAreaPath} fill="url(#oosGradient)" />
          <path
            d={bhPath}
            fill="none"
            stroke="#6b7280"
            strokeWidth="1.5"
            strokeDasharray="4,4"
            className="opacity-75"
          />
          <path
            d={oosPath}
            fill="none"
            stroke={totalOos >= 0 ? '#10b981' : '#ef4444'}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Hover highlight line */}
          {hoverIndex !== null && (
            <line
              x1={getX(hoverIndex)}
              y1={padding.top}
              x2={getX(hoverIndex)}
              y2={height - padding.bottom}
              stroke="#60a5fa"
              strokeWidth="1.5"
              strokeDasharray="3,3"
            />
          )}

          {/* Data Points */}
          {points.map((p, i) => {
            const x = getX(i);
            const y = getY(p.equityValue);
            const isHovered = hoverIndex === i;
            return (
              <g
                key={p.foldIndex}
                onMouseEnter={() => setHoverIndex(i)}
                className="cursor-pointer"
              >
                <circle
                  cx={x}
                  cy={y}
                  r={isHovered ? 5.5 : 3.5}
                  className={`transition-all ${
                    p.foldIndex === 0
                      ? 'fill-gray-400 stroke-gray-800 stroke-2'
                      : p.foldOosReturn >= 0
                        ? 'fill-emerald-400 stroke-emerald-950 stroke-2'
                        : 'fill-red-400 stroke-red-950 stroke-2'
                  }`}
                />
                {/* Fold label on X axis */}
                <text
                  x={x}
                  y={height - 4}
                  textAnchor="middle"
                  className={`text-[9px] font-mono transition-colors ${
                    isHovered ? 'fill-blue-400 font-bold' : 'fill-gray-500'
                  }`}
                >
                  {p.label}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Underwater Drawdown Section */}
        <div className="mt-2 pt-2 border-t border-gray-800/80">
          <div className="flex items-center justify-between text-[10px] text-gray-500 font-mono px-2 mb-1">
            <span>Underwater Drawdown (%)</span>
            <span>Max: {formatPct(-maxDd)}</span>
          </div>

          <svg viewBox={`0 0 ${width} ${ddHeight}`} className="w-full h-auto overflow-visible">
            <path d={ddAreaPath} fill="url(#ddGradient)" />
            <path
              d={ddPath}
              fill="none"
              stroke="#f87171"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
            {/* Zero line */}
            <line
              x1={padding.left}
              y1={0}
              x2={width - padding.right}
              y2={0}
              stroke="#374151"
              strokeWidth="1"
            />
            {hoverIndex !== null && (
              <circle
                cx={getX(hoverIndex)}
                cy={getDdY(points[hoverIndex].drawdownPct)}
                r={3.5}
                className="fill-red-400 stroke-gray-950 stroke-2"
              />
            )}
          </svg>
        </div>

        {/* Floating Tooltip when hovered */}
        {activePoint && hoverIndex !== null && (
          <div
            className="absolute z-20 top-3 bg-gray-900/95 border border-blue-500/30 backdrop-blur-md rounded-xl p-3 text-xs shadow-xl pointer-events-none transition-all"
            style={{
              left: Math.min(Math.max(getX(hoverIndex) - 90, 10), width - 210),
            }}
          >
            <div className="font-bold text-gray-200 border-b border-gray-800 pb-1.5 mb-1.5 flex items-center justify-between gap-3">
              <span>{activePoint.label}</span>
              <span className="text-[10px] font-mono text-gray-400">
                ${Math.round(activePoint.equityValue).toLocaleString()}
              </span>
            </div>

            {activePoint.startDate && (
              <div className="text-[10px] text-gray-400 font-mono flex items-center gap-1 mb-1">
                <Calendar className="w-3 h-3 text-gray-500" />
                {activePoint.startDate.slice(0, 10)} → {activePoint.endDate.slice(0, 10)}
              </div>
            )}

            <div className="flex flex-col gap-1 text-[11px] font-mono mt-1">
              {activePoint.foldIndex > 0 && (
                <div className="flex justify-between gap-4">
                  <span className="text-gray-400">Fold OOS Return:</span>
                  <span
                    className={
                      activePoint.foldOosReturn >= 0 ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'
                    }
                  >
                    {formatPct(activePoint.foldOosReturn)}
                  </span>
                </div>
              )}
              <div className="flex justify-between gap-4">
                <span className="text-gray-400">Cumulative Return:</span>
                <span
                  className={
                    activePoint.cumulativeOosReturn >= 0 ? 'text-emerald-400' : 'text-red-400'
                  }
                >
                  {formatPct(activePoint.cumulativeOosReturn)}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-400">Buy &amp; Hold Cumul:</span>
                <span className="text-gray-300">
                  {formatPct(activePoint.cumulativeBhReturn)}
                </span>
              </div>
              <div className="flex justify-between gap-4">
                <span className="text-gray-400">Peak Drawdown:</span>
                <span className="text-amber-400">
                  {formatPct(activePoint.drawdownPct)}
                </span>
              </div>
              {activePoint.fills > 0 && (
                <div className="flex justify-between gap-4 text-gray-500 text-[10px]">
                  <span>Fills in fold:</span>
                  <span>{activePoint.fills}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
