import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import { Activity, Play, StopCircle, RefreshCw, BarChart2, ShieldAlert } from 'lucide-react';

const ChartComponent = ({ symbol = 'ETHUSDT', interval = '1m' }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const candlestickSeriesRef = useRef<any>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (chartContainerRef.current) {
      const handleResize = () => {
        chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
      };

      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: '#111827' },
          textColor: '#9CA3AF',
        },
        grid: {
          vertLines: { color: '#1F2937' },
          horzLines: { color: '#1F2937' },
        },
        width: chartContainerRef.current.clientWidth,
        height: 300,
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
        },
      });

      candlestickSeriesRef.current = chart.addSeries(CandlestickSeries, {
        upColor: '#10B981',
        downColor: '#EF4444',
        borderVisible: false,
        wickUpColor: '#10B981',
        wickDownColor: '#EF4444',
      });

      // Fetch historical data
      fetch(`https://api.binance.com/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=100`)
        .then(res => res.json())
        .then(data => {
          const historicalData = data.map((d: any) => ({
            time: d[0] / 1000,
            open: parseFloat(d[1]),
            high: parseFloat(d[2]),
            low: parseFloat(d[3]),
            close: parseFloat(d[4]),
          }));
          candlestickSeriesRef.current.setData(historicalData);
        });

      // Connect WebSocket for real-time updates
      const wsUrl = `wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@kline_${interval}`;
      wsRef.current = new WebSocket(wsUrl);

      wsRef.current.onmessage = (event) => {
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

const ResearchTab = ({ strategies, onRun, running, output }: any) => {
  const [selectedRobot, setSelectedRobot] = useState(strategies[0] || 'regime');
  const [bars, setBars] = useState(3000);
  const [reports, setReports] = useState<any[]>([]);

  useEffect(() => {
    const fetchReports = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/reports');
        const data = await response.json();
        setReports(data.reports || []);
      } catch (err) {
        console.error("Failed to fetch reports", err);
      }
    };
    fetchReports();
    // Refresh reports every 5 seconds
    const interval = setInterval(fetchReports, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 flex flex-col gap-4">
        <h2 className="text-xl font-bold text-gray-100">Lab Research (Walk-Forward / Smoke Tests)</h2>
        <p className="text-gray-400 text-sm">
          Run backtests or smoke tests. For this UI prototype, it runs with `--synthetic` to ensure it executes quickly.
        </p>
        
        <div className="flex flex-col md:flex-row gap-4 items-end mt-4">
          <div className="flex flex-col gap-2 flex-1">
            <label className="text-sm font-medium text-gray-300">Strategy (Robot)</label>
            <select 
              value={selectedRobot}
              onChange={(e) => setSelectedRobot(e.target.value)}
              className="bg-gray-950 border border-gray-700 text-gray-100 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5"
            >
              {strategies.map((s: string) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          
          <div className="flex flex-col gap-2 flex-1">
            <label className="text-sm font-medium text-gray-300">Bars (Length)</label>
            <input 
              type="number" 
              value={bars}
              onChange={(e) => setBars(Number(e.target.value))}
              className="bg-gray-950 border border-gray-700 text-gray-100 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5" 
            />
          </div>

          <button 
            onClick={() => onRun(selectedRobot, bars)}
            disabled={running}
            className="w-full md:w-auto px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
          >
            {running ? <RefreshCw className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
            {running ? 'Running...' : 'Run Research'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Terminal Output */}
        <div className="bg-[#0c0c0c] rounded-xl border border-gray-800 flex flex-col overflow-hidden h-[400px]">
          <div className="bg-gray-800 px-4 py-2 border-b border-gray-700 flex justify-between items-center">
            <span className="text-xs font-mono text-gray-300">Terminal Output</span>
          </div>
          <div className="p-4 flex-1 overflow-y-auto font-mono text-sm text-green-400 whitespace-pre-wrap">
            {output || 'Ready to run research...\n'}
          </div>
        </div>

        {/* Generated Reports */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 flex flex-col gap-4 h-[400px]">
            <h2 className="text-xl font-bold text-gray-100 mb-2">Generated Tearsheets</h2>
            {reports.length === 0 ? (
                <div className="flex-1 flex items-center justify-center text-gray-500 text-sm">
                    No reports generated yet. Run a backtest that generates an HTML tearsheet.
                </div>
            ) : (
                <ul className="flex flex-col gap-2 overflow-y-auto pr-2">
                    {reports.map((report, idx) => (
                        <li key={idx}>
                            <a 
                                href={`http://localhost:8000${report.url}`} 
                                target="_blank" 
                                rel="noreferrer"
                                className="block p-3 bg-gray-950 border border-gray-800 hover:border-blue-500/50 rounded-lg transition-colors text-blue-400 hover:text-blue-300 text-sm"
                            >
                                📄 {report.filename}
                            </a>
                        </li>
                    ))}
                </ul>
            )}
        </div>
      </div>
    </div>
  );
};

const SettingsTab = () => {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    fetch('http://localhost:8000/api/settings')
      .then(res => res.json())
      .then(data => setSettings(data.settings || {}))
      .catch(err => console.error(err));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      const res = await fetch('http://localhost:8000/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings })
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
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 flex flex-col gap-4">
        <div className="flex justify-between items-center">
            <div>
                <h2 className="text-xl font-bold text-gray-100">Environment Settings (.env)</h2>
                <p className="text-gray-400 text-sm">Configure robots, risk limits, API keys, and more.</p>
            </div>
            <button 
                onClick={handleSave} 
                disabled={saving}
                className="px-6 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white rounded-lg font-medium transition-colors"
            >
                {saving ? 'Saving...' : 'Save Changes'}
            </button>
        </div>
        
        {message && (
            <div className={`p-3 rounded border text-sm ${message.includes('success') ? 'bg-green-900/20 text-green-400 border-green-900/50' : 'bg-red-900/20 text-red-400 border-red-900/50'}`}>
                {message}
            </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
            {Object.entries(settings).map(([key, value]) => (
                <div key={key} className="flex flex-col gap-1.5">
                    <label className="text-xs font-mono text-gray-400">{key}</label>
                    <input 
                        type="text" 
                        value={value} 
                        onChange={(e) => handleChange(key, e.target.value)}
                        className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5 font-mono"
                    />
                </div>
            ))}
        </div>
      </div>
    </div>
  );
};

function App() {
  const [status, setStatus] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'dashboard' | 'research' | 'settings'>('dashboard');
  
  // Research State
  const [isRunning, setIsRunning] = useState(false);
  const [researchOutput, setResearchOutput] = useState('');

  useEffect(() => {
    // In a real app, this would fetch from http://localhost:8000/api/status
    setStatus({
        active_bots: 2,
        strategies_available: ["regime", "ema", "pairs"],
        is_live: false
    });
  }, []);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (isRunning) {
      interval = setInterval(async () => {
        try {
          const res = await fetch('http://localhost:8000/api/research/log');
          const data = await res.json();
          if (data.log) {
            setResearchOutput(data.log);
            if (data.log.includes('Process finished with code') || data.log.includes('Exception occurred:')) {
              setIsRunning(false);
            }
          }
        } catch (err) {
          console.error("Failed to fetch log", err);
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isRunning]);

  const handleRunResearch = async (robot: string, bars: number) => {
    setIsRunning(true);
    setResearchOutput(`Running: lab research --robot ${robot} --synthetic --bars ${bars}\n\n`);
    
    try {
      await fetch(`http://localhost:8000/api/research?robot=${robot}&bars=${bars}`, {
        method: 'POST'
      });
    } catch (err: any) {
      setResearchOutput(prev => prev + `\nNetwork Error: ${err.message}`);
      setIsRunning(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-gray-950 text-gray-100 font-sans">
      {/* Sidebar */}
      <aside className="w-full md:w-64 bg-gray-900 border-r border-gray-800 p-4 flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <Activity className="text-blue-500 w-8 h-8" />
          <h1 className="text-xl font-bold tracking-tight">Nautilus Lab</h1>
        </div>
        
        <nav className="flex flex-col gap-2">
          <button 
            onClick={() => setActiveTab('dashboard')}
            className={`flex items-center gap-3 px-3 py-2 rounded-md font-medium transition-colors ${activeTab === 'dashboard' ? 'bg-blue-900/20 text-blue-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'}`}
          >
            <BarChart2 className="w-5 h-5" /> Dashboard
          </button>
          <button 
            onClick={() => setActiveTab('research')}
            className={`flex items-center gap-3 px-3 py-2 rounded-md font-medium transition-colors ${activeTab === 'research' ? 'bg-blue-900/20 text-blue-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'}`}
          >
            <RefreshCw className="w-5 h-5" /> Backtests
          </button>
          <button 
            onClick={() => setActiveTab('settings')}
            className={`flex items-center gap-3 px-3 py-2 rounded-md transition-colors font-medium ${activeTab === 'settings' ? 'bg-blue-900/20 text-blue-400' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'}`}
          >
            <ShieldAlert className="w-5 h-5" /> Settings
          </button>
        </nav>

        <div className="mt-auto">
            <button className="w-full py-2 bg-red-600/10 text-red-500 border border-red-900/50 hover:bg-red-600/20 rounded-md font-semibold transition-colors flex items-center justify-center gap-2">
                <StopCircle className="w-5 h-5" /> KILL SWITCH
            </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 p-6 flex flex-col gap-6 overflow-y-auto">
        {activeTab === 'dashboard' ? (
          <>
            {/* Top Stats */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 flex flex-col gap-1">
                <span className="text-sm text-gray-400">Total PnL (Paper)</span>
                <span className="text-2xl font-bold text-green-400">+$1,240.50</span>
              </div>
              <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 flex flex-col gap-1">
                <span className="text-sm text-gray-400">Active Bots</span>
                <span className="text-2xl font-bold">{status?.active_bots || 0}</span>
              </div>
              <div className="bg-gray-900 p-4 rounded-xl border border-gray-800 flex flex-col gap-1">
                <span className="text-sm text-gray-400">System Mode</span>
                <span className="text-2xl font-bold text-yellow-500">Research / Paper</span>
              </div>
            </div>

            {/* Charts Area */}
            <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 h-[350px] flex flex-col">
                <div className="flex justify-between items-center mb-4">
                    <h2 className="text-lg font-semibold">ETH/USDT - 1m (Live)</h2>
                    <div className="flex gap-2">
                        <span className="px-2 py-1 bg-green-900/30 text-green-400 text-xs rounded border border-green-900/50">LONG</span>
                    </div>
                </div>
                <div className="flex-1 w-full">
                    <ChartComponent />
                </div>
            </div>

            {/* Active Bots Table */}
            <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
                <div className="p-4 border-b border-gray-800">
                    <h2 className="text-lg font-semibold">Active Robots</h2>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead className="bg-gray-950/50 text-gray-400">
                            <tr>
                                <th className="px-4 py-3 font-medium">Name</th>
                                <th className="px-4 py-3 font-medium">Strategy</th>
                                <th className="px-4 py-3 font-medium">Status</th>
                                <th className="px-4 py-3 font-medium">PnL</th>
                                <th className="px-4 py-3 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-800">
                            <tr>
                                <td className="px-4 py-3 font-medium">ETH_Regime_1h</td>
                                <td className="px-4 py-3 text-gray-400">regime</td>
                                <td className="px-4 py-3">
                                    <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-green-500/10 text-green-400 border border-green-500/20">
                                        <span className="w-1.5 h-1.5 rounded-full bg-green-500"></span>
                                        Running
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-green-400">+$45.20</td>
                                <td className="px-4 py-3 text-right">
                                    <button className="text-red-400 hover:text-red-300">Stop</button>
                                </td>
                            </tr>
                            <tr>
                                <td className="px-4 py-3 font-medium">BTC_Pairs_15m</td>
                                <td className="px-4 py-3 text-gray-400">pairs</td>
                                <td className="px-4 py-3">
                                    <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium bg-gray-500/10 text-gray-400 border border-gray-500/20">
                                        <span className="w-1.5 h-1.5 rounded-full bg-gray-500"></span>
                                        Stopped
                                    </span>
                                </td>
                                <td className="px-4 py-3 text-gray-500">$0.00</td>
                                <td className="px-4 py-3 text-right">
                                    <button className="text-blue-400 hover:text-blue-300 flex items-center gap-1 ml-auto">
                                        <Play className="w-4 h-4" /> Start
                                    </button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
          </>
        ) : activeTab === 'research' ? (
          <ResearchTab 
            strategies={status?.strategies_available || []} 
            onRun={handleRunResearch}
            running={isRunning}
            output={researchOutput}
          />
        ) : (
          <SettingsTab />
        )}
      </main>
    </div>
  );
}

export default App;
