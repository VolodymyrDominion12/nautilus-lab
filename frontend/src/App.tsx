import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, WifiOff } from 'lucide-react';
import { getSelectedCatalogPath, setSelectedCatalogPath } from './catalogSelection';
import { catalogQuery, catalogsQuery, statusQuery, strategiesQuery } from './services/queries';
import type { StrategySpec } from './services/api';
import type { TabId } from './tabs';
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
import { CommandPalette } from './components/CommandPalette';
import { InterfaceGuideModal } from './components/InterfaceGuideModal';
import { TradeDetailPage } from './components/trades/TradeDetailPage';
import { ToastProvider } from './components/Toast';
import { useToast } from './components/toastContext';
import { Sidebar } from './components/Sidebar';
import { parseTradeHash, buildTradeHash } from './lib/trades';
import type { TradeRoute } from './lib/trades';
import { buildBatchHash, parseBatchHash, type BatchRoute } from './lib/batch';
import { BatchSection } from './components/batch/BatchSection';

const SettingsTab = () => <SettingsPanel />;

const NO_STRATEGIES: StrategySpec[] = [];

/**
 * The trade page in the URL fragment, kept in sync with the browser.
 *
 * A trade gets its own address (`#/trade?session=…&id=…`) rather than a modal, so it can be
 * linked, bookmarked, opened in a new tab and left with the Back button — the same address
 * for a backtest trade and a paper trade, because both are reconstructed from the decision
 * log. The fragment is read here and nowhere else; the active tab is kept in state, so Back
 * returns to the tab the link was opened from (that tab's own component remounts, which also
 * means a modal it had open is closed — the user came from a link, not from that modal).
 */
