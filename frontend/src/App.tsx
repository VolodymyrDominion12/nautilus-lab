import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  ArrowLeftRight,
  BookOpen,
  Brain,
  Cpu,
  Database,
  FlaskConical,
  Layers,
  LayoutDashboard,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  WifiOff,
} from 'lucide-react';
import { getSelectedCatalogPath, setSelectedCatalogPath } from './catalogSelection';
import { fetchCatalog, fetchCatalogs, fetchStatus, fetchStrategies } from './services/api';
import type { CatalogResponse, JobKey, JobState, StatusResponse, StrategySpec } from './services/api';
import { ResearchLab } from './components/ResearchLab';
import { CatalogManager } from './components/CatalogManager';
import { StrategyCatalog } from './components/StrategyCatalog';
import { SettingsPanel } from './components/SettingsPanel';
import { CommandCenter } from './components/CommandCenter';
import { MLPipeline } from './components/MLPipeline';
import { JournalKanban } from './components/JournalKanban';
import { PaperSimulator } from './components/PaperSimulator';
import { ScanTab } from './components/ScanTab';
import { AlphaIdeasTab } from './components/AlphaIdeasTab';
import { formatElapsed } from './lib/format';

type TabId =
  | 'home'
  | 'research'
  | 'catalog'
  | 'strategies'
  | 'ml'
  | 'journal'
  | 'paper'
  | 'scan'
  | 'alpha'
  | 'settings';

const SettingsTab = () => <SettingsPanel />;

const JOB_TABS: Record<JobKey, TabId> = {
  research: 'research',
  ingest: 'catalog',
  ml_train: 'ml',
  paper: 'paper',
};

