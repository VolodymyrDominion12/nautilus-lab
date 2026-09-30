import React, { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  LineType,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import type {
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import { AlertCircle } from 'lucide-react';
import type { TradeChart as TradeChartPayload, TradeSummary } from '../../services/api';
import { tradeMarkers, tradePriceLines } from '../../lib/trades';
import type { OverlaySeries } from '../../lib/tradeOverlays';

interface TradeChartProps {
  trade: TradeSummary;
  chart: TradeChartPayload;
  height?: number;
  /** Indicator lines and the stop's path from the decision log (`lib/tradeOverlays.ts`). */
  overlays?: OverlaySeries[];
}

const NO_OVERLAYS: OverlaySeries[] = [];

/**
 * The candles around one trade, with the entry, the exit and the protective levels on it.
 *
 * The bars come with the trade from the API instead of being fetched here: the backend
 * knows which source actually holds them (a live session's own stream, or the parquet
 * catalog for a backtest), and a browser-side guess at a catalog path is how a chart ends
 * up empty next to a real trade. Markers are snapped onto candles that exist — a decision
 * is stamped with the bar's **end**, so an unsnapped marker is dropped without a word.
 */
export const TradeChart: React.FC<TradeChartProps> = ({
  trade,
  chart,
  height = 380,
  overlays = NO_OVERLAYS,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  // Both are re-applied on every update, and a live session polls: creating them again
  // instead of updating would stack a second set of arrows and levels on each poll.
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const overlayRefs = useRef<ISeriesApi<'Line'>[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const instance = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#090d16' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
      },
      timeScale: { borderColor: '#1e293b', timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: '#1e293b' },
      height,
    });
    const candles = instance.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });
    const volume = instance.addSeries(HistogramSeries, {
      color: '#334155',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    chartRef.current = instance;
    seriesRef.current = candles;
    volumeRef.current = volume;

    const handleResize = () => {
      chartRef.current?.applyOptions({ width: container.clientWidth });
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      markersRef.current = null;
      priceLinesRef.current = [];
      overlayRefs.current = [];
      seriesRef.current = null;
      volumeRef.current = null;
      chartRef.current = null;
      instance.remove();
    };
  }, [height]);

  useEffect(() => {
    const series = seriesRef.current;
    const instance = chartRef.current;
    if (!series || !instance) return;

    const bars = chart.bars ?? [];
    if (bars.length === 0) {
      series.setData([]);
      volumeRef.current?.setData([]);
      markersRef.current?.setMarkers([]);
      for (const line of priceLinesRef.current) series.removePriceLine(line);
      priceLinesRef.current = [];
      return;
    }

    series.setData(
      bars.map((bar) => ({
        time: bar.time as UTCTimestamp,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    volumeRef.current?.setData(
      bars.map((bar) => ({
        time: bar.time as UTCTimestamp,
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(16,185,129,0.35)' : 'rgba(239,68,68,0.35)',
      })),
    );

    const markers = tradeMarkers(trade, bars).map((marker) => ({
      time: marker.time as unknown as Time,
      position: marker.position,
      color: marker.color,
      shape: marker.shape,
      text: marker.text,
    }));
    if (markersRef.current) markersRef.current.setMarkers(markers);
    else markersRef.current = createSeriesMarkers(series, markers);

    for (const line of priceLinesRef.current) series.removePriceLine(line);
    // With the stop drawn as its own step line, a flat "final stop" price line would
    // only repeat its last point; keep it when the log has no stop history to draw.
    const hasStopPath = overlays.some((overlay) => overlay.key === 'stop_loss');
    const lines = tradePriceLines(trade).filter(
      (line) => !(hasStopPath && line.title === 'Стоп-лос'),
    );
    priceLinesRef.current = lines.map((line) =>
      series.createPriceLine({
        price: line.price,
        color: line.color,
        lineWidth: 2,
        lineStyle: line.lineStyle,
        axisLabelVisible: true,
        title: line.title,
      }),
    );

    for (const old of overlayRefs.current) instance.removeSeries(old);
    overlayRefs.current = overlays.map((overlay) => {
      const line = instance.addSeries(LineSeries, {
        color: overlay.color,
        lineWidth: overlay.key === 'stop_loss' ? 2 : 1,
        lineStyle: overlay.dashed ? LineStyle.Dashed : LineStyle.Solid,
        lineType: overlay.step ? LineType.WithSteps : LineType.Simple,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        title: overlay.label,
      });
      line.setData(
        overlay.points.map((point) => ({ time: point.time as UTCTimestamp, value: point.value })),
      );
      return line;
    });

    instance.timeScale().fitContent();
  }, [chart, trade, overlays]);

  return (
    <div className="rounded-xl overflow-hidden border border-gray-800 bg-gray-950">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5 border-b border-gray-800/80 text-[10px] font-mono">
        <span className="text-gray-400 truncate">
          {chart.instrument_id ?? trade.symbol}
          {chart.bar_interval ? ` · ${chart.bar_interval}` : ''}
          <span className="text-gray-600"> · {chart.bars.length} барів</span>
        </span>
        <span className="flex items-center gap-2 shrink-0">
          <span className="px-1.5 py-0.5 rounded bg-gray-800/60 text-gray-300 border border-gray-700">
            Джерело: {chartSourceLabel(chart.source)}
          </span>
          {chart.source === 'session' && (
            <span className="px-1.5 py-0.5 rounded bg-blue-950/60 text-blue-300 border border-blue-900">
              бари сесії
            </span>
          )}
        </span>
      </div>

      {chart.bars.length === 0 ? (
        <div
          className="flex items-center justify-center p-6 text-center"
          style={{ height: height - 28 }}
        >
          <div className="flex items-start gap-2 text-xs text-amber-300 bg-amber-950/40 border border-amber-800/50 rounded-xl p-3 max-w-lg">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              Графік недоступний. {chart.note ?? 'Бари для цієї угоди не знайдено.'}
            </span>
          </div>
        </div>
      ) : (
        <div ref={containerRef} style={{ height: height - 28 }} className="w-full" />
      )}
      {chart.bars.length > 0 && chart.note && (
        <div className="px-3 py-1.5 border-t border-gray-800/80 text-[10px] text-gray-500 font-mono">
          {chart.note}
        </div>
      )}
    </div>
  );
};

function chartSourceLabel(source: TradeChartPayload['source']): string {
  if (source === 'session') return 'живий потік сесії';
  if (source === 'catalog') return 'parquet-каталог';
  return 'немає';
}
