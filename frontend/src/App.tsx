import React, { useEffect, useState } from 'react';
import {
  Activity,
  BookOpen,
  Brain,
  Cpu,
  Database,
  FlaskConical,
  Layers,
  LayoutDashboard,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { getSelectedCatalogPath, setSelectedCatalogPath } from './catalogSelection';
import { fetchCatalog, fetchCatalogs, fetchStatus, fetchStrategies } from './services/api';
import type { CatalogResponse, StatusResponse, StrategySpec } from './services/api';
import { ResearchLab } from './components/ResearchLab';
import { CatalogManager } from './components/CatalogManager';
import { StrategyCatalog } from './components/StrategyCatalog';
import { SettingsPanel } from './components/SettingsPanel';
import { CommandCenter } from './components/CommandCenter';
import { MLPipeline } from './components/MLPipeline';
import { JournalKanban } from './components/JournalKanban';
import { PaperSimulator } from './components/PaperSimulator';

type TabId =
  | 'home'
  | 'research'
  | 'catalog'
  | 'strategies'
  | 'ml'
  | 'journal'
  | 'paper'
  | 'settings';

const SettingsTab = () => <SettingsPanel />;

export function App() {
  const [activeTab, setActiveTab] = useState<TabId>('home');
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [strategies, setStrategies] = useState<StrategySpec[]>([]);
  const [selectedRobot, setSelectedRobot] = useState('regime');
  const [selectedCatalogPath, setSelectedCatalogPathState] = useState(
    () => getSelectedCatalogPath() || 'catalog',
  );

  const handleCatalogChange = (path: string) => {
    setSelectedCatalogPathState(path);
    setSelectedCatalogPath(path);
  };

  const refreshOverview = () => {
    fetchStatus()
      .then((data) => setStatus(data))
      .catch((err) => console.error(err));
    fetchCatalog(selectedCatalogPath)
      .then((data) => setCatalog(data))
      .catch((err) => console.error(err));
    fetchStrategies()
      .then((data) => setStrategies(data.strategies))
      .catch((err) => console.error(err));
  };

  useEffect(() => {
    fetchCatalogs()
      .then((data) => {
        const stored = getSelectedCatalogPath();
        if (!stored && data.default) {
          handleCatalogChange(data.default);
        }
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    refreshOverview();
    const interval = setInterval(refreshOverview, 15000);
    return () => clearInterval(interval);
  }, [selectedCatalogPath]);

  const handleSelectStrategy = (robotName: string) => {
    setSelectedRobot(robotName);
    setActiveTab('research');
  };

  const navButton = (tab: TabId, label: string, icon: React.ReactNode) => (
    <button
      key={tab}
      onClick={() => setActiveTab(tab)}
      className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors ${
        activeTab === tab
          ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
          : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
      }`}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#080c14] text-gray-100 font-sans">
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
          {navButton('home', 'Command Center', <LayoutDashboard className="w-4 h-4" />)}
          {navButton('research', 'Research & Backtest', <Layers className="w-4 h-4" />)}
          {navButton('catalog', 'Parquet Catalog', <Database className="w-4 h-4" />)}
          {navButton('strategies', 'Strategy Specs', <Cpu className="w-4 h-4" />)}
          {navButton('ml', 'ML Pipeline', <Brain className="w-4 h-4" />)}
          {navButton('journal', 'Experiment Journal', <BookOpen className="w-4 h-4" />)}
          {navButton('paper', 'Paper Simulator', <FlaskConical className="w-4 h-4" />)}
          {navButton('settings', 'Settings', <ShieldAlert className="w-4 h-4" />)}
        </nav>

        <div className="mt-auto p-3.5 bg-gray-950/80 border border-gray-800 rounded-2xl flex flex-col gap-2">
          <div className="flex items-center gap-2 text-emerald-400 text-xs font-semibold">
            <ShieldCheck className="w-4 h-4" />
            <span>Safety: Fail-Closed</span>
          </div>
          <p className="text-[11px] text-gray-400 leading-tight">
            Live execution is intentionally disabled. Simulation & walk-forward research only.
          </p>
          {status && (
            <p className="text-[10px] font-mono text-gray-500">
              {status.research_running
                ? 'research running'
                : status.ingest_running
                ? 'ingest running'
                : 'idle'}
              · {catalog?.total_instruments ?? 0} instruments
            </p>
          )}
        </div>
      </aside>

      <main className="flex-1 p-6 md:p-8 flex flex-col gap-6 overflow-y-auto max-h-screen">
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
        {activeTab === 'paper' && <PaperSimulator strategies={strategies} />}
        {activeTab === 'settings' && <SettingsTab />}
      </main>
    </div>
  );
}

export default App;
