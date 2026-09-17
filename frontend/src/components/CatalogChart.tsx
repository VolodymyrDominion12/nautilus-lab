import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import type {
  CandlestickData,
  IChartApi,
  ISeriesApi,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import { AlertCircle, Loader2 } from 'lucide-react';
import { fetchCatalogBars } from '../services/api';
import type { CatalogBarPoint } from '../services/api';
import { createWindowBands } from '../lib/windowBands';
import type { WindowBandsPrimitive, WindowBoundaries } from '../lib/windowBands';

interface CatalogChartProps {
  instrumentId?: string;
  catalogPath?: string;
  barInterval?: string;
  limit?: number;
  height?: number;
  /** Walk-forward boundaries drawn on the chart: amber for selection, green for OOS. */
  boundaries?: WindowBoundaries;
  showVolume?: boolean;
  title?: string;
}

/**
 * Catalog price chart with the walk-forward window drawn on the time axis.
 *
 * The chart object is created once per (height, volume) configuration and the data is
 * pushed into it, so moving a date field updates the bands and the visible range without
 * tearing the chart down — rebuilding it would throw away the user's zoom and pan on every
 * keystroke.
 */
export function CatalogChart({
  instrumentId,
  catalogPath,
  barInterval,
  limit = 400,
  height = 280,
  boundaries,
  showVolume = true,
  title,
}: CatalogChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const bandsRef = useRef<WindowBandsPrimitive | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [generation, setGeneration] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<{
    count: number;
    first: string | null;
    last: string | null;
  } | null>(null);

  const bandValues = useMemo(
    () => ({
      isStart: boundaries?.isStart ?? null,
      isEnd: boundaries?.isEnd ?? null,
      oosStart: boundaries?.oosStart ?? null,
      oosEnd: boundaries?.oosEnd ?? null,
    }),
    [boundaries?.isStart, boundaries?.isEnd, boundaries?.oosStart, boundaries?.oosEnd],
  );

  // --- chart lifetime: one chart per (height, showVolume) -------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0b0f19' },
        textColor: '#9CA3AF',
      },
      grid: {
        vertLines: { color: '#182030' },
        horzLines: { color: '#182030' },
      },
      width: containerRef.current.clientWidth,
      height,
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: '#1f2937' },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10B981',
      downColor: '#EF4444',
      borderVisible: false,
      wickUpColor: '#10B981',
      wickDownColor: '#EF4444',
    });
    seriesRef.current = candleSeries;

    if (showVolume) {
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
        color: '#334155',
      });
      volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      volumeRef.current = volumeSeries;
    }

    const bands = createWindowBands();
    candleSeries.attachPrimitive(bands);
    bandsRef.current = bands;
    setGeneration((value) => value + 1);

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      bandsRef.current = null;
      volumeRef.current = null;
      seriesRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
  }, [height, showVolume]);

  // --- data + bands: refetch when the request or the window changes ---------------------
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const series = seriesRef.current;
      const chart = chartRef.current;
      if (!series || !chart) return;

      setLoading(true);
      setError(null);
      try {
        // When a window is defined, fetch around it so its boundaries are always on screen.
        // Otherwise fall back to the most recent `limit` bars.
        const padSeconds = 60 * 60 * 24 * 5;
        const anchors = [bandValues.isStart, bandValues.oosEnd].filter(
          (value): value is number => value != null,
        );
        const start =
          anchors.length > 0 ? new Date((Math.min(...anchors) - padSeconds) * 1000) : null;
        const end =
          anchors.length > 0 ? new Date((Math.max(...anchors) + padSeconds) * 1000) : null;

        const data = await fetchCatalogBars({
          instrument_id: instrumentId,
          catalog_path: catalogPath,
          bar_interval: barInterval,
          start: start?.toISOString(),
          end: end?.toISOString(),
          // A windowed request must not be truncated from the front, or the chart would
          // silently drop the beginning of the very window being edited.
          limit: anchors.length > 0 ? 0 : limit,
        });
        if (cancelled) return;

        if (!data.bars || data.bars.length === 0) {
          series.setData([]);
          setMeta({ count: 0, first: null, last: null });
          setError(
            `No bars for ${data.instrument_id ?? instrumentId ?? 'this instrument'} in ${data.catalog_path}. Check the catalog interval and run an ingest if it is empty.`,
          );
          setLoading(false);
          return;
        }

        setMeta({ count: data.count, first: data.first_date, last: data.last_date });

        const candles: CandlestickData<Time>[] = data.bars.map((bar: CatalogBarPoint) => ({
          time: bar.time as UTCTimestamp,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        }));
        series.setData(candles);

        volumeRef.current?.setData(
          data.bars.map((bar: CatalogBarPoint) => ({
            time: bar.time as UTCTimestamp,
            value: bar.volume,
            color: bar.close >= bar.open ? 'rgba(16,185,129,0.35)' : 'rgba(239,68,68,0.35)',
          })),
        );

        bandsRef.current?.setBands(bandValues);

        const known = new Set(candles.map((candle) => candle.time as number));
        const markers = (
          [
            [bandValues.isStart, 'IS starts', '#f59e0b'],
            [bandValues.isEnd, 'IS ends', '#f59e0b'],
            [bandValues.oosStart, 'OOS starts', '#10b981'],
            [bandValues.oosEnd, 'OOS ends', '#10b981'],
          ] as [number | null, string, string][]
        )
          .filter(([seconds]) => seconds != null && known.has(seconds as number))
          .map(([seconds, text, color]) => ({
            time: seconds as unknown as Time,
            position: 'aboveBar' as const,
            color,
            shape: 'arrowDown' as const,
            text,
          }));
        createSeriesMarkers(series, markers);

        chart.timeScale().fitContent();
        setLoading(false);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load catalog bars');
        setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [
    generation,
    instrumentId,
    catalogPath,
    barInterval,
    limit,
    bandValues,
  ]);

  const hasWindow = Object.values(bandValues).some((value) => value != null);

  return (
    <div className="relative w-full rounded-xl overflow-hidden bg-gray-950 border border-gray-800">
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-gray-800/80 text-[10px] font-mono">
        <span className="text-gray-400 truncate">
          {title ?? instrumentId ?? 'catalog preview'}
          {meta && meta.count > 0 && (
            <span className="text-gray-600">
              {' · '}
              {meta.count.toLocaleString()} bars
              {meta.first ? ` · ${meta.first.slice(0, 10)} → ${meta.last?.slice(0, 10)}` : ''}
            </span>
          )}
        </span>
        {hasWindow && (
          <span className="flex items-center gap-2 shrink-0">
            <span className="px-1.5 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-800/50">
              selection (IS)
            </span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800/50">
              report (OOS)
            </span>
          </span>
        )}
      </div>

      {loading && (
        <div
          className="absolute inset-0 top-7 flex items-center justify-center bg-gray-950/70 z-10"
          style={{ height }}
        >
          <span className="flex items-center gap-2 text-xs text-gray-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading bars…
          </span>
        </div>
      )}

      {error && !loading && (
        <div
          className="absolute inset-0 top-7 flex items-center justify-center p-4 z-10"
          style={{ height }}
        >
          <div className="flex items-start gap-2 text-xs text-amber-300 bg-amber-950/40 border border-amber-800/50 rounded-xl p-3 max-w-md">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        </div>
      )}

      <div ref={containerRef} style={{ height }} className="w-full" />
    </div>
  );
}
