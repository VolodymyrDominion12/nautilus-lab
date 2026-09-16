import { useEffect, useRef } from 'react';
import { ColorType, CandlestickSeries, createChart } from 'lightweight-charts';
import { fetchCatalogBars } from '../services/api';
import type { CatalogBarPoint } from '../services/api';

interface CatalogChartProps {
  instrumentId?: string;
  catalogPath?: string;
  limit?: number;
  height?: number;
  /** Unix seconds for in-sample end marker (optional overlay) */
  isEndTime?: number | null;
  /** Unix seconds for OOS start marker (optional overlay) */
  oosStartTime?: number | null;
}

export function CatalogChart({
  instrumentId,
  catalogPath,
  limit = 400,
  height = 280,
  isEndTime = null,
  oosStartTime = null,
}: CatalogChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const seriesRef = useRef<any>(null);

  useEffect(() => {
    let chart: ReturnType<typeof createChart> | null = null;

    const load = async () => {
      try {
        const data = await fetchCatalogBars({
          instrument_id: instrumentId,
          catalog_path: catalogPath,
          limit,
        });
        if (!containerRef.current) return;

        chart = createChart(containerRef.current, {
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
        });

        seriesRef.current = chart.addSeries(CandlestickSeries, {
          upColor: '#10B981',
          downColor: '#EF4444',
          borderVisible: false,
          wickUpColor: '#10B981',
          wickDownColor: '#EF4444',
        });

        const candles = data.bars.map((bar: CatalogBarPoint) => ({
          time: bar.time as any,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        }));
        seriesRef.current.setData(candles);

        if (isEndTime) {
          chart.timeScale().setVisibleRange({
            from: candles[0]?.time,
            to: candles[candles.length - 1]?.time,
          });
        }
      } catch (err) {
        console.error('Catalog chart load failed', err);
      }
    };

    load();

    const handleResize = () => {
      if (chart && containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart?.remove();
    };
  }, [instrumentId, catalogPath, limit, height, isEndTime, oosStartTime]);

  return (
    <div className="relative w-full rounded-xl overflow-hidden bg-gray-950 border border-gray-800">
      {(isEndTime || oosStartTime) && (
        <div className="absolute top-2 right-2 z-10 flex gap-2 text-[10px] font-mono">
          {isEndTime && (
            <span className="px-2 py-0.5 rounded bg-amber-950/70 text-amber-300 border border-amber-800/50">
              IS ends
            </span>
          )}
          {oosStartTime && (
            <span className="px-2 py-0.5 rounded bg-blue-950/70 text-blue-300 border border-blue-800/50">
              OOS starts
            </span>
          )}
        </div>
      )}
      <div ref={containerRef} style={{ height }} className="w-full" />
    </div>
  );
}
