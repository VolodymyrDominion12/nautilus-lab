import React, { useEffect, useRef, useState } from 'react';
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
import {
  ArrowDownRight,
  ArrowUpRight,
  Play,
  ShieldAlert,
  Square,
  Zap,
} from 'lucide-react';
import {
  closeLivePosition,
  fetchLivePaperState,
  getLivePaperWsUrl,
  startLivePaper,
  stopLivePaper,
  updateLiveStops,
} from '../services/api';
import { DecisionLogPanel } from './DecisionLogPanel';
import type {
  LiveBar,
  LivePaperState,
  LivePosition,
} from '../services/api';

interface LiveTradingTerminalProps {
  supportedRobots?: string[];
  /** Session shown and controlled here; null = the "new session" form. */
  sessionId?: string | null;
  /** Called with the new id after Start, and with null after Stop. */
  onSessionChange?: (sessionId: string | null) => void;
}

const POPULAR_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'];
const INTERVALS = ['1m', '3m', '5m', '15m', '1h'];

export const LiveTradingTerminal: React.FC<LiveTradingTerminalProps> = ({
  supportedRobots = ['regime', 'ema', 'adaptive_ema'],
  sessionId = null,
  onSessionChange,
}) => {
  const [sessionName, setSessionName] = useState('');
  const [sessionNotes, setSessionNotes] = useState('');
  // Session & Config state
  const [mode, setMode] = useState<'paper' | 'live_guarded'>('paper');
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [interval, setIntervalVal] = useState('1m');
  const [robot, setRobot] = useState('regime');
  const [autoTrade, setAutoTrade] = useState(true);
  const [startingEquity, setStartingEquity] = useState('10000');
  const [riskPct, setRiskPct] = useState('0.01');
  const [stopPct, setStopPct] = useState('0.015');
  const [tpMultiple, setTpMultiple] = useState('2.0');

  // Runtime State
  const [state, setState] = useState<LivePaperState | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [statusMsg, setStatusMsg] = useState('Ready');
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeBottomTab, setActiveBottomTab] = useState<'position' | 'fills' | 'risk' | 'decision_logs'>('position');

  // Editable Stops in UI
  const [editSl, setEditSl] = useState('');
  const [editTp, setEditTp] = useState('');
  const [showLiveWarningModal, setShowLiveWarningModal] = useState(false);

  // Chart References
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  // Price Lines
  const entryLineRef = useRef<IPriceLine | null>(null);
  const slLineRef = useRef<IPriceLine | null>(null);
  const tpLineRef = useRef<IPriceLine | null>(null);

  // WebSocket Ref
  const wsRef = useRef<WebSocket | null>(null);

  // Fetch initial state
  const loadInitialState = async () => {
    if (!sessionId) {
      setState(null);
      return;
    }
    try {
      const data = await fetchLivePaperState(sessionId);
      setState(data);
      if (data.position) {
        setEditSl(data.position.stop_loss || '');
        setEditTp(data.position.take_profit || '');
      }
    } catch (err) {
      console.error('Failed to fetch live paper state:', err);
    }
  };

  useEffect(() => {
    loadInitialState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

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
  const updatePriceLines = (pos: LivePosition | null) => {
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries) return;

    // Remove existing lines
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

    if (!pos) return;

    const entryPrice = parseFloat(pos.entry_price);
    if (!isNaN(entryPrice) && entryPrice > 0) {
      entryLineRef.current = candleSeries.createPriceLine({
        price: entryPrice,
        color: '#3b82f6',
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `ENTRY (${pos.side} ${pos.qty})`,
      });
    }

    if (pos.stop_loss) {
      const slPrice = parseFloat(pos.stop_loss);
      if (!isNaN(slPrice) && slPrice > 0) {
        slLineRef.current = candleSeries.createPriceLine({
          price: slPrice,
          color: '#ef4444',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `STOP LOSS (${pos.stop_loss})`,
        });
      }
    }

    if (pos.take_profit) {
      const tpPrice = parseFloat(pos.take_profit);
      if (!isNaN(tpPrice) && tpPrice > 0) {
        tpLineRef.current = candleSeries.createPriceLine({
          price: tpPrice,
          color: '#10b981',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `TAKE PROFIT (${pos.take_profit})`,
        });
      }
    }
  };

  // Populate chart with recent bars when state updates
  useEffect(() => {
    if (!state || !candleSeriesRef.current || !volumeSeriesRef.current) return;

    if (state.recent_bars && state.recent_bars.length > 0) {
      const candleData = state.recent_bars.map((b) => ({
        time: b.time as Time,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }));

      const volumeData = state.recent_bars.map((b) => ({
        time: b.time as Time,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
      }));

      candleSeriesRef.current.setData(candleData);
      volumeSeriesRef.current.setData(volumeData);
    }

    updatePriceLines(state.position);
  }, [state]);

  // While a session runs, the header and the (disabled) form show what the SERVER is
  // trading, not this page's defaults: a session started by LIVE_PAPER_AUTOSTART or
  // resumed after a restart was otherwise displayed as BTCUSDT 1m while trading ETH 1h.
  const activeConfig = state?.is_active ? state.config : null;
  useEffect(() => {
    if (!activeConfig) return;
    setSymbol(activeConfig.symbol);
    setIntervalVal(activeConfig.interval);
    setRobot(activeConfig.robot);
    setStartingEquity(activeConfig.starting_equity);
    setRiskPct(activeConfig.risk_per_trade);
    setStopPct(activeConfig.stop_pct);
    setTpMultiple(activeConfig.take_profit_multiple);
    setAutoTrade(activeConfig.auto_trade);
    setSessionName(state?.name ?? activeConfig.name ?? '');
    setSessionNotes(state?.notes ?? activeConfig.notes ?? '');
  }, [
    activeConfig?.symbol,
    activeConfig?.interval,
    activeConfig?.robot,
    activeConfig?.starting_equity,
    activeConfig?.risk_per_trade,
    activeConfig?.stop_pct,
    activeConfig?.take_profit_multiple,
    activeConfig?.auto_trade,
  ]);

  // WebSocket Connection — reconnects with backoff. Before, one API restart or network
  // blip left the terminal on "Stream disconnected" until the page was reloaded.
  useEffect(() => {
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let attempt = 0;

    if (!sessionId) {
      setIsConnected(false);
      setStatusMsg('No session selected: fill in the form and press Start');
      return () => {
        disposed = true;
      };
    }

    const connect = () => {
      if (disposed) return;
      const ws = new WebSocket(getLivePaperWsUrl(sessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        setIsConnected(true);
        setStatusMsg('Connected to Live Stream');
      };

      ws.onclose = (event) => {
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = null;
        setIsConnected(false);
        if (disposed) return;
        const delayMs = Math.min(15000, 1000 * 2 ** attempt);
        attempt += 1;
        if (event.code === 1008) {
          // Policy refusal from the API gate: say why instead of a bare "disconnected".
          setStatusMsg(
            `Refused by the API: ${event.reason || 'origin or token'} — open the dashboard at the ` +
              'address listed in API_ALLOWED_ORIGINS (and check API_TOKEN)',
          );
        } else {
          setStatusMsg(`Stream disconnected — reconnecting in ${Math.round(delayMs / 1000)}s`);
        }
        retryTimer = setTimeout(connect, delayMs);
      };

      ws.onerror = (err) => {
        console.warn('Live Paper WS error:', err);
      };

      ws.onmessage = (event) => {
        if (event.data === 'pong') return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'INIT_STATE' || msg.type === 'STATE_UPDATE') {
            const newState = msg.data as LivePaperState;
            setState(newState);
            updatePriceLines(newState.position);
            if (newState.position) {
              setEditSl(newState.position.stop_loss || '');
              setEditTp(newState.position.take_profit || '');
            }
          } else if (msg.type === 'BAR_UPDATE') {
            const bar = msg.data as LiveBar;
            if (candleSeriesRef.current && volumeSeriesRef.current) {
              candleSeriesRef.current.update({
                time: bar.time as Time,
                open: bar.open,
                high: bar.high,
                low: bar.low,
                close: bar.close,
              });
              volumeSeriesRef.current.update({
                time: bar.time as Time,
                value: bar.volume,
                color: bar.close >= bar.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
              });
            }

            // Update position mark price and floating PnL
            setState((prev) => {
              if (!prev) return null;
              return {
                ...prev,
                last_price: msg.last_price ?? prev.last_price,
                current_equity: msg.current_equity ?? prev.current_equity,
                unrealized_pnl: msg.unrealized_pnl ?? prev.unrealized_pnl,
                position: msg.position ?? prev.position,
              };
            });
          }
        } catch (e) {
          console.error('Error parsing WS message:', e);
        }
      };

      pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 15000);
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (pingTimer) clearInterval(pingTimer);
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  // Actions
  const handleStartSession = async () => {
    setActionError(null);
    try {
      const res = await startLivePaper({
        name: sessionName.trim(),
        notes: sessionNotes.trim(),
        symbol,
        interval,
        robot,
        starting_equity: startingEquity,
        risk_per_trade: riskPct,
        stop_pct: stopPct,
        take_profit_multiple: tpMultiple,
        mode,
        auto_trade: autoTrade,
      });
      if (res.status === 'started') {
        setStatusMsg(`Active: ${res.name ?? symbol} (${robot})`);
        if (res.session_id) onSessionChange?.(res.session_id);
      } else {
        setActionError(res.message || 'Failed to start session');
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error starting live paper session');
    }
  };

  const handleStopSession = async () => {
    if (!sessionId) return;
    const label = state?.name || sessionId;
    const confirmed = window.confirm(
      `Stop "${label}" for good?\n\nA stopped session is final: it is not resumed after a ` +
        'restart and is not restarted from the portfolio file. Use Pause to only halt new entries.',
    );
    if (!confirmed) return;
    setActionError(null);
    try {
      await stopLivePaper(sessionId);
      setStatusMsg('Session stopped');
      loadInitialState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error stopping session');
    }
  };

  const handleClosePosition = async () => {
    setActionError(null);
    try {
      if (!sessionId) return;
      const res = await closeLivePosition(sessionId);
      setStatusMsg(res.message || 'Position closed');
      loadInitialState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error closing position');
    }
  };

  const handleUpdateStops = async () => {
    setActionError(null);
    try {
      if (!sessionId) return;
      const res = await updateLiveStops(sessionId, {
        stop_loss: editSl ? editSl : null,
        take_profit: editTp ? editTp : null,
      });
      setStatusMsg(res.message || 'Stops updated');
      loadInitialState();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Error updating stops');
    }
  };

  const handleModeSwitch = (targetMode: 'paper' | 'live_guarded') => {
    if (targetMode === 'live_guarded') {
      setShowLiveWarningModal(true);
    } else {
      setMode('paper');
    }
  };

  const currentEquityNum = parseFloat(state?.current_equity || startingEquity);
  const startingEquityNum = parseFloat(state?.starting_equity || startingEquity);
  const netPnlNum = currentEquityNum - startingEquityNum;
  const netPnlPct = startingEquityNum > 0 ? (netPnlNum / startingEquityNum) * 100 : 0;
  const unrealizedPnlNum = parseFloat(state?.unrealized_pnl || '0');

  return (
    <div className="flex flex-col gap-5">
      {/* Top Header & Mode Switcher */}
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 bg-[#0d131f] border border-gray-800 p-4 rounded-2xl">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-blue-600/10 border border-blue-500/20 rounded-xl">
            <Zap className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-gray-100">Live Trading Terminal</h2>
              <span
                className={`px-2 py-0.5 text-[10px] font-bold tracking-wider rounded-md uppercase border ${
                  mode === 'paper'
                    ? 'bg-amber-950/40 text-amber-300 border-amber-800/40'
                    : 'bg-red-950/50 text-red-300 border-red-800/50'
                }`}
              >
                {mode === 'paper' ? 'Paper Simulation' : 'Live Monitor (Guarded)'}
              </span>
            </div>
            <p className="text-xs text-gray-400 mt-0.5">
              Real-time candlestick charts, visual SL/TP triggers & dynamic position risk control.
            </p>
          </div>
        </div>

        {/* Mode Selector & Status */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Mode Toggle Button */}
          <div className="bg-gray-950 border border-gray-800 p-1 rounded-xl flex items-center">
            <button
              type="button"
              onClick={() => handleModeSwitch('paper')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'paper'
                  ? 'bg-amber-600/20 text-amber-300 border border-amber-500/30'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Paper Simulator
            </button>
            <button
              type="button"
              onClick={() => handleModeSwitch('live_guarded')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'live_guarded'
                  ? 'bg-red-600/20 text-red-300 border border-red-500/30'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Live Trading
            </button>
          </div>

          {/* Connection Indicator */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-950 border border-gray-800 rounded-xl text-xs font-mono">
            <span
              className={`w-2 h-2 rounded-full ${
                isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'
              }`}
            />
            <span className={isConnected ? 'text-gray-300' : 'text-red-400'}>
              {isConnected ? 'Stream Active' : 'Disconnected'}
            </span>
          </div>

          {/* Start / Stop Session */}
          {state?.is_active ? (
            <button
              type="button"
              onClick={handleStopSession}
              className="flex items-center gap-2 px-4 py-2 bg-red-950/60 hover:bg-red-900/60 text-red-200 border border-red-800/50 rounded-xl text-xs font-semibold transition-colors"
            >
              <Square className="w-3.5 h-3.5" /> Stop Session
            </button>
          ) : (
            <button
              type="button"
              onClick={handleStartSession}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold transition-colors shadow-lg shadow-emerald-900/20"
            >
              <Play className="w-3.5 h-3.5" /> Start Live Paper
            </button>
          )}
        </div>
      </div>

      {/* Safety Notice for Live Guarded mode */}
      {mode === 'live_guarded' && (
        <div className="p-3.5 rounded-xl bg-red-950/30 border border-red-800/40 flex items-start gap-3 text-xs text-red-200">
          <ShieldAlert className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-red-300">Live Trading Guard: Active. </span>
            In accordance with project architecture (AGENTS.md), real execution adapters are
            fail-closed. You receive real-time exchange prices and see live strategy signals, but no
            real capital or API keys reach an external exchange.
          </div>
        </div>
      )}

      {actionError && (
        <div className="p-3 rounded-xl bg-red-950/30 border border-red-800/50 text-red-300 text-xs">
          {actionError}
        </div>
      )}

      {/* Account Metrics Ribbon */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
          <span className="text-[11px] text-gray-400 block mb-1">Account Equity</span>
          <div className="text-base font-bold font-mono text-gray-100">
            ${currentEquityNum.toLocaleString('en-US', { minimumFractionDigits: 2 })}
          </div>
          <span className="text-[10px] text-gray-500">Initial: ${startingEquityNum}</span>
        </div>

        <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
          <span className="text-[11px] text-gray-400 block mb-1">Realized PnL</span>
          <div
            className={`text-base font-bold font-mono flex items-center gap-1 ${
              parseFloat(state?.realized_pnl || '0') >= 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {parseFloat(state?.realized_pnl || '0') >= 0 ? (
              <ArrowUpRight className="w-4 h-4" />
            ) : (
              <ArrowDownRight className="w-4 h-4" />
            )}
            ${state?.realized_pnl || '0.00'}
          </div>
          <span className="text-[10px] text-gray-500">Closed trades</span>
        </div>

        <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
          <span className="text-[11px] text-gray-400 block mb-1">Floating PnL</span>
          <div
            className={`text-base font-bold font-mono flex items-center gap-1 ${
              unrealizedPnlNum >= 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {unrealizedPnlNum >= 0 ? (
              <ArrowUpRight className="w-4 h-4" />
            ) : (
              <ArrowDownRight className="w-4 h-4" />
            )}
            ${unrealizedPnlNum.toFixed(2)}
          </div>
          <span className="text-[10px] text-gray-500">
            {state?.position ? state.position.unrealized_pnl_pct : 'No open position'}
          </span>
        </div>

        <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
          <span className="text-[11px] text-gray-400 block mb-1">Current Mark</span>
          <div className="text-base font-bold font-mono text-blue-400">
            {state?.last_price ? `$${parseFloat(state.last_price).toLocaleString()}` : '—'}
          </div>
          <span className="text-[10px] text-gray-500">{symbol} Binance spot</span>
        </div>

        <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
          <span className="text-[11px] text-gray-400 block mb-1">Exchange Fees</span>
          <div className="text-base font-bold font-mono text-gray-300">
            ${parseFloat(state?.fees_paid || '0').toFixed(4)}
          </div>
          <span className="text-[10px] text-gray-500">Simulated taker</span>
        </div>

        <div className="bg-[#0d131f] border border-gray-800/80 p-3.5 rounded-xl">
          <span className="text-[11px] text-gray-400 block mb-1">Session Total Return</span>
          <div
            className={`text-base font-bold font-mono ${
              netPnlNum >= 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {netPnlPct >= 0 ? '+' : ''}
            {netPnlPct.toFixed(2)}%
          </div>
          <span className="text-[10px] text-gray-500">{state?.fills.length || 0} order fills</span>
        </div>
      </div>

      {/* Main Grid: Chart + Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-5">
        {/* Chart Column (3 cols) */}
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
                    disabled={state?.is_active}
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
                    disabled={state?.is_active}
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

        {/* Sidebar Controls Column (1 col) */}
        <div className="flex flex-col gap-4">
          {/* Active Position Card */}
          <div className="bg-[#0d131f] border border-gray-800 p-4 rounded-2xl space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-300">Active Position</span>
              {state?.position ? (
                <span
                  className={`px-2 py-0.5 text-[10px] font-bold font-mono rounded ${
                    state.position.side === 'LONG'
                      ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/50'
                      : 'bg-red-950/60 text-red-300 border border-red-800/50'
                  }`}
                >
                  {state.position.side} {state.position.qty}
                </span>
              ) : (
                <span className="text-[10px] text-gray-500 font-mono">FLAT</span>
              )}
            </div>

            {state?.position ? (
              <div className="space-y-2.5 pt-1 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-gray-400">Entry Price:</span>
                  <span className="text-gray-200">${state.position.entry_price}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Mark Price:</span>
                  <span className="text-blue-400">${state.position.mark_price}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">Unrealized PnL:</span>
                  <span
                    className={
                      parseFloat(state.position.unrealized_pnl) >= 0
                        ? 'text-emerald-400 font-bold'
                        : 'text-red-400 font-bold'
                    }
                  >
                    ${state.position.unrealized_pnl} ({state.position.unrealized_pnl_pct})
                  </span>
                </div>

                {/* Adjust SL/TP Inputs */}
                <div className="pt-2 border-t border-gray-800 space-y-2">
                  <div>
                    <label className="text-[10px] text-gray-400 block mb-0.5">Stop Loss ($)</label>
                    <input
                      type="number"
                      value={editSl}
                      onChange={(e) => setEditSl(e.target.value)}
                      placeholder="SL price"
                      className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2.5 py-1.5 text-xs font-mono text-red-300 focus:outline-none focus:border-red-500/50"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-gray-400 block mb-0.5">Take Profit ($)</label>
                    <input
                      type="number"
                      value={editTp}
                      onChange={(e) => setEditTp(e.target.value)}
                      placeholder="TP price"
                      className="w-full bg-gray-950 border border-gray-800 rounded-lg px-2.5 py-1.5 text-xs font-mono text-emerald-300 focus:outline-none focus:border-emerald-500/50"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={handleUpdateStops}
                    className="w-full py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg text-xs font-medium transition-colors"
                  >
                    Update Stops
                  </button>
                </div>

                {/* Market Close Button */}
                <button
                  type="button"
                  onClick={handleClosePosition}
                  className="w-full py-2 bg-red-950/60 hover:bg-red-900/60 border border-red-800/50 text-red-200 rounded-xl text-xs font-semibold transition-colors mt-2"
                >
                  Close Position (Market)
                </button>
              </div>
            ) : (
              <div className="py-6 text-center text-xs text-gray-500 border border-dashed border-gray-800/80 rounded-xl">
                No open position. Waiting for robot signal...
              </div>
            )}
          </div>

          {/* Strategy & Risk Settings Card */}
          <div className="bg-[#0d131f] border border-gray-800 p-4 rounded-2xl space-y-3">
            <span className="text-xs font-semibold text-gray-300 block">Session Configuration</span>

            <div className="space-y-2 text-xs">
              <div>
                <label className="text-[10px] text-gray-400 block mb-1">Session name</label>
                <input
                  type="text"
                  value={sessionName}
                  onChange={(e) => setSessionName(e.target.value)}
                  disabled={state?.is_active}
                  placeholder={`${robot}-${symbol.replace('USDT', '').toLowerCase()}`}
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs disabled:opacity-50 text-gray-200 font-mono"
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-400 block mb-1">
                  Hypothesis / stop criterion
                </label>
                <textarea
                  value={sessionNotes}
                  onChange={(e) => setSessionNotes(e.target.value)}
                  disabled={state?.is_active}
                  rows={2}
                  placeholder="e.g. beats hold-eth after fees within 60 days, else rejected"
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs disabled:opacity-50 text-gray-200"
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-400 block mb-1">Trading Robot</label>
                <select
                  value={robot}
                  onChange={(e) => setRobot(e.target.value)}
                  disabled={state?.is_active}
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs disabled:opacity-50 text-gray-200"
                >
                  {supportedRobots.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[10px] text-gray-400 block mb-1">Starting Capital ($)</label>
                <input
                  type="number"
                  value={startingEquity}
                  onChange={(e) => setStartingEquity(e.target.value)}
                  disabled={state?.is_active}
                  className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
                />
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-[10px] text-gray-400 block mb-1">Risk (%)</label>
                  <input
                    type="number"
                    step="0.005"
                    value={riskPct}
                    onChange={(e) => setRiskPct(e.target.value)}
                    disabled={state?.is_active}
                    className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-400 block mb-1">Stop Loss (%)</label>
                  <input
                    type="number"
                    step="0.005"
                    value={stopPct}
                    onChange={(e) => setStopPct(e.target.value)}
                    disabled={state?.is_active}
                    className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-400 block mb-1">TP Multiple</label>
                  <input
                    type="number"
                    step="0.5"
                    value={tpMultiple}
                    onChange={(e) => setTpMultiple(e.target.value)}
                    disabled={state?.is_active}
                    className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
                  />
                </div>
              </div>

              <div className="flex items-center justify-between pt-2">
                <span className="text-xs text-gray-400">Autonomous Execution</span>
                <input
                  type="checkbox"
                  checked={autoTrade}
                  onChange={(e) => setAutoTrade(e.target.checked)}
                  disabled={state?.is_active}
                  className="rounded bg-gray-950 border-gray-800 text-blue-600 focus:ring-0"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Tabs Drawer: Positions, Order History, Risk Breaches */}
      <div className="bg-[#0d131f] border border-gray-800 rounded-2xl overflow-hidden">
        {/* Tab Headers */}
        <div className="flex border-b border-gray-800 bg-gray-950/60 px-4">
          <button
            type="button"
            onClick={() => setActiveBottomTab('position')}
            className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
              activeBottomTab === 'position'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            Position Details {state?.position ? '(1)' : '(0)'}
          </button>
          <button
            type="button"
            onClick={() => setActiveBottomTab('fills')}
            className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
              activeBottomTab === 'fills'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            Order Fills History ({state?.fills.length || 0})
          </button>
          <button
            type="button"
            onClick={() => setActiveBottomTab('risk')}
            className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
              activeBottomTab === 'risk'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            Equity Trajectory & Risk
          </button>
          <button
            type="button"
            onClick={() => setActiveBottomTab('decision_logs')}
            className={`px-4 py-3 text-xs font-semibold border-b-2 transition-colors ${
              activeBottomTab === 'decision_logs'
                ? 'border-purple-500 text-purple-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            Decision Logs
          </button>
        </div>

        {/* Tab Contents */}
        <div className="p-4">
          {activeBottomTab === 'position' && (
            <div>
              {state?.position ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs font-mono">
                    <thead className="text-[11px] text-gray-500 border-b border-gray-800">
                      <tr>
                        <th className="pb-2">Instrument</th>
                        <th className="pb-2">Side</th>
                        <th className="pb-2">Qty</th>
                        <th className="pb-2">Entry Price</th>
                        <th className="pb-2">Mark Price</th>
                        <th className="pb-2">Stop Loss</th>
                        <th className="pb-2">Take Profit</th>
                        <th className="pb-2">Floating PnL</th>
                        <th className="pb-2">Entry Time</th>
                      </tr>
                    </thead>
                    <tbody className="text-gray-300">
                      <tr className="border-t border-gray-800/40">
                        <td className="py-2.5 font-bold text-white">{state.position.symbol}</td>
                        <td
                          className={`py-2.5 font-bold ${
                            state.position.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'
                          }`}
                        >
                          {state.position.side}
                        </td>
                        <td className="py-2.5">{state.position.qty}</td>
                        <td className="py-2.5">${state.position.entry_price}</td>
                        <td className="py-2.5 text-blue-400">${state.position.mark_price}</td>
                        <td className="py-2.5 text-red-400">
                          {state.position.stop_loss ? `$${state.position.stop_loss}` : '—'}
                        </td>
                        <td className="py-2.5 text-emerald-400">
                          {state.position.take_profit ? `$${state.position.take_profit}` : '—'}
                        </td>
                        <td
                          className={`py-2.5 font-bold ${
                            parseFloat(state.position.unrealized_pnl) >= 0
                              ? 'text-emerald-400'
                              : 'text-red-400'
                          }`}
                        >
                          ${state.position.unrealized_pnl} ({state.position.unrealized_pnl_pct})
                        </td>
                        <td className="py-2.5 text-gray-400">{state.position.entry_time}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-gray-500">
                  No active position. The session is currently FLAT.
                </div>
              )}
            </div>
          )}

          {activeBottomTab === 'fills' && (
            <div>
              {state?.fills && state.fills.length > 0 ? (
                <div className="overflow-x-auto max-h-60">
                  <table className="w-full text-left text-xs font-mono">
                    <thead className="text-[11px] text-gray-500 border-b border-gray-800 sticky top-0 bg-[#0d131f]">
                      <tr>
                        <th className="pb-2">Time (UTC)</th>
                        <th className="pb-2">Symbol</th>
                        <th className="pb-2">Side</th>
                        <th className="pb-2 text-right">Qty</th>
                        <th className="pb-2 text-right">Price</th>
                        <th className="pb-2 text-right">Fee</th>
                        <th className="pb-2 text-right">Realized PnL</th>
                        <th className="pb-2 pl-4">Reason / Trigger</th>
                      </tr>
                    </thead>
                    <tbody className="text-gray-300 divide-y divide-gray-800/40">
                      {state.fills.map((fill) => (
                        <tr key={fill.id} className="hover:bg-gray-800/20">
                          <td className="py-2 text-gray-400 whitespace-nowrap">{fill.ts}</td>
                          <td className="py-2 font-semibold text-gray-200">{fill.symbol}</td>
                          <td
                            className={`py-2 font-bold ${
                              fill.side === 'BUY' ? 'text-emerald-400' : 'text-red-400'
                            }`}
                          >
                            {fill.side}
                          </td>
                          <td className="py-2 text-right">{fill.qty}</td>
                          <td className="py-2 text-right font-medium">${fill.price}</td>
                          <td className="py-2 text-right text-gray-400">${fill.fee}</td>
                          <td
                            className={`py-2 text-right font-bold ${
                              parseFloat(fill.realized_pnl) > 0
                                ? 'text-emerald-400'
                                : parseFloat(fill.realized_pnl) < 0
                                  ? 'text-red-400'
                                  : 'text-gray-400'
                            }`}
                          >
                            {fill.realized_pnl !== '0.00' ? `$${fill.realized_pnl}` : '—'}
                          </td>
                          <td className="py-2 pl-4 text-gray-400">{fill.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="py-8 text-center text-xs text-gray-500">
                  No orders have been filled in this session yet.
                </div>
              )}
            </div>
          )}

          {activeBottomTab === 'risk' && (
            <div className="space-y-4">
              <div className="text-xs text-gray-400">
                Equity snapshots recorded upon bar closes. Total snapshots:{' '}
                <span className="font-mono text-gray-200">
                  {state?.equity_history.length || 0}
                </span>
              </div>
              {state?.equity_history && state.equity_history.length > 0 ? (
                <div className="overflow-x-auto max-h-52">
                  <table className="w-full text-left text-xs font-mono">
                    <thead className="text-[11px] text-gray-500 border-b border-gray-800">
                      <tr>
                        <th className="pb-2">Time (Epoch)</th>
                        <th className="pb-2">Equity</th>
                        <th className="pb-2">Realized PnL</th>
                        <th className="pb-2">Unrealized PnL</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800/40 text-gray-300">
                      {state.equity_history.slice(-10).map((pt, idx) => (
                        <tr key={`${pt.time}-${idx}`}>
                          <td className="py-1.5 text-gray-400">
                            {new Date(pt.time * 1000).toLocaleTimeString()}
                          </td>
                          <td className="py-1.5 font-bold text-gray-100">
                            ${pt.equity.toFixed(2)}
                          </td>
                          <td className="py-1.5 text-emerald-400">
                            ${pt.realized_pnl.toFixed(2)}
                          </td>
                          <td className="py-1.5 text-blue-400">
                            ${pt.unrealized_pnl.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="py-6 text-center text-xs text-gray-500">
                  Awaiting the first closed bar to record equity curve snapshots.
                </div>
              )}
            </div>
          )}

          {activeBottomTab === 'decision_logs' && sessionId && (
            <div className="p-4">
              <DecisionLogPanel sessionId={sessionId} />
            </div>
          )}
        </div>
      </div>

      {/* Safety Modal for Live Trading confirmation */}
      {showLiveWarningModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#0f172a] border border-red-500/40 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center gap-3 text-red-400">
              <ShieldAlert className="w-7 h-7" />
              <h3 className="text-lg font-bold text-white">Live Trading Mode (Guarded)</h3>
            </div>

            <p className="text-xs text-gray-300 leading-relaxed">
              You are switching to <strong>Live Trading Mode</strong>. In Nautilus Lab, real exchange
              order routing is intentionally <strong>fail-closed</strong> (`lab live` exits with code 1
              by design).
            </p>

            <div className="p-3 bg-red-950/40 border border-red-900/60 rounded-xl text-xs text-red-200">
              This terminal will stream live Binance market data and show where orders would trigger,
              but <strong>no actual funds will be risked</strong> on any exchange.
            </div>

            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setMode('live_guarded');
                  setShowLiveWarningModal(false);
                }}
                className="flex-1 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl text-xs font-bold transition-colors"
              >
                Acknowledge & Proceed
              </button>
              <button
                type="button"
                onClick={() => setShowLiveWarningModal(false)}
                className="px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl text-xs font-semibold transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
