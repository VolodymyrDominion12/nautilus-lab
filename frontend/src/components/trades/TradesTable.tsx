import React from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import type { TradeSummary } from '../../services/api';
import { TONE_TEXT, formatDateTime, formatPct, toneOf } from '../../lib/format';
import { buildTradeHash, describePnlBasis, formatDuration, outcomeLabel } from '../../lib/trades';
import type { TradeRoute } from '../../lib/trades';

interface TradesTableProps {
  trades: TradeSummary[];
  loading?: boolean;
  error?: string | null;
  /** Everything the trade page needs beyond the id; it rides in the link. */
  linkContext: Omit<TradeRoute, 'session' | 'id'> & { session: string };
  /** Older records exist beyond the scanned window (reported by the API, not inferred). */
  truncated?: boolean;
  recordsScanned?: number;
  /** Passes over the same window merged from one log; 1 for a live session. */
  windows?: number;
  onReload?: () => void;
  emptyHint?: string;
  /** Rows drawn before the rest is collapsed; the table scrolls regardless. */
  maxHeightClass?: string;
}

const money = (value: number | null | undefined, digits = 2): string =>
  value == null ? '—' : `$${value.toFixed(digits)}`;

/**
 * The trade list shared by the live paper terminal and the Backtest Details modal.
 *
 * Both read the same API (`GET /api/paper/sessions/{key}/trades`) because both reconstruct
 * from the same decision log, so one table serves them: same columns, same wording, same
 * link to a trade page. The row's number is never shown without its basis — see
 * `describePnlBasis` under the table.
 */
export const TradesTable: React.FC<TradesTableProps> = ({
  trades,
  loading,
  error,
  linkContext,
  truncated,
  recordsScanned,
  windows = 1,
  onReload,
  emptyHint,
  maxHeightClass = 'max-h-[32rem]',
}) => {
  const linkFor = (trade: TradeSummary) => buildTradeHash({ ...linkContext, id: trade.id });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-400">
        <span>
          Угод: <span className="font-mono text-gray-200">{trades.length}</span>
          {recordsScanned != null && (
            <span className="text-gray-600 font-mono"> · записів журналу: {recordsScanned}</span>
          )}
          {windows > 1 && (
            <span className="text-gray-600 font-mono"> · проходів: {windows}</span>
          )}
        </span>
        {onReload && (
          <button
            type="button"
            onClick={onReload}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg transition-colors border border-gray-700"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Оновити
          </button>
        )}
      </div>

      {windows > 1 && (
        <div className="p-3 rounded-lg bg-gray-900 border border-gray-700 text-[11px] text-gray-300">
          Журнал містить <span className="font-mono">{windows}</span> проходів по тому самому
          вікну (walk-forward пише кожен фолд під одним id сесії). Угоді зіставлено прохід, у
          якому її записано, — інакше вхід одного проходу змикався б із виходом іншого.
        </div>
      )}

      {truncated && (
        <div className="p-3 rounded-lg bg-amber-950/20 border border-amber-800/40 text-[11px] text-amber-200">
          Прочитано останні {recordsScanned ?? '?'} записів журналу рішень, старіші не
          скановано. У списку може не бути давніших угод — це межа вікна читання, а не
          твердження, що їх не було.
        </div>
      )}

      {error && (
        <div className="p-3 bg-red-950/30 border border-red-900/50 rounded-lg text-xs text-red-400">
          {error}
        </div>
      )}

      {trades.length === 0 && !loading && !error ? (
        <div className="py-8 text-center text-xs text-gray-500">
          {emptyHint ??
            'Угод немає. Якщо робот торгував, перевірте, що увімкнено DECISION_LOG_ENABLED=true.'}
        </div>
      ) : (
        <div className={`overflow-auto border border-gray-800 rounded-xl ${maxHeightClass}`}>
          <table className="w-full text-left text-[11px] font-mono">
            <thead className="bg-gray-950/80 text-gray-400 sticky top-0 z-10">
              <tr>
                <th className="p-2 font-medium">#</th>
                {windows > 1 && <th className="p-2 font-medium">Прохід</th>}
                <th className="p-2 font-medium">Вхід (UTC)</th>
                <th className="p-2 font-medium">Напрям</th>
                <th className="p-2 font-medium text-right">Ціна входу</th>
                <th className="p-2 font-medium text-right">Ціна виходу</th>
                <th className="p-2 font-medium text-right">Стоп</th>
                <th className="p-2 font-medium text-right">Тейк</th>
                <th className="p-2 font-medium">Тривалість</th>
                <th className="p-2 font-medium text-right">Результат</th>
                <th className="p-2 font-medium text-right">R</th>
                <th className="p-2 font-medium">Вихід</th>
                <th className="p-2 font-medium text-right">Деталі</th>
              </tr>
            </thead>
            <tbody className="text-gray-300 divide-y divide-gray-800/40">
              {trades.map((trade, index) => (
                <tr key={trade.id} className="hover:bg-gray-800/20">
                  <td className="p-2 text-gray-500">{index + 1}</td>
                  {windows > 1 && (
                    <td className="p-2 text-gray-400">{trade.window_index ?? 1}</td>
                  )}
                  <td className="p-2 whitespace-nowrap text-gray-400">
                    {formatDateTime(trade.entry_time)}
                  </td>
                  <td
                    className={`p-2 font-bold ${
                      trade.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'
                    }`}
                  >
                    {trade.side}
                    {trade.status === 'OPEN' && (
                      <span className="ml-1 text-[9px] text-amber-400">відкрита</span>
                    )}
                  </td>
                  <td className="p-2 text-right">{money(trade.entry_price)}</td>
                  <td className="p-2 text-right">
                    {trade.exit_price == null && trade.mark_price != null ? (
                      <span className="text-gray-400">{money(trade.mark_price)}*</span>
                    ) : (
                      money(trade.exit_price)
                    )}
                  </td>
                  <td className="p-2 text-right text-red-400/80">{money(trade.stop_loss)}</td>
                  <td className="p-2 text-right text-emerald-400/80">{money(trade.take_profit)}</td>
                  <td className="p-2 whitespace-nowrap text-gray-400">
                    {formatDuration(trade.duration_seconds, trade.duration_bars)}
                  </td>
                  <td
                    className={`p-2 text-right font-bold ${TONE_TEXT[toneOf(trade.realized_pnl)]}`}
                  >
                    {money(trade.realized_pnl)}
                    <div className="text-[9px] font-normal text-gray-500">
                      {formatPct((trade.realized_pnl_pct ?? 0) / 100)}
                    </div>
                  </td>
                  <td className="p-2 text-right text-gray-300">
                    {trade.r_multiple == null ? '—' : trade.r_multiple.toFixed(2)}
                  </td>
                  <td className="p-2 text-gray-400">{outcomeLabel(trade.exit_outcome)}</td>
                  <td className="p-2 text-right">
                    <a
                      href={linkFor(trade)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded border border-blue-800/60 text-blue-300 hover:bg-blue-950/40"
                    >
                      Розбір
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {trades.length > 0 && trades[0] && (
        <p className="text-[10px] text-gray-500 leading-relaxed">
          {describePnlBasis(trades[0])}.{' '}
          {trades.some((trade) => trade.status === 'OPEN') &&
            '* — поточна ціна відкритої позиції, не вихід. '}
          Посилання «Розбір» відкриває сторінку угоди з графіком, стопом, тейком, індикаторами
          та ланцюжком рішень — посилання можна скопіювати або відкрити в новій вкладці.
        </p>
      )}
    </div>
  );
};
