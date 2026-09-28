import React from 'react';
import { ListOrdered } from 'lucide-react';
import { TradesTable } from './TradesTable';
import { useSessionTrades } from './useSessionTrades';
import type { TradeRoute } from '../../lib/trades';

interface TradesPanelProps {
  /** Live session id/name, or a research run id — the API resolves both. */
  sessionKey: string | null;
  /** Context the trade page needs beyond the id (instrument, interval, catalog). */
  linkContext: Omit<TradeRoute, 'session' | 'id'> & { session: string };
  /** Re-read every N ms; a live session keeps appending trades. */
  pollMs?: number;
  emptyHint?: string;
}

/**
 * The trade list of one session: the shared table plus the fetch that feeds it.
 *
 * Used by the live paper terminal; the Backtest Details modal renders `TradesTable` with
 * the run id in the same role, which is the whole point — a backtest and a paper session
 * are read through one interface because they are reconstructed from one log format.
 */
export const TradesPanel: React.FC<TradesPanelProps> = ({
  sessionKey,
  linkContext,
  pollMs = 0,
  emptyHint,
}) => {
  const { data, loading, error, reload } = useSessionTrades(sessionKey, pollMs);

  if (!sessionKey) {
    return (
      <div className="py-8 text-center text-xs text-gray-500">
        Сесію не вибрано: список угод читається з журналу рішень конкретної сесії.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <ListOrdered className="w-4 h-4" />
        <span>
          Угоди відновлені з журналу рішень: вхід, вихід, стоп, тейк та індикатори на обох
          кінцях. Кожен рядок веде на окрему сторінку розбору.
        </span>
      </div>
      <TradesTable
        trades={data?.trades ?? []}
        loading={loading}
        error={error}
        linkContext={linkContext}
        truncated={data?.truncated}
        recordsScanned={data?.records}
        windows={data?.windows}
        onReload={reload}
        emptyHint={emptyHint}
      />
    </div>
  );
};
