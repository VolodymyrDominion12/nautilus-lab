import React, { useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { fetchRunTrades, type BatchTradeSummary } from '../../services/api';
import { TONE_TEXT, formatDateTime, formatPct, toneOf } from '../../lib/format';
import { formatDuration } from '../../lib/batch';
import { buildTradeHash, exitColor, outcomeLabel } from '../../lib/trades';

interface RunTradesTabProps {
  batchId: string;
  cellId: string;
  fold?: number;
  instrumentId: string;
  interval: string;
  catalog: string;
  title: string;
}

/**
 * Every trade of the run's OOS folds, each linking to the trade page (chart, SL/TP,
 * indicators, the decision chain). The link carries the **fold's** session key, which the
 * trade endpoints resolve into the batch cell's decision files.
 */
export const RunTradesTab: React.FC<RunTradesTabProps> = ({
  batchId,
  cellId,
  fold,
  instrumentId,
  interval,
  catalog,
  title,
}) => {
  const [trades, setTrades] = useState<BatchTradeSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setTrades(null);
    fetchRunTrades(batchId, cellId, fold)
      .then((data) => alive && setTrades(data.trades))
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : String(err)));
    return () => {
      alive = false;
    };
  }, [batchId, cellId, fold]);

  if (error) return <div className="text-xs text-red-400">{error}</div>;
  if (trades == null) return <div className="text-xs text-gray-500">Завантаження угод…</div>;
  if (trades.length === 0) {
    return (
      <div className="text-xs text-gray-500">
        Угод немає. Причину видно у вкладках «Рішення» та «Аналіз причин».
      </div>
    );
  }

  return (
    <div className="overflow-x-auto max-h-[36rem]">
      <table className="w-full text-xs">
        <thead className="text-gray-500 text-[10px] uppercase sticky top-0 bg-gray-950">
          <tr>
            <th className="text-left py-1.5 pr-3">Фолд</th>
            <th className="text-left pr-3">Вхід</th>
            <th className="text-left pr-3">Напрям</th>
            <th className="text-left pr-3">Результат</th>
            <th className="text-left pr-3">R</th>
            <th className="text-left pr-3">Вихід</th>
            <th className="text-left pr-3">MFE / MAE</th>
            <th className="text-left pr-3">Комісія</th>
            <th className="text-left pr-3">Прослизання</th>
            <th className="text-left pr-3">Тривалість</th>
            <th className="text-left">Режим</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={`${trade.fold_session}-${trade.id}`} className="border-t border-gray-800 hover:bg-gray-800/30">
              <td className="py-1.5 pr-3 font-mono text-gray-400">{trade.fold}</td>
              <td className="pr-3">
                <a
                  href={buildTradeHash({
                    session: trade.fold_session,
                    id: trade.id,
                    instrument: instrumentId,
                    interval,
                    catalog,
                    title,
                    origin: 'backtest',
                  })}
                  className="flex items-center gap-1 text-blue-400 hover:text-blue-300 font-mono"
                >
                  {formatDateTime(trade.entry_time)} <ExternalLink className="w-3 h-3" />
                </a>
              </td>
              <td className={`pr-3 font-mono ${trade.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>
                {trade.side}
              </td>
              <td className={`pr-3 font-mono ${TONE_TEXT[toneOf(trade.realized_pnl)]}`}>
                <div className="flex items-center gap-1">
                  <span>{formatPct((trade.realized_pnl_pct ?? 0) / 100)}</span>
                  {trade.pnl_source && (
                    <span
                      className={`text-[9px] px-1 py-0.5 rounded border ${
                        trade.pnl_source === 'fills'
                          ? 'border-emerald-700/50 text-emerald-400 bg-emerald-950/40'
                          : 'border-gray-700 text-gray-400 bg-gray-900/60'
                      }`}
                      title={trade.pnl_source === 'fills' ? 'PnL з фактичних fills' : 'PnL з різниці цін'}
                    >
                      {trade.pnl_source === 'fills' ? 'fills' : 'delta'}
                    </span>
                  )}
                </div>
              </td>
              <td className="pr-3 font-mono text-gray-300">
                {trade.r_multiple == null ? '—' : trade.r_multiple.toFixed(2)}
              </td>
              <td className="pr-3 font-mono">
                <div style={{ color: exitColor(trade.exit_outcome) }}>
                  {trade.status === 'OPEN' ? 'відкрита' : outcomeLabel(trade.exit_outcome)}
                </div>
                {trade.exit_reason && (
                  <div className="text-[10px] text-gray-500 truncate max-w-[8rem]" title={trade.exit_reason}>
                    {trade.exit_reason}
                  </div>
                )}
              </td>
              <td className="pr-3 font-mono text-gray-300">
                {trade.mfe_close_pct != null || trade.mae_close_pct != null ? (
                  <div className="text-[11px]">
                    <span className="text-emerald-400">
                      {trade.mfe_close_pct != null ? `+${trade.mfe_close_pct.toFixed(2)}%` : '—'}
                    </span>
                    <span className="text-gray-600 mx-1">/</span>
                    <span className="text-red-400">
                      {trade.mae_close_pct != null ? `${trade.mae_close_pct.toFixed(2)}%` : '—'}
                    </span>
                  </div>
                ) : (
                  '—'
                )}
              </td>
              <td className="pr-3 font-mono text-gray-400">
                {trade.fee != null ? (
                  <span title={trade.fee_known ? 'Фактична комісія' : 'Оцінена комісія'}>
                    ${trade.fee.toFixed(2)}
                    {!trade.fee_known && <span className="text-gray-500 text-[9px] ml-0.5">~</span>}
                  </span>
                ) : (
                  '—'
                )}
              </td>
              <td className="pr-3 font-mono text-gray-400">
                {trade.entry_slippage_bps == null ? '—' : `${trade.entry_slippage_bps.toFixed(1)} bps`}
              </td>
              <td className="pr-3 font-mono text-gray-400">
                <div>{trade.duration_bars != null ? `${trade.duration_bars} б` : '—'}</div>
                {trade.duration_seconds != null && trade.duration_seconds > 0 && (
                  <div className="text-[10px] text-gray-500">
                    {formatDuration(trade.duration_seconds)}
                  </div>
                )}
              </td>
              <td className="font-mono text-gray-400">{trade.regime_at_entry || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
