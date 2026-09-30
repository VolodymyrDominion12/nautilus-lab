import React, { useMemo, useState } from 'react';
import { ArrowLeft, Copy, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import type { TradeRoute } from '../../lib/trades';
import { buildTradeHash, describeMissingDetail } from '../../lib/trades';
import { useTrade } from './useSessionTrades';
import { TradeChart } from './TradeChart';
import { TradeSummaryGrid } from './TradeSummaryGrid';
import { TradeIndicatorTable } from './TradeIndicatorTable';
import { TradeDecisionTimeline } from './TradeDecisionTimeline';
import { overlaySeries } from '../../lib/tradeOverlays';

interface TradeDetailPageProps {
  route: TradeRoute;
  /** Leaves the trade page; the caller keeps the tab the user came from. */
  onClose: () => void;
}

/**
 * One trade, on its own page: chart, levels, indicators and the whole decision chain.
 *
 * The same component serves a live paper session and a research backtest, because both
 * reconstruct their trades from the decision log (`GET /api/paper/sessions/{key}/trades/{id}`)
 * — the interface is identical because the data behind it is. The address is a fragment
 * (`#/trade?...`), so a link to a trade can be pasted, bookmarked or opened in a new tab.
 */
export const TradeDetailPage: React.FC<TradeDetailPageProps> = ({ route, onClose }) => {
  const [copied, setCopied] = useState(false);
  const { data, loading, error, reload } = useTrade(
    route.session,
    route.id,
    {
      instrumentId: route.instrument,
      barInterval: route.interval,
      catalogPath: route.catalog,
    },
    route.origin === 'paper' ? 5000 : 0,
  );

  const trade = data?.trade;
  const missingDetail = trade ? describeMissingDetail(trade) : null;
  // Context bars before the entry and after the exit, then the trade's own records.
  const overlays = useMemo(
    () =>
      data && trade
        ? overlaySeries([...(data.context ?? []), ...trade.decisions], data.chart.bars ?? [])
        : [],
    [data, trade],
  );

  const copyLink = async () => {
    const url = `${window.location.origin}${window.location.pathname}${buildTradeHash(route)}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-center gap-3 border-b border-gray-800 pb-3">
        <button
          type="button"
          onClick={onClose}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg border border-gray-700"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Назад
        </button>

        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-gray-100">
            {trade ? `${trade.symbol} · ${trade.side}` : 'Угода'}
          </h2>
          {trade && (
            <span
              className={`text-[10px] px-2 py-0.5 rounded border ${
                trade.status === 'OPEN'
                  ? 'border-amber-700/60 text-amber-300 bg-amber-950/30'
                  : 'border-gray-700 text-gray-400 bg-gray-900'
              }`}
            >
              {trade.status === 'OPEN' ? 'відкрита' : 'закрита'}
            </span>
          )}
          <span className="text-[10px] font-mono text-gray-500">
            {route.title ? `${route.title} · ` : ''}
            {route.origin === 'backtest' ? 'бектест' : route.origin === 'paper' ? 'paper' : ''}
            {data && data.windows > 1 && trade
              ? ` · прохід ${trade.window_index ?? 1} з ${data.windows}`
              : ''}
          </span>
        </div>

        <span className="text-[10px] font-mono text-gray-600 truncate max-w-[22rem]">
          {route.id}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={copyLink}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg border border-gray-700"
          >
            <Copy className="w-3.5 h-3.5" />
            {copied ? 'Скопійовано' : 'Копіювати посилання'}
          </button>
          <a
            href={buildTradeHash(route)}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg border border-gray-700"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Нова вкладка
          </a>
          <button
            type="button"
            onClick={reload}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-900 hover:bg-gray-800 text-gray-300 rounded-lg border border-gray-700"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Оновити
          </button>
        </div>
      </header>

      {error && (
        <div className="p-4 rounded-xl bg-red-950/30 border border-red-900/50 text-xs text-red-300">
          <div className="font-semibold mb-1">Угоду не вдалося прочитати</div>
          {error}
          <div className="mt-2 text-red-400/80">
            Угода не зберігається окремо: її щоразу відновлюють із журналу рішень сесії, тож
            «не знайдено» означає, що записів про неї вже немає у прочитаному вікні журналу
            (retention або завелике вікно прогону).
          </div>
        </div>
      )}

      {loading && !trade && (
        <div className="py-16 flex items-center justify-center gap-2 text-xs text-gray-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Читаю журнал рішень…
        </div>
      )}

      {trade && (
        <>
          {data?.truncated && (
            <div className="p-3 rounded-xl bg-amber-950/20 border border-amber-800/40 text-[11px] text-amber-200">
              Прочитано останні {data.records} записів журналу: старіші не скановано. Показники
              цієї угоди відновлено з того, що потрапило у вікно.
            </div>
          )}

          <TradeSummaryGrid trade={trade} />

          <TradeChart trade={trade} chart={data!.chart} overlays={overlays} />

          <TradeIndicatorTable trade={trade} />

          <TradeDecisionTimeline trade={trade} note={missingDetail} />
        </>
      )}
    </div>
  );
};
