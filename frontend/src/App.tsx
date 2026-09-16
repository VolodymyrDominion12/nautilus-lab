import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import {
  Activity,
  Layers,
  Database,
  Cpu,
  ShieldAlert,
  ShieldCheck,
  BarChart2,
  TrendingUp,
} from 'lucide-react';
import { fetchStatus, fetchStrategies } from './services/api';
import type { StatusResponse, StrategySpec } from './services/api';
import { ResearchLab } from './components/ResearchLab';
import { CatalogManager } from './components/CatalogManager';
import { StrategyCatalog } from './components/StrategyCatalog';

const ChartComponent = ({ symbol = 'ETHUSDT', interval = '1m' }: { symbol?: string; interval?: string }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const candlestickSeriesRef = useRef<any>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (chartContainerRef.current) {
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: '#0b0f19' },
          textColor: '#9CA3AF',
        },
        grid: {
          vertLines: { color: '#182030' },
          horzLines: { color: '#182030' },
        },
        width: chartContainerRef.current.clientWidth,
        height: 320,
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
        },
      });

      const handleResize = () => {
        chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
      };

      candlestickSeriesRef.current = chart.addSeries(CandlestickSeries, {
        upColor: '#10B981',
        downColor: '#EF4444',
        borderVisible: false,
        wickUpColor: '#10B981',
        wickDownColor: '#EF4444',
      });

      // Fetch historical data from Binance public API
      fetch(`https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=100`)
        .then((res) => res.json())
        .then((data) => {
          if (Array.isArray(data)) {
            const historicalData = data.map((d: any) => ({
              time: d[0] / 1000,
              open: parseFloat(d[1]),
              high: parseFloat(d[2]),
              low: parseFloat(d[3]),
              close: parseFloat(d[4]),
            }));
            candlestickSeriesRef.current.setData(historicalData);
          }
        })
        .catch((err) => console.error('Klines fetch error:', err));

      // Connect WebSocket for real-time updates
      const wsUrl = `wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@kline_${interval}`;
      wsRef.current = new WebSocket(wsUrl);

      wsRef.current.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.e === 'kline') {
            const kline = message.k;
            candlestickSeriesRef.current.update({
              time: kline.t / 1000,
              open: parseFloat(kline.o),
              high: parseFloat(kline.h),
              low: parseFloat(kline.l),
              close: parseFloat(kline.c),
            });
          }
        } catch (e) {
          // ignore stream parse errors
        }
      };

      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        if (wsRef.current) wsRef.current.close();
        chart.remove();
      };
    }
  }, [symbol, interval]);

  return <div ref={chartContainerRef} className="w-full h-full" />;
};

