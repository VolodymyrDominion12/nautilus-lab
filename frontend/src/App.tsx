import { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import { Activity, Play, StopCircle, RefreshCw, BarChart2, ShieldAlert } from 'lucide-react';

const ChartComponent = () => {
  const chartContainerRef = useRef<HTMLDivElement>(null);

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
      });

      const candlestickSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#10B981',
        downColor: '#EF4444',
        borderVisible: false,
        wickUpColor: '#10B981',
        wickDownColor: '#EF4444',
      });

      // Sample data
      const data = [
        { time: '2018-12-22', open: 75.16, high: 82.84, low: 36.16, close: 45.72 },
        { time: '2018-12-23', open: 45.12, high: 53.90, low: 45.12, close: 48.09 },
        { time: '2018-12-24', open: 60.71, high: 60.71, low: 53.39, close: 59.29 },
        { time: '2018-12-25', open: 68.26, high: 68.26, low: 59.04, close: 60.50 },
        { time: '2018-12-26', open: 67.71, high: 105.85, low: 66.67, close: 91.04 },
        { time: '2018-12-27', open: 91.04, high: 121.40, low: 82.70, close: 111.40 },
        { time: '2018-12-28', open: 111.51, high: 142.83, low: 103.34, close: 131.25 },
        { time: '2018-12-29', open: 131.33, high: 151.17, low: 77.68, close: 96.43 },
        { time: '2018-12-30', open: 106.33, high: 110.20, low: 90.39, close: 98.10 },
        { time: '2018-12-31', open: 109.87, high: 114.69, low: 85.66, close: 111.26 },
      ];
      
      candlestickSeries.setData(data);

      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        chart.remove();
      };
    }
  }, []);

  return <div ref={chartContainerRef} className="w-full h-full" />;
};

function App() {
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    // In a real app, this would fetch from http://localhost:8000/api/status
    setStatus({
        active_bots: 2,
        strategies_available: ["regime", "ema", "pairs"],
        is_live: false
    });
  }, []);

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-gray-950 text-gray-100 font-sans">
      {/* Sidebar */}
      <aside className="w-full md:w-64 bg-gray-900 border-r border-gray-800 p-4 flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <Activity className="text-blue-500 w-8 h-8" />
          <h1 className="text-xl font-bold tracking-tight">Nautilus Lab</h1>
        </div>
        
        <nav className="flex flex-col gap-2">
          <a href="#" className="flex items-center gap-3 px-3 py-2 rounded-md bg-blue-900/20 text-blue-400 font-medium">
            <BarChart2 className="w-5 h-5" /> Dashboard
          </a>
          <a href="#" className="flex items-center gap-3 px-3 py-2 rounded-md hover:bg-gray-800 transition-colors text-gray-400 hover:text-gray-200 font-medium">
            <RefreshCw className="w-5 h-5" /> Backtests
          </a>
          <a href="#" className="flex items-center gap-3 px-3 py-2 rounded-md hover:bg-gray-800 transition-colors text-gray-400 hover:text-gray-200 font-medium">
            <ShieldAlert className="w-5 h-5" /> Settings
          </a>
        </nav>

        <div className="mt-auto">
            <button className="w-full py-2 bg-red-600/10 text-red-500 border border-red-900/50 hover:bg-red-600/20 rounded-md font-semibold transition-colors flex items-center justify-center gap-2">
                <StopCircle className="w-5 h-5" /> KILL SWITCH
            </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 p-6 flex flex-col gap-6 overflow-y-auto">
        
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
                <h2 className="text-lg font-semibold">ETH/USDT - 1h (Regime Strategy)</h2>
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

      </main>
    </div>
  );
}

export default App;
