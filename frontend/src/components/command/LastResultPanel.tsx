import React from 'react';
import { Gauge } from 'lucide-react';

import { InfoTooltip } from '../InfoTooltip';
import { MetricCard } from '../MetricCard';
import { formatBps, formatDateTime, toNumber } from '../../lib/format';
import { verdictFor } from '../../lib/research';
import type { ResearchSummary } from '../../services/api';

/** What the last finished run measured, read through `verdictFor` instead of dumped as JSON. */
export const LastResultPanel: React.FC<{ last: ResearchSummary | null }> = ({ last }) => {
  const verdict = verdictFor(last);
  const multi = last?.multi_window ?? null;
  const single = last?.single_backtest ?? null;
  const meanOos = toNumber(multi?.mean_oos_raw);
  const excess = toNumber(multi?.mean_excess_return_raw);
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Gauge className="w-5 h-5 text-blue-400" />
        <h3 className="font-semibold text-gray-100">Last measured result</h3>
        <InfoTooltip term="verdict" size="xs" />
        {last?.robot && (
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full border bg-gray-950 text-gray-300 border-gray-800">
            {last.robot} · {last.run_type}
          </span>
        )}
        <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${verdict.badge.className}`}>
          {verdict.badge.label}
        </span>
        {last?.finished_at && (
          <span className="text-[11px] font-mono text-gray-500">
            {formatDateTime(last.finished_at)}
          </span>
        )}
      </div>

      {!last ? (
        <p className="text-sm text-gray-500">
          No research run recorded yet. Start one from the Research &amp; Backtest tab.
        </p>
      ) : (
        <>
          <p
            className={`text-sm font-medium ${
              verdict.beatsBuyHold === true
                ? 'text-emerald-400'
                : verdict.beatsBuyHold === false
                  ? 'text-red-400'
                  : 'text-gray-300'
            }`}
          >
            {verdict.headline}
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {multi ? (
              <>
                <MetricCard
                  label="OOS mean"
                  value={multi.mean_oos}
                  tone={meanOos != null && meanOos > 0 ? 'positive' : 'negative'}
                  hint={
                    excess == null
                      ? 'Baseline not measurable'
                      : `Excess over buy&hold ${multi.mean_excess_return}`
                  }
                />
                <MetricCard
                  label="Buy & hold"
                  value={multi.buy_and_hold_mean}
                  hint={`Mean of ${multi.fold_count} fold baselines`}
                />
                <MetricCard
                  label="Profitable folds"
                  value={multi.profitable}
                  hint={`Worst ${multi.worst_oos} · best ${multi.best_oos}`}
                />
                <MetricCard
                  label="Breakeven headroom"
                  value={formatBps(multi.cost_headroom)}
                  tone={(multi.cost_headroom ?? 0) > 0 ? 'positive' : 'negative'}
                  hint={`Paid ${formatBps(multi.mean_paid_cost_rate)} · breakeven ${formatBps(multi.mean_breakeven_cost)}`}
                />
              </>
            ) : (
              <>
                <MetricCard
                  label="Ending balance"
                  value={
                    single?.ending_balance != null
                      ? `$${single.ending_balance.toLocaleString()}`
                      : 'n/a'
                  }
                  hint={`${single?.fills ?? 0} fills / ${single?.positions ?? 0} positions`}
                />
                <MetricCard
                  label="Buy & hold"
                  value="n/a"
                  hint="Not measured for this run type"
                />
                <MetricCard label="Max drawdown" value={single?.max_dd_pct ?? 'n/a'} />
                <MetricCard
                  label="Sharpe-like"
                  value={single?.sharpe != null ? single.sharpe.toFixed(3) : 'n/a'}
                  hint="Undeflated"
                />
              </>
            )}
          </div>

          {verdict.concerns.length > 0 && (
            <div className="flex flex-col gap-1">
              {verdict.concerns.map((concern) => (
                <span key={concern} className="text-[11px] text-amber-400/90">
                  · {concern}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};