const SettingsTab = () => {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetch('http://localhost:8000/api/settings')
      .then((res) => res.json())
      .then((data) => setSettings(data.settings || {}))
      .catch((err) => console.error(err));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      const res = await fetch('http://localhost:8000/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      });
      if (res.ok) {
        setMessage('Settings saved successfully.');
      } else {
        setMessage('Error saving settings.');
      }
    } catch (err) {
      setMessage('Network error.');
    }
    setSaving(false);
  };

  const handleChange = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="bg-gray-900 rounded-2xl border border-gray-800 p-6 flex flex-col gap-4">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-xl font-bold text-gray-100">Environment Configuration (.env)</h2>
            <p className="text-gray-400 text-xs mt-1">
              Configure risk thresholds, fee schedules, catalog parameters, and robot hyperparameter defaults.
            </p>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 text-white rounded-xl text-sm font-medium transition-colors"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>

        {message && (
          <div
            className={`p-3 rounded-xl border text-xs ${
              message.includes('success')
                ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/50'
                : 'bg-red-950/40 text-red-400 border-red-800/50'
            }`}
          >
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-2">
          {Object.entries(settings).map(([key, value]) => (
            <div key={key} className="flex flex-col gap-1.5">
              <label className="text-[11px] font-mono text-gray-400">{key}</label>
              <input
                type="text"
                value={value}
                onChange={(e) => handleChange(key, e.target.value)}
                className="bg-gray-950 border border-gray-800 text-gray-100 text-xs rounded-xl focus:border-blue-500 focus:outline-none p-2.5 font-mono"
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'research' | 'catalog' | 'strategies' | 'settings'>('research');
  const [, setStatus] = useState<StatusResponse | null>(null);
  const [strategies, setStrategies] = useState<StrategySpec[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState('ETHUSDT');

  useEffect(() => {
    fetchStatus()
      .then((data) => setStatus(data))
      .catch((err) => console.error(err));

    fetchStrategies()
      .then((data) => setStrategies(data.strategies))
      .catch((err) => console.error(err));
  }, []);

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#080c14] text-gray-100 font-sans">
      {/* Sidebar */}
      <aside className="w-full md:w-64 bg-[#0d131f] border-r border-gray-800/80 p-5 flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-600/10 border border-blue-500/20 rounded-xl">
            <Activity className="text-blue-400 w-6 h-6" />
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-gray-100">Nautilus Lab</h1>
            <span className="text-[10px] font-mono text-gray-400 block">Research-First Engine</span>
          </div>
        </div>

        <nav className="flex flex-col gap-1.5">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'dashboard'
                ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
                : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
            }`}
          >
            <BarChart2 className="w-4 h-4" /> Market Dashboard
          </button>

          <button
            onClick={() => setActiveTab('research')}
            className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'research'
                ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
                : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
            }`}
          >
            <Layers className="w-4 h-4" /> Research & Backtest
          </button>

          <button
            onClick={() => setActiveTab('catalog')}
            className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'catalog'
                ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
                : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
            }`}
          >
            <Database className="w-4 h-4" /> Parquet Catalog
          </button>

          <button
            onClick={() => setActiveTab('strategies')}
            className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'strategies'
                ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
                : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
            }`}
          >
            <Cpu className="w-4 h-4" /> Strategy Specs
          </button>

          <button
            onClick={() => setActiveTab('settings')}
            className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              activeTab === 'settings'
                ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
                : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
            }`}
          >
            <ShieldAlert className="w-4 h-4" /> Settings
          </button>
        </nav>

        {/* Live Safety Indicator */}
        <div className="mt-auto p-3.5 bg-gray-950/80 border border-gray-800 rounded-2xl flex flex-col gap-2">
          <div className="flex items-center gap-2 text-emerald-400 text-xs font-semibold">
            <ShieldCheck className="w-4 h-4" />
            <span>Safety: Fail-Closed</span>
          </div>
          <p className="text-[11px] text-gray-400 leading-tight">
            Live execution is intentionally disabled. Simulation & walk-forward research only.
          </p>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 p-6 md:p-8 flex flex-col gap-6 overflow-y-auto max-h-screen">
        {activeTab === 'dashboard' ? (
          <div className="flex flex-col gap-6">
            {/* Top Stat Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs text-gray-400 font-medium">Parquet Instruments</span>
                <span className="text-2xl font-bold text-gray-100 font-mono">2 Pairs</span>
                <span className="text-[11px] text-gray-500 mt-1">BTCUSDT & ETHUSDT (32k bars each)</span>
              </div>
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs text-gray-400 font-medium">Available Strategies</span>
                <span className="text-2xl font-bold text-blue-400 font-mono">
                  {strategies.length > 0 ? strategies.length : '9'} Specs
                </span>
                <span className="text-[11px] text-gray-500 mt-1">5 Wired for Backtest Engine</span>
              </div>
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs text-gray-400 font-medium">Research Protocol</span>
                <span className="text-2xl font-bold text-emerald-400 font-mono">Walk-Forward</span>
                <span className="text-[11px] text-gray-500 mt-1">OOS vs Buy&Hold Validation</span>
              </div>
            </div>

            {/* Live Chart Section */}
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
              <div className="flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <TrendingUp className="w-5 h-5 text-emerald-400" />
                  <h2 className="text-base font-bold text-gray-100">Live Binance Market Stream</h2>
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={selectedSymbol}
                    onChange={(e) => setSelectedSymbol(e.target.value)}
                    className="bg-gray-950 border border-gray-800 text-xs text-gray-200 rounded-xl px-3 py-1.5 focus:outline-none font-mono"
                  >
                    <option value="ETHUSDT">ETH/USDT</option>
                    <option value="BTCUSDT">BTC/USDT</option>
                    <option value="SOLUSDT">SOL/USDT</option>
                  </select>
                  <span className="px-2 py-1 bg-emerald-950/50 text-emerald-400 border border-emerald-800/40 text-[11px] font-mono rounded-lg">
                    1m real-time
                  </span>
                </div>
              </div>

              <div className="h-[320px] w-full rounded-xl overflow-hidden bg-gray-950">
                <ChartComponent symbol={selectedSymbol} />
              </div>
            </div>
          </div>
        ) : activeTab === 'research' ? (
          <ResearchLab strategies={strategies} />
        ) : activeTab === 'catalog' ? (
          <CatalogManager />
        ) : activeTab === 'strategies' ? (
          <StrategyCatalog
            strategies={strategies}
            onSelectStrategy={() => setActiveTab('research')}
          />
        ) : (
          <SettingsTab />
        )}
      </main>
    </div>
  );
}

export default App;