export function App() {
  const [activeTab, setActiveTab] = useState<TabId>('home');
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [strategies, setStrategies] = useState<StrategySpec[]>([]);
  const [selectedRobot, setSelectedRobot] = useState('regime');
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [selectedCatalogPath, setSelectedCatalogPathState] = useState(
    () => getSelectedCatalogPath() || 'catalog',
  );

  const handleCatalogChange = (path: string) => {
    setSelectedCatalogPathState(path);
    setSelectedCatalogPath(path);
  };

  const refreshOverview = useCallback(() => {
    fetchStatus(selectedCatalogPath)
      .then((data) => {
        setStatus(data);
        setConnectionError(null);
      })
      .catch((err: unknown) => {
        setConnectionError(
          err instanceof Error
            ? err.message
            : 'Cannot reach the API. Start it with: uvicorn nautilus_lab.api.app:app',
        );
      });
    fetchCatalog(selectedCatalogPath)
      .then((data) => setCatalog(data))
      .catch((err: unknown) => console.error(err));
    fetchStrategies()
      .then((data) => setStrategies(data.strategies))
      .catch((err: unknown) => console.error(err));
  }, [selectedCatalogPath]);

  useEffect(() => {
    fetchCatalogs()
      .then((data) => {
        const stored = getSelectedCatalogPath();
        if (!stored && data.default) {
          handleCatalogChange(data.default);
        }
      })
      .catch((err: unknown) => console.error(err));
  }, []);

  useEffect(() => {
    refreshOverview();
    const interval = setInterval(refreshOverview, 15000);
    return () => clearInterval(interval);
  }, [refreshOverview]);

  const handleSelectStrategy = (robotName: string) => {
    setSelectedRobot(robotName);
    setActiveTab('research');
  };

  const navButton = (tab: TabId, label: string, icon: React.ReactNode, badge?: React.ReactNode) => (
    <button
      type="button"
      key={tab}
      onClick={() => setActiveTab(tab)}
      className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors ${
        activeTab === tab
          ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
          : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
      }`}
    >
      {icon}
      <span className="flex-1 text-left">{label}</span>
      {badge}
    </button>
  );

  const runningJobs: [JobKey, JobState][] = Object.entries(status?.jobs ?? {}).filter(
    ([, job]) => job.running,
  ) as [JobKey, JobState][];

  const toggleJob = (key: JobKey) => setActiveTab(JOB_TABS[key]);

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#080c14] text-gray-100 font-sans">
      <aside className="w-full md:w-64 bg-[#0d131f] border-r border-gray-800/80 p-5 flex flex-col gap-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-600/10 border border-blue-500/20 rounded-xl">
            <Activity className="text-blue-400 w-6 h-6" />
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-gray-100">Nautilus Lab</h1>
            <span className="text-[10px] font-mono text-gray-400 block">
              Research-first engine
            </span>
          </div>
        </div>

        <nav className="flex flex-col gap-1.5">
          {navButton('home', 'Command Center', <LayoutDashboard className="w-4 h-4" />)}
          {navButton(
            'research',
            'Research & Backtest',
            <Layers className="w-4 h-4" />,
            status?.jobs?.research.running ? (
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            ) : undefined,
          )}
          {navButton(
            'catalog',
            'Parquet Catalog',
            <Database className="w-4 h-4" />,
            status?.jobs?.ingest.running ? (
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            ) : undefined,
          )}
          {navButton('strategies', 'Strategy Specs', <Cpu className="w-4 h-4" />)}
          {navButton(
            'ml',
            'ML Pipeline',
            <Brain className="w-4 h-4" />,
            status?.jobs?.ml_train.running ? (
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            ) : undefined,
          )}
          {navButton('journal', 'Experiment Journal', <BookOpen className="w-4 h-4" />)}
          {navButton(
            'paper',
            'Paper Simulator',
            <FlaskConical className="w-4 h-4" />,
            status?.jobs?.paper.running ? (
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            ) : undefined,
          )}

          <div className="my-0.5 border-t border-gray-800/60" />

          {navButton('scan', 'Arb Scanner', <ArrowLeftRight className="w-4 h-4" />)}
          {navButton('alpha', 'Alpha Ideas', <Sparkles className="w-4 h-4" />)}

          <div className="my-0.5 border-t border-gray-800/60" />

          {navButton('settings', 'Settings', <ShieldAlert className="w-4 h-4" />)}
        </nav>

        {runningJobs.length > 0 && (
          <div className="p-3 bg-amber-950/30 border border-amber-800/40 rounded-2xl flex flex-col gap-1.5">
            <span className="text-[10px] font-semibold text-amber-300 uppercase tracking-wider">
              Running now
            </span>
            {runningJobs.map(([key, job]) => (
              <button
                type="button"
                key={key}
                onClick={() => toggleJob(key)}
                className="flex items-center justify-between gap-2 text-[11px] text-gray-300 hover:text-white text-left"
              >
                <span className="truncate">{job.label}</span>
                <span className="font-mono text-amber-300 shrink-0">
                  {formatElapsed(job.elapsed_seconds) || '…'}
                </span>
              </button>
            ))}
          </div>
        )}

        <div className="mt-auto p-3.5 bg-gray-950/80 border border-gray-800 rounded-2xl flex flex-col gap-2">
          <div className="flex items-center gap-2 text-emerald-400 text-xs font-semibold">
            <ShieldCheck className="w-4 h-4" />
            <span>
              {status?.live_safe_mode === 'FAIL_CLOSED' ? 'Safety: fail-closed' : 'Safety: unknown'}
            </span>
          </div>
          <p className="text-[11px] text-gray-400 leading-tight">
            No execution adapter exists: <span className="font-mono">lab live</span> always exits 1,
            and orders are never submitted.
          </p>
          <dl className="text-[10px] font-mono text-gray-500 flex flex-col gap-0.5">
            <div className="flex justify-between gap-2">
              <dt>mode</dt>
              <dd className="text-gray-400">{status?.trading_mode ?? '—'}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>interval</dt>
              <dd className="text-gray-400">{status?.bar_interval ?? catalog?.bar_interval ?? '—'}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>instruments</dt>
              <dd className="text-gray-400">{catalog?.total_instruments ?? 0}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>robots wired</dt>
              <dd className="text-gray-400">
                {status?.wired_robots.length ?? 0}/{status?.strategies_available.length ?? 0}
              </dd>
            </div>
          </dl>
        </div>
      </aside>

      <main className="flex-1 p-6 md:p-8 flex flex-col gap-6 overflow-y-auto max-h-screen">
        {connectionError && (
          <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl flex items-start gap-3 text-red-300 text-xs">
            <WifiOff className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>
              {connectionError}
              <span className="block text-red-400/70 mt-1 font-mono">
                Try: .venv/bin/uvicorn nautilus_lab.api.app:app --port 8000
              </span>
            </span>
          </div>
        )}

        {activeTab === 'home' && <CommandCenter />}
        {activeTab === 'research' && (
          <ResearchLab
            strategies={strategies}
            initialRobot={selectedRobot}
            selectedCatalogPath={selectedCatalogPath}
          />
        )}
        {activeTab === 'catalog' && (
          <CatalogManager
            selectedCatalogPath={selectedCatalogPath}
            onCatalogChange={handleCatalogChange}
          />
        )}
        {activeTab === 'strategies' && (
          <StrategyCatalog strategies={strategies} onSelectStrategy={handleSelectStrategy} />
        )}
        {activeTab === 'ml' && <MLPipeline selectedCatalogPath={selectedCatalogPath} />}
        {activeTab === 'journal' && <JournalKanban />}
        {activeTab === 'paper' && <PaperSimulator strategies={strategies} status={status} />}
        {activeTab === 'scan' && <ScanTab />}
        {activeTab === 'alpha' && <AlphaIdeasTab />}
        {activeTab === 'settings' && <SettingsTab />}
      </main>
    </div>
  );
}

export default App;