function useTradeRoute(): [TradeRoute | null, (route: TradeRoute | null) => void] {
  const [route, setRoute] = useState<TradeRoute | null>(() =>
    parseTradeHash(window.location.hash),
  );

  useEffect(() => {
    const onHashChange = () => setRoute(parseTradeHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  const navigate = useCallback((next: TradeRoute | null) => {
    if (next) {
      window.location.hash = buildTradeHash(next);
    } else if (parseTradeHash(window.location.hash)) {
      // Setting an empty fragment fires `hashchange`, which is what updates the state.
      window.location.hash = '';
    }
    setRoute(next);
  }, []);

  return [route, navigate];
}

/** The batch pages' route (`#/batch…`, `#/run…`), kept in sync with the browser. */
function useBatchRoute(): BatchRoute | null {
  const [route, setRoute] = useState<BatchRoute | null>(() =>
    parseBatchHash(window.location.hash),
  );
  useEffect(() => {
    const onHashChange = () => setRoute(parseBatchHash(window.location.hash));
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  return route;
}

/** The banner text when the API cannot be read; null while it answers. */
function describeFailure(statusError: Error | null, strategiesError: Error | null): string | null {
  if (statusError) {
    return statusError.message || 'Cannot reach the API. Start it with: uvicorn nautilus_lab.api.app:app';
  }
  if (strategiesError) return strategiesError.message || 'Cannot reach API strategies';
  return null;
}

function AppContent() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabId>('home');
  const [selectedRobot, setSelectedRobot] = useState('regime');
  const [isPaletteOpen, setIsPaletteOpen] = useState(false);
  const [isGuideOpen, setIsGuideOpen] = useState(false);
  const [tradeRoute, navigateToTrade] = useTradeRoute();
  const batchRoute = useBatchRoute();
  const [selectedCatalogPath, setSelectedCatalogPathState] = useState(
    () => getSelectedCatalogPath() || 'catalog',
  );

  // Hypotheses passed from AlphaIdeasTab into ResearchLab
  const [externalHypoConfig, setExternalHypoConfig] = useState<{
    robot?: string;
    formula?: string;
    notes?: string;
  } | null>(null);

  // Track background jobs transition to notify on completion
  const prevJobsRef = useRef<Record<string, boolean>>({});
  // A `paper` server opens on the live terminal once; afterwards the user navigates freely.
  const openedOnPaperRef = useRef(false);

  const handleCatalogChange = (path: string) => {
    setSelectedCatalogPathState(path);
    setSelectedCatalogPath(path);
  };

  // Server state from the shared query cache (services/queries.ts): polled while the
  // tab is visible, paused while it is hidden.
  const statusResult = useQuery(statusQuery(selectedCatalogPath));
  const catalog = useQuery(catalogQuery(selectedCatalogPath)).data;
  const strategiesResult = useQuery(strategiesQuery());
  const catalogsResult = useQuery(catalogsQuery());
  const status = statusResult.data ?? null;
  const strategies: StrategySpec[] = strategiesResult.data?.strategies ?? NO_STRATEGIES;
  const connectionError = describeFailure(statusResult.error, strategiesResult.error);
  const defaultCatalog = catalogsResult.data?.default;
  const isPaperServer = status?.lab_role === 'paper';

  // Keyboard shortcut: Cmd+K / Ctrl+K opens CommandPalette; ? opens Guide
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const targetTag = (e.target as HTMLElement)?.tagName;
      const isInput = targetTag === 'INPUT' || targetTag === 'TEXTAREA' || targetTag === 'SELECT';

      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsPaletteOpen((prev) => !prev);
      } else if (e.key === '?' && !isInput && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setIsGuideOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // A job that finished: say so, and re-read what it may have written (catalog,
  // reports, models) instead of waiting for each panel's next poll.
  useEffect(() => {
    if (!status?.jobs) return;
    let finished = false;
    Object.entries(status.jobs).forEach(([key, job]) => {
      const wasRunning = prevJobsRef.current[key];
      if (wasRunning && !job.running) {
        finished = true;
        toast.success(`Task finished: ${job.label}`, 'Process finished execution');
      }
      prevJobsRef.current[key] = Boolean(job.running);
    });
    if (finished) void queryClient.invalidateQueries();
  }, [status?.jobs, toast, queryClient]);

  useEffect(() => {
    if (!getSelectedCatalogPath() && defaultCatalog) {
      handleCatalogChange(defaultCatalog);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultCatalog]);

  useEffect(() => {
    if (isPaperServer && !openedOnPaperRef.current) {
      openedOnPaperRef.current = true;
      setActiveTab('paper');
    }
  }, [isPaperServer]);

  const handleSelectStrategy = (robotName: string) => {
    setSelectedRobot(robotName);
    setActiveTab('research');
  };

  const handleTestHypothesis = (cfg: { robot: string; formula?: string; notes?: string }) => {
    setExternalHypoConfig(cfg);
    setSelectedRobot(cfg.robot);
    setActiveTab('research');
    toast.success('Hypothesis loaded into Research Lab!', cfg.notes || cfg.formula);
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#080c14] text-gray-100 font-sans">
      <CommandPalette
        isOpen={isPaletteOpen}
        onClose={() => setIsPaletteOpen(false)}
        onNavigateTab={(tab) => setActiveTab(tab as TabId)}
        onSelectStrategy={handleSelectStrategy}
        onOpenGuide={() => setIsGuideOpen(true)}
        strategies={strategies}
      />

      <Sidebar
        activeTab={batchRoute ? 'batch' : activeTab}
        onNavigate={(tab) => {
          // The batch pages live in the address; leaving them clears it, entering sets it.
          if (tab === 'batch') window.location.hash = buildBatchHash({ page: 'list' });
          else if (batchRoute || tradeRoute) window.location.hash = '';
          setActiveTab(tab);
        }}
        status={status}
        catalog={catalog}
        onOpenPalette={() => setIsPaletteOpen(true)}
        onOpenGuide={() => setIsGuideOpen(true)}
      />

      <main className="flex-1 p-6 md:p-8 flex flex-col gap-6 overflow-y-auto max-h-screen">
        {connectionError && (
          <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl flex items-start gap-3 text-red-300 text-xs">
            <WifiOff className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>
              {connectionError}
              <span className="block text-red-400/70 mt-1 font-mono">
                Try: uv run --extra api uvicorn nautilus_lab.api.app:app --port 8000 (or: make api)
              </span>
            </span>
          </div>
        )}

        {isPaperServer && (
          <div className="p-3 bg-amber-950/30 border border-amber-800/50 rounded-xl flex items-start gap-3 text-amber-200 text-xs">
            <ShieldCheck className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>
              Paper server (LAB_ROLE=paper): only the live paper terminal runs here. Research, ingest,
              ML and settings changes are disabled — run them on the workstation.
              {status?.live_paper_persisted === false && (
                <span className="block text-amber-400/80 mt-1">
                  LIVE_PAPER_JOURNAL is not set: the ledger is lost on restart.
                </span>
              )}
            </span>
          </div>
        )}

        {tradeRoute ? (
          <TradeDetailPage
            route={tradeRoute}
            onClose={() =>
              // A trade opened from a batch run goes back to that run, not to a tab.
              tradeRoute.origin === 'backtest' && window.history.length > 1
                ? window.history.back()
                : navigateToTrade(null)
            }
          />
        ) : batchRoute || activeTab === 'batch' ? (
          <BatchSection route={batchRoute ?? { page: 'list' }} />
        ) : (
          <>
            {activeTab === 'home' && <CommandCenter />}
            {activeTab === 'research' && (
              <ResearchLab
                strategies={strategies}
                initialRobot={selectedRobot}
                selectedCatalogPath={selectedCatalogPath}
                tickVpinRobots={status?.tick_vpin_robots}
                hawkesRobots={status?.hawkes_robots}
                stressSlices={status?.stress_slices}
                externalConfig={externalHypoConfig}
                onClearExternalConfig={() => setExternalHypoConfig(null)}
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
            {activeTab === 'alpha' && <AlphaIdeasTab onTestInResearch={handleTestHypothesis} />}
            {activeTab === 'settings' && <SettingsTab />}
          </>
        )}
      </main>

      <InterfaceGuideModal
        isOpen={isGuideOpen}
        onClose={() => setIsGuideOpen(false)}
      />
    </div>
  );
}

export function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
}

export default App;
