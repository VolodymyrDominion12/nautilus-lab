import React, { useEffect, useState } from 'react';
import {
  Play,
  RefreshCw,
  FileText,
  AlertTriangle,
  Layers,
  Terminal,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  fetchResearchLog,
  fetchReports,
  runResearch,
} from '../services/api';
import type {
  ReportItem,
  ResearchSummary,
  StrategySpec,
} from '../services/api';

interface ResearchLabProps {
  strategies: StrategySpec[];
}

export const ResearchLab: React.FC<ResearchLabProps> = ({ strategies }) => {
  // Config form state
  const [robot, setRobot] = useState('regime');
  const [source, setSource] = useState<'catalog' | 'synthetic'>('catalog');
  const [bars, setBars] = useState(3000);
  const [folds, setFolds] = useState(2);
  const [isFraction, setIsFraction] = useState(0.7);
  const [embargoBars, setEmbargoBars] = useState<number | undefined>(undefined);
  const [useOptuna, setUseOptuna] = useState(false);
  const [optunaTrials, setOptunaTrials] = useState(20);
  const [usePbo, setUsePbo] = useState(false);
  const [pboBlocks, setPboBlocks] = useState(8);
  const [barVpin, setBarVpin] = useState(false);
  const [stressSlice, setStressSlice] = useState<string>('');
  const [generateTearsheet, setGenerateTearsheet] = useState(true);
  const [journal, setJournal] = useState(false);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState('');
  const [summary, setSummary] = useState<ResearchSummary | null>(null);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [selectedTearsheetUrl, setSelectedTearsheetUrl] = useState<string | null>(null);

  // Load existing reports
  const loadReports = async () => {
    try {
      const data = await fetchReports();
      setReports(data.reports);
      if (data.reports.length > 0 && !selectedTearsheetUrl) {
        setSelectedTearsheetUrl(data.reports[0].url);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadReports();
  }, []);

  // Poll research log
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (running) {
      interval = setInterval(async () => {
        try {
          const res = await fetchResearchLog();
          setLog(res.log);
          setSummary(res.summary);

          if (res.summary.tearsheet_url) {
            setSelectedTearsheetUrl(res.summary.tearsheet_url);
          }

          if (!res.is_running && res.summary.is_finished) {
            setRunning(false);
            loadReports();
          }
        } catch (err) {
          console.error(err);
        }
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [running]);

  const handleRun = async () => {
    setRunning(true);
    setLog(`Starting research for ${robot} (${source} mode)...\n`);
    try {
      await runResearch({
        robot,
        source,
        bars: source === 'synthetic' ? bars : undefined,
        folds: source === 'catalog' ? folds : undefined,
        is_fraction: source === 'catalog' ? isFraction : undefined,
        embargo_bars: embargoBars,
        use_optuna: useOptuna,
        optuna_trials: useOptuna ? optunaTrials : undefined,
        pbo: usePbo,
        pbo_blocks: usePbo ? pboBlocks : undefined,
        bar_vpin: barVpin,
        stress_slice: stressSlice ? stressSlice : undefined,
        generate_tearsheet: generateTearsheet,
        journal,
      });
    } catch (err: any) {
      setRunning(false);
      setLog((prev) => prev + `\nError starting research: ${err.message}`);
    }
  };

  const selectedStrategyInfo = strategies.find((s) => s.name === robot);

  return (
    <div className="flex flex-col gap-6">
      {/* Top Warning Banner if synthetic */}
      {source === 'synthetic' && (
        <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl flex items-center gap-3 text-amber-300 text-xs font-medium">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>
            Synthetic bars are for smoke tests only and may generate +3000% artifacts. Real research must use Parquet Catalog with Walk-Forward folds.
          </span>
        </div>
      )}

      {/* Configuration Grid */}
      <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
              <Layers className="w-5 h-5 text-blue-400" />
              Research Lab (Walk-Forward & Backtesting)
            </h2>
            <p className="text-xs text-gray-400 mt-1">
              Test strategies with strictly separated In-Sample parameter fitting and Out-Of-Sample reporting.
            </p>
          </div>

          <div className="flex items-center gap-2 bg-gray-950 p-1 border border-gray-800 rounded-xl">
            <button
              onClick={() => setSource('catalog')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                source === 'catalog'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Parquet Catalog (Real)
            </button>
            <button
              onClick={() => setSource('synthetic')}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                source === 'synthetic'
                  ? 'bg-amber-600 text-white shadow-sm'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Synthetic (Smoke)
            </button>
          </div>
        </div>

        {/* Primary Controls */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-gray-300">Robot (Strategy)</label>
            <select
              value={robot}
              onChange={(e) => setRobot(e.target.value)}
              className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none"
            >
              {strategies.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} {s.wired_in_backtest ? '✓' : '(fail-closed)'}
                </option>
              ))}
            </select>
          </div>

          {source === 'catalog' ? (
            <>
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium text-gray-300">
                  Walk-Forward Folds ({folds} folds)
                </label>
                <select
                  value={folds}
                  onChange={(e) => setFolds(Number(e.target.value))}
                  className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono"
                >
                  <option value={1}>1 Fold (Single Anchor)</option>
                  <option value={2}>2 Folds (Multi-Window Recommended)</option>
                  <option value={4}>4 Folds (Quarterly Windows)</option>
                  <option value={8}>8 Folds (Deep Stress)</option>
                </select>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium text-gray-300">
                  In-Sample Fraction ({(isFraction * 100).toFixed(0)}% IS / {((1 - isFraction) * 100).toFixed(0)}% OOS)
                </label>
                <input
                  type="number"
                  step="0.05"
                  min="0.4"
                  max="0.9"
                  value={isFraction}
                  onChange={(e) => setIsFraction(Number(e.target.value))}
                  className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono"
                />
              </div>
            </>
          ) : (
            <div className="flex flex-col gap-1.5 md:col-span-2">
              <label className="text-xs font-medium text-gray-300">Bars Count (Length)</label>
              <input
                type="number"
                value={bars}
                onChange={(e) => setBars(Number(e.target.value))}
                className="bg-gray-950 border border-gray-800 text-gray-100 text-sm rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono"
              />
            </div>
          )}

          <button
            onClick={handleRun}
            disabled={running}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-500 text-white font-medium rounded-xl transition-colors flex items-center justify-center gap-2"
          >
            {running ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {running ? 'Simulating...' : 'Run Research'}
          </button>
        </div>

        {/* Strategy Spec summary note */}
        {selectedStrategyInfo && (
          <div className="text-xs bg-gray-950/60 p-3 rounded-xl border border-gray-800/80 flex items-center justify-between text-gray-400">
            <div>
              <span className="text-gray-300 font-semibold">{selectedStrategyInfo.name}</span>: {selectedStrategyInfo.summary}
            </div>
            <span
              className={`px-2 py-0.5 rounded text-[11px] font-mono ${
                selectedStrategyInfo.wired_in_backtest
                  ? 'bg-emerald-950/80 text-emerald-400 border border-emerald-800/50'
                  : 'bg-red-950/80 text-red-400 border border-red-800/50'
              }`}
            >
              {selectedStrategyInfo.wired_in_backtest ? 'Wired to Engine' : 'Fail-Closed Block'}
            </span>
          </div>
        )}

        {/* Advanced Options Toggle */}
        <div>
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-medium"
          >
            {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            {showAdvanced ? 'Hide Advanced Research Gates' : 'Show Advanced Research Gates (Optuna, PBO, Stress, VPIN)'}
          </button>

          {showAdvanced && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4 mt-2 border-t border-gray-800/80">
              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                  <input
                    type="checkbox"
                    checked={useOptuna}
                    onChange={(e) => setUseOptuna(e.target.checked)}
                    className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                  />
                  Bayesian Optuna Optimization
                </label>
                {useOptuna && (
                  <div className="flex items-center gap-2 pl-5">
                    <span className="text-[11px] text-gray-400">Trials:</span>
                    <input
                      type="number"
                      value={optunaTrials}
                      onChange={(e) => setOptunaTrials(Number(e.target.value))}
                      className="w-20 bg-gray-950 border border-gray-800 text-xs rounded p-1 font-mono"
                    />
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                  <input
                    type="checkbox"
                    checked={usePbo}
                    onChange={(e) => setUsePbo(e.target.checked)}
                    className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                  />
                  CSCV Overfitting Audit (PBO)
                </label>
                {usePbo && (
                  <div className="flex items-center gap-2 pl-5">
                    <span className="text-[11px] text-gray-400">Blocks:</span>
                    <input
                      type="number"
                      value={pboBlocks}
                      onChange={(e) => setPboBlocks(Number(e.target.value))}
                      className="w-20 bg-gray-950 border border-gray-800 text-xs rounded p-1 font-mono"
                    />
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-gray-400">Purged Embargo Bars:</span>
                <input
                  type="number"
                  placeholder="e.g. 10"
                  value={embargoBars ?? ''}
                  onChange={(e) => setEmbargoBars(e.target.value ? Number(e.target.value) : undefined)}
                  className="bg-gray-950 border border-gray-800 text-xs text-gray-200 rounded-lg p-1.5 font-mono"
                />
              </div>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={barVpin}
                  onChange={(e) => setBarVpin(e.target.checked)}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Enable Bar-level VPIN Regime Filter
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={generateTearsheet}
                  onChange={(e) => setGenerateTearsheet(e.target.checked)}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Generate Interactive HTML Tearsheet
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={journal}
                  onChange={(e) => setJournal(e.target.checked)}
                  className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                />
                Auto-record row to research/journal.md
              </label>

              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-gray-400">Stress Slices:</span>
                <select
                  value={stressSlice}
                  onChange={(e) => setStressSlice(e.target.value)}
                  className="bg-gray-950 border border-gray-800 text-xs text-gray-300 rounded-lg p-1.5"
                >
                  <option value="">Full Range (No slice)</option>
                  <option value="covid2020">covid2020 (March crash)</option>
                  <option value="ftx2022">ftx2022 (Nov liquidity crisis)</option>
                  <option value="etf2024">etf2024 (Jan ETF launch volatility)</option>
                </select>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Structured Results Showcase: Out-Of-Sample vs Buy&Hold */}
      {summary && (summary.multi_window || summary.single_backtest) && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {summary.multi_window ? (
            <>
              {/* OOS Mean Return */}
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Out-Of-Sample Mean Return
                </span>
                <span
                  className={`text-2xl font-bold font-mono ${
                    summary.multi_window.mean_oos.startsWith('+')
                      ? 'text-emerald-400'
                      : 'text-red-400'
                  }`}
                >
                  {summary.multi_window.mean_oos}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  Reported from {folds} OOS folds
                </span>
              </div>

              {/* Buy & Hold Baseline */}
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Baseline Buy & Hold
                </span>
                <span className="text-2xl font-bold font-mono text-gray-200">
                  {summary.multi_window.buy_and_hold_mean}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  Must beat this to prove edge
                </span>
              </div>

              {/* Profitable Folds Ratio */}
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Profitable Folds
                </span>
                <span className="text-2xl font-bold font-mono text-blue-400">
                  {summary.multi_window.profitable}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  Worst: {summary.multi_window.worst_oos} / Best: {summary.multi_window.best_oos}
                </span>
              </div>

              {/* Total OOS Trades */}
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Total OOS Fills
                </span>
                <span className="text-2xl font-bold font-mono text-gray-200">
                  {summary.multi_window.total_oos_fills}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  Execution sample size
                </span>
              </div>
            </>
          ) : summary.single_backtest ? (
            <>
              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Ending Balance
                </span>
                <span className="text-2xl font-bold font-mono text-emerald-400">
                  ${summary.single_backtest.ending_balance.toLocaleString()}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  {summary.single_backtest.fills} fills / {summary.single_backtest.positions} positions
                </span>
              </div>

              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Max Drawdown
                </span>
                <span className="text-2xl font-bold font-mono text-amber-400">
                  {summary.single_backtest.max_dd_pct}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  Peak-to-trough risk
                </span>
              </div>

              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Sharpe-like Ratio
                </span>
                <span className="text-2xl font-bold font-mono text-blue-400">
                  {summary.single_backtest.sharpe.toFixed(3)}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  Risk-adjusted metric
                </span>
              </div>

              <div className="bg-gray-900 border border-gray-800 p-5 rounded-2xl flex flex-col gap-1">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                  Fees Paid
                </span>
                <span className="text-2xl font-bold font-mono text-red-400">
                  ${summary.single_backtest.fees_paid.toFixed(2)}
                </span>
                <span className="text-[11px] text-gray-500 mt-1">
                  Turnover: ${summary.single_backtest.turnover.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </span>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Tearsheet Embedded Viewer & Terminal Output Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Terminal Log Output */}
        <div className="bg-[#0a0f18] border border-gray-800 rounded-2xl flex flex-col overflow-hidden h-[460px]">
          <div className="bg-gray-900/80 px-4 py-2.5 border-b border-gray-800 flex justify-between items-center">
            <span className="text-xs font-mono text-gray-400 flex items-center gap-2">
              <Terminal className="w-3.5 h-3.5 text-gray-400" />
              Live Console Output
            </span>
            <span className="text-[11px] font-mono text-gray-500">
              {running ? 'Streaming...' : 'Idle'}
            </span>
          </div>
          <div className="p-4 flex-1 overflow-y-auto font-mono text-xs text-emerald-400 whitespace-pre-wrap">
            {log || 'Click "Run Research" to start backtesting.\n'}
          </div>
        </div>

        {/* Tearsheet Preview / List */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl flex flex-col overflow-hidden h-[460px]">
          <div className="bg-gray-900 px-5 py-3 border-b border-gray-800 flex justify-between items-center">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-400" />
              <h3 className="text-sm font-bold text-gray-100">Interactive Tearsheet</h3>
            </div>
            {selectedTearsheetUrl && (
              <a
                href={`http://localhost:8000${selectedTearsheetUrl}`}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
              >
                Open in new tab <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
          </div>

          <div className="flex-1 bg-gray-950 flex flex-col">
            {selectedTearsheetUrl ? (
              <iframe
                src={`http://localhost:8000${selectedTearsheetUrl}`}
                title="Tearsheet View"
                className="w-full h-full border-0 bg-white"
              />
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-gray-500 text-xs">
                <FileText className="w-8 h-8 text-gray-700 mb-2" />
                No tearsheet generated yet.
                <br />
                Run a research backtest with "Generate Interactive HTML Tearsheet" enabled.
              </div>
            )}
          </div>

          {reports.length > 1 && (
            <div className="p-2.5 bg-gray-950 border-t border-gray-800 flex items-center gap-2 overflow-x-auto text-xs">
              <span className="text-gray-500 text-[11px] whitespace-nowrap">Previous:</span>
              {reports.slice(0, 5).map((r, i) => (
                <button
                  key={i}
                  onClick={() => setSelectedTearsheetUrl(r.url)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors whitespace-nowrap ${
                    selectedTearsheetUrl === r.url
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
                  }`}
                >
                  {r.filename.replace('.html', '')}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
