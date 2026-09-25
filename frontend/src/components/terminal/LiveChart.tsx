import React, { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineStyle,
  createChart,
} from 'lightweight-charts';
import type {
  IChartApi,
  IPriceLine,
  ISeriesApi,
  Time,
} from 'lightweight-charts';
import type { LiveBar, LivePosition } from '../../services/api';

const POPULAR_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'];
const INTERVALS = ['1m', '3m', '5m', '15m', '1h'];

interface LiveChartProps {
  symbol: string;
  setSymbol: (sym: string) => void;
  interval: string;
  setIntervalVal: (intv: string) => void;
  robot: string;
  mode: 'paper' | 'live_guarded';
  statusMsg: string;
  recentBars?: LiveBar[];
  lastBar?: LiveBar | null;
  position?: LivePosition | null;
  isActive?: boolean;
}

export const LiveChart: React.FC<LiveChartProps> = ({
  symbol,
  setSymbol,
  interval,
  setIntervalVal,
  robot,
  mode,
  statusMsg,
  recentBars,
  lastBar,
  position,
  isActive = false,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  const entryLineRef = useRef<IPriceLine | null>(null);
  const slLineRef = useRef<IPriceLine | null>(null);
  const tpLineRef = useRef<IPriceLine | null>(null);

  // Initialize Lightweight Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const container = chartContainerRef.current;
    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: '#090d16' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
      },
      crosshair: {
        mode: 1,
      },
      timeScale: {
        borderColor: '#1e293b',
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: '#1e293b',
        autoScale: true,
      },
      height: 380,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const handleResize = () => {
      if (container) {
        chart.applyOptions({ width: container.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // Update Price Lines on Position change
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries) return;

    if (entryLineRef.current) {
      candleSeries.removePriceLine(entryLineRef.current);
      entryLineRef.current = null;
    }
    if (slLineRef.current) {
      candleSeries.removePriceLine(slLineRef.current);
      slLineRef.current = null;
    }
    if (tpLineRef.current) {
      candleSeries.removePriceLine(tpLineRef.current);
      tpLineRef.current = null;
    }

    if (!position) return;

    const entryPrice = parseFloat(position.entry_price);
    if (!isNaN(entryPrice) && entryPrice > 0) {
      entryLineRef.current = candleSeries.createPriceLine({
        price: entryPrice,
        color: '#3b82f6',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `ENTRY (${position.side} ${position.qty})`,
      });
    }

    if (position.stop_loss) {
      const slPrice = parseFloat(position.stop_loss);
      if (!isNaN(slPrice) && slPrice > 0) {
        slLineRef.current = candleSeries.createPriceLine({
          price: slPrice,
          color: '#ef4444',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `STOP LOSS (${position.stop_loss})`,
        });
      }
    }

    if (position.take_profit) {
      const tpPrice = parseFloat(position.take_profit);
      if (!isNaN(tpPrice) && tpPrice > 0) {
        tpLineRef.current = candleSeries.createPriceLine({
          price: tpPrice,
          color: '#10b981',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `TAKE PROFIT (${position.take_profit})`,
        });
      }
    }
  }, [position]);

  // Set initial bars data
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !recentBars || recentBars.length === 0) {
      return;
    }

    const candleData = recentBars.map((b) => ({
      time: b.time as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));

    const volumeData = recentBars.map((b) => ({
      time: b.time as Time,
      value: b.volume,
      color: b.close >= b.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
    }));

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);
  }, [recentBars]);

  // Handle single bar update
  useEffect(() => {
    if (!lastBar || !candleSeriesRef.current || !volumeSeriesRef.current) return;

    candleSeriesRef.current.update({
      time: lastBar.time as Time,
      open: lastBar.open,
      high: lastBar.high,
      low: lastBar.low,
      close: lastBar.close,
    });
    volumeSeriesRef.current.update({
      time: lastBar.time as Time,
      value: lastBar.volume,
      color: lastBar.close >= lastBar.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
    });
  }, [lastBar]);

  return (
    <div className="lg:col-span-3 flex flex-col gap-3 bg-[#0d131f] border border-gray-800 p-4 rounded-2xl">
      {/* Chart Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800/80 pb-3">
        <div className="flex items-center gap-2">
          <span className="font-bold text-gray-200 text-sm">{symbol}</span>
          <span className="text-xs text-gray-400">•</span>
          <span className="text-xs font-mono text-gray-400">{interval}</span>
          <span className="text-xs text-gray-400">•</span>
          <span className="text-xs font-mono text-blue-400 uppercase">{robot}</span>
        </div>

        {/* Quick Chart Symbols & Interval Selection */}
        <div className="flex items-center gap-2">
          <div className="flex bg-gray-950 border border-gray-800 rounded-lg p-0.5 text-xs">
            {POPULAR_SYMBOLS.map((sym) => (
              <button
                type="button"
                key={sym}
                onClick={() => setSymbol(sym)}
                disabled={isActive}
                className={`px-2 py-1 rounded text-[11px] font-medium transition-colors ${
                  symbol === sym
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {sym.replace('USDT', '')}
              </button>
            ))}
          </div>

          <div className="flex bg-gray-950 border border-gray-800 rounded-lg p-0.5 text-xs">
            {INTERVALS.map((intv) => (
              <button
                type="button"
                key={intv}
                onClick={() => setIntervalVal(intv)}
                disabled={isActive}
                className={`px-2 py-1 rounded text-[11px] font-mono transition-colors ${
                  interval === intv
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {intv}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart Canvas */}
      <div className="relative w-full rounded-xl overflow-hidden">
        <div ref={chartContainerRef} className="w-full h-[380px]" />
        {mode === 'paper' && (
          <div className="absolute top-4 right-4 pointer-events-none select-none text-[11px] font-mono text-amber-500/40 border border-amber-500/20 px-2 py-1 rounded bg-amber-950/10">
            PAPER SIMULATION ENVIRONMENT
          </div>
        )}
      </div>

      {/* Legend Strip */}
      <div className="flex flex-wrap items-center justify-between text-[11px] font-mono text-gray-400 pt-1 border-t border-gray-800/60">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-0.5 bg-blue-500 inline-block" /> Entry Price
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-0.5 bg-red-500 border-b border-dashed inline-block" /> Stop Loss
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2.5 h-0.5 bg-emerald-500 border-b border-dashed inline-block" /> Take Profit
          </span>
        </div>
        <div className="text-gray-500">{statusMsg}</div>
      </div>
    </div>
  );
};
