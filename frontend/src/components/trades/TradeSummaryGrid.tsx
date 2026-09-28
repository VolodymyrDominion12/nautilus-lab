import React from 'react';
import type { TradeDetail } from '../../services/api';
import { TONE_TEXT, formatDateTime, formatPct, toneOf } from '../../lib/format';
import { describePnlBasis, formatDuration, outcomeLabel } from '../../lib/trades';

interface TradeSummaryGridProps {
  trade: TradeDetail;
}

const money = (value: number | null | undefined, digits = 2): string =>
  value == null ? '—' : `$${value.toFixed(digits)}`;

const Cell: React.FC<{ label: string; value: React.ReactNode; hint?: string; className?: string }> = ({
  label,
  value,
  hint,
  className,
}) => (
  <div className="p-3 rounded-xl bg-gray-900/60 border border-gray-800">
    <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
    <div className={`mt-1 font-mono text-sm ${className ?? 'text-gray-100'}`}>{value}</div>
    {hint && <div className="mt-1 text-[10px] text-gray-500 leading-snug">{hint}</div>}
  </div>
);

/**
 * The numbers of one trade, each with the sentence that says where it came from.
 *
 * `stop_loss` and `take_profit` are the levels the trade **ended** with: the log updates
 * them as the stop ratchets, and the page has no per-bar history of the level, so the
 * panel says so rather than pretending this was the risk from the first bar.
 */
export const TradeSummaryGrid: React.FC<TradeSummaryGridProps> = ({ trade }) => (
  <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
    <Cell
      label="Напрям"
      value={trade.side}
      className={trade.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'}
      hint={trade.status === 'OPEN' ? 'Позиція ще відкрита' : 'Позицію закрито'}
    />
    <Cell
      label="Результат"
      value={
        <>
          {money(trade.realized_pnl)}
          <span className="ml-2 text-xs text-gray-400">
            {formatPct((trade.realized_pnl_pct ?? 0) / 100)}
          </span>
        </>
      }
      className={TONE_TEXT[toneOf(trade.realized_pnl)]}
      hint={describePnlBasis(trade)}
    />
    <Cell
      label="R-множник"
      value={trade.r_multiple == null ? '—' : trade.r_multiple.toFixed(2)}
      hint="Результат у ризиках: відстань входу до стопа"
    />
    <Cell
      label="Комісія"
      value={trade.fee_known ? money(trade.fee, 4) : '—'}
      hint={trade.fee_known ? 'Із журналу угод сесії' : 'Комісії цієї угоди в журналі немає'}
    />
    <Cell label="Ціна входу" value={money(trade.entry_price)} />
    <Cell
      label={trade.status === 'OPEN' ? 'Поточна ціна' : 'Ціна виходу'}
      value={money(trade.exit_price ?? trade.mark_price)}
    />
    <Cell
      label="Стоп-лос"
      value={money(trade.stop_loss)}
      className="text-red-400"
      hint="Рівень на момент закриття: стоп міг рухатись за ціною"
    />
    <Cell
      label="Тейк-профіт"
      value={money(trade.take_profit)}
      className="text-emerald-400"
    />
    <Cell
      label="Тривалість"
      value={formatDuration(trade.duration_seconds, trade.duration_bars)}
    />
    <Cell
      label="Розмір позиції"
      value={trade.qty_known ? String(trade.qty) : `${trade.qty ?? 1} (припущено)`}
      hint={trade.qty_known ? undefined : 'Розміру в журналі немає: результат рахується на 1 одиницю'}
    />
    <Cell
      label="Найкраща точка"
      value={
        trade.mfe_close == null
          ? '—'
          : `${money(trade.mfe_close)} (${formatPct((trade.mfe_close_pct ?? 0) / 100)})`
      }
      className="text-emerald-400/90"
      hint={`За ${trade.excursion_basis ?? 'закриттями барів'}: максимум, який угода бачила`}
    />
    <Cell
      label="Найгірша точка"
      value={
        trade.mae_close == null
          ? '—'
          : `${money(trade.mae_close)} (${formatPct((trade.mae_close_pct ?? 0) / 100)})`
      }
      className="text-red-400/90"
      hint="Протихід до входу, який угода пережила"
    />
    <Cell
      label="Вхід"
      value={formatDateTime(trade.entry_time)}
      hint={trade.entry_reason || undefined}
    />
    <Cell
      label="Вихід"
      value={trade.exit_time ? formatDateTime(trade.exit_time) : '—'}
      hint={trade.exit_reason || outcomeLabel(trade.exit_outcome)}
    />
    <Cell label="Режим на вході" value={trade.regime_at_entry || '—'} />
    <Cell label="Режим на виході" value={trade.regime_at_exit || '—'} />
  </div>
);
