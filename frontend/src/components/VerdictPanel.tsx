import React from 'react';
import { AlertTriangle, CheckCircle2, HelpCircle, Info, ShieldQuestion } from 'lucide-react';
import { MetricCard } from './MetricCard';
import { TONE_TEXT, formatBps, formatDateTime, formatPct, toNumber } from '../lib/format';
import type { Tone } from '../lib/format';
import type { ResearchSummary } from '../services/api';
import { verdictFor } from '../lib/research';

interface VerdictPanelProps {
  summary: ResearchSummary | null;
}

const TONE_ICON = {
  positive: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
  negative: <AlertTriangle className="w-4 h-4 text-red-400" />,
  neutral: <ShieldQuestion className="w-4 h-4 text-gray-400" />,
};

/**
 * The honest reading of a finished run.
 *
 * Answers the questions the raw cards cannot: was this measured out of sample, did it beat
 * buy&hold, how many folds actually made money, and does the result survive its own
 * trading costs. Anything unmeasured is shown as "n/a" rather than as zero.
 */
export const VerdictPanel: React.FC<VerdictPanelProps> = ({ summary }) => {
  const verdict = verdictFor(summary);
  if (!summary || !summary.is_finished || summary.is_error) return null;

  const multi = summary.multi_window;
  const walk = summary.walk_forward;
  const single = summary.single_backtest;
  const headlineTone: Tone =
    verdict.beatsBuyHold === true ? 'positive' : verdict.beatsBuyHold === false ? 'negative' : 'neutral';

  const breakeven = multi?.mean_breakeven_cost ?? single?.breakeven_cost ?? null;
  const paid = multi?.mean_paid_cost_rate ?? single?.paid_cost_rate ?? null;
  const headroom = multi?.cost_headroom ?? single?.cost_headroom ?? null;

  const foldCount = multi?.fold_count ?? (multi?.folds?.length || null);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Info className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-bold text-gray-100">Verdict</h3>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${verdict.badge.className}`}>
            {verdict.badge.label}
          </span>
          {summary.robot && (
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-gray-950 text-gray-400 border-gray-800">
              {summary.robot}
            </span>
          )}
          {summary.finished_at && (
            <span className="text-[11px] font-mono text-gray-500">
              {formatDateTime(summary.finished_at)}
            </span>
          )}
        </div>
      </div>

      <div className={`flex items-start gap-2 text-sm font-medium ${TONE_TEXT[headlineTone]}`}>
        {TONE_ICON[headlineTone]}
        <span>{verdict.headline}</span>
      </div>

      <p className="text-[11px] text-gray-500 leading-snug">{verdict.badge.detail}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {multi && (
          <>
            <MetricCard
              label="OOS mean return"
              value={multi.mean_oos}
              tone={toNumber(multi.mean_oos_raw) != null && (toNumber(multi.mean_oos_raw) as number) > 0 ? 'positive' : 'negative'}
              hint={`Spread across folds: ${multi.spread}`}
              tag={foldCount ? `${foldCount} folds` : undefined}
            />
            <MetricCard
              label="Buy & hold baseline"
              value={multi.buy_and_hold_mean}
              hint={
                multi.beats_buy_and_hold === true
                  ? `Excess ${multi.mean_excess_return}`
                  : multi.beats_buy_and_hold === false
                    ? `Excess ${multi.mean_excess_return} — behind the baseline`
                    : 'Baseline not measurable for this run'
              }
            />
            <MetricCard
              label="Profitable folds"
              value={multi.profitable}
              hint={`Worst ${multi.worst_oos} · best ${multi.best_oos} · median ${multi.median_oos}`}
              tone={multi.profitable.startsWith(multi.fold_count.toString()) ? 'positive' : 'neutral'}
            />
            <MetricCard
              label="OOS fills"
              value={multi.total_oos_fills}
              tone={multi.total_oos_fills === 0 ? 'negative' : 'neutral'}
              hint={
                multi.total_oos_fills === 0
                  ? 'No trades executed — no sample to score'
                  : 'Executed out-of-sample trades'
              }
            />
          </>
        )}

        {!multi && walk && (
          <>
            <MetricCard
              label="Out-of-sample return"
              value={walk.out_of_sample_return ?? 'n/a'}
              hint={`Window ${walk.window.out_of_sample_start.slice(0, 10)} → ${walk.window.out_of_sample_end.slice(0, 10)}`}
              tag="report this"
              tagClassName="bg-emerald-950/60 text-emerald-400 border-emerald-800/50"
            />
            <MetricCard
              label="In-sample return"
              value={walk.in_sample_return ?? 'n/a'}
              hint="Selection window only — not a result"
              tag="selection only"
              tagClassName="bg-amber-950/60 text-amber-400 border-amber-800/50"
            />
            <MetricCard
              label="Configurations tried"
              value={walk.candidates_tried}
              hint={`Selected: ${walk.selected}`}
            />
            <MetricCard
              label="Buy & hold baseline"
              value="n/a"
              hint="Not measured for a single anchored split"
            />
          </>
        )}

        {!multi && !walk && single && (
          <>
            <MetricCard
              label="Ending balance"
              value={single.ending_balance != null ? `$${single.ending_balance.toLocaleString()}` : 'n/a'}
              hint={`${single.fills} fills / ${single.positions} positions`}
              tag="in-sample"
              tagClassName="bg-amber-950/60 text-amber-400 border-amber-800/50"
            />
            <MetricCard
              label="Max drawdown"
              value={single.max_dd_pct}
              tone="neutral"
              hint="Peak-to-trough, in-sample"
            />
            <MetricCard
              label="Sharpe-like"
              value={single.sharpe != null ? single.sharpe.toFixed(3) : 'n/a'}
              hint="Undeflated: no correction for how many configurations were tried"
            />
            <MetricCard
              label="Buy & hold baseline"
              value="n/a"
              hint="Not measured for a full-sample run"
            />
          </>
        )}
      </div>

      {(breakeven != null || paid != null) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
          <MetricCard
            label="Breakeven cost"
            value={formatBps(breakeven)}
            hint={
              breakeven != null && breakeven < 0
                ? 'Negative: even free execution leaves this run at a loss'
                : 'Highest constant cost per traded notional that still leaves PnL at zero'
            }
          />
          <MetricCard
            label="Cost actually paid"
            value={formatBps(paid)}
            hint="Fees divided by two-sided traded notional"
          />
          <MetricCard
            label="Cost headroom"
            value={formatBps(headroom)}
            tone={(headroom ?? 0) > 0 ? 'positive' : 'negative'}
            hint={
              breakeven != null && breakeven < 0
                ? 'Breakeven is negative: this loses money even at zero cost'
                : (headroom ?? 0) > 0
                  ? 'Survives more expensive execution than it got'
                  : 'Needs cheaper execution than it got'
            }
          />
        </div>
      )}

      {verdict.concerns.length > 0 && (
        <div className="border-t border-gray-800/80 pt-3 flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold text-amber-400 uppercase tracking-wider">
            Read with caution
          </span>
          {verdict.concerns.map((concern) => (
            <div key={concern} className="flex items-start gap-2 text-[11px] text-gray-400">
              <AlertTriangle className="w-3.5 h-3.5 text-amber-500/80 mt-0.5 shrink-0" />
              <span>{concern}</span>
            </div>
          ))}
        </div>
      )}

      {summary.raw_summary && (
        <div className="text-[10px] font-mono text-gray-500 border-t border-gray-800/80 pt-3 break-all">
          {summary.raw_summary}
        </div>
      )}

      {multi && (multi.breakeven_costs?.length ?? 0) > 0 && (
        <div className="text-[11px] text-gray-500 flex items-center gap-2 flex-wrap">
          <HelpCircle className="w-3.5 h-3.5" />
          <span>Per-fold breakeven:</span>
          <span className="font-mono text-gray-400">
            {multi.breakeven_costs
              .map((value) => (value == null ? 'n/a' : formatBps(value)))
              .join(' · ')}
          </span>
        </div>
      )}

      {summary.single_backtest && summary.walk_forward && (
        <div className="text-[10px] font-mono text-gray-600">
          OOS return {formatPct(toNumber(summary.walk_forward.out_of_sample_return_raw))}
          {' · '}IS return {formatPct(toNumber(summary.walk_forward.in_sample_return_raw))}
        </div>
      )}
    </div>
  );
};
