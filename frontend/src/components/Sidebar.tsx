import React from 'react';
import {
  Activity,
  ArrowLeftRight,
  BookOpen,
  Brain,
  Cpu,
  Database,
  HelpCircle,
  Layers,
  LayoutDashboard,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Zap,
} from 'lucide-react';

import { formatElapsed } from '../lib/format';
import type { CatalogResponse, JobKey, JobState, StatusResponse } from '../services/api';
import { JOB_TABS, type TabId } from '../tabs';

interface SidebarProps {
  activeTab: TabId;
  onNavigate: (tab: TabId) => void;
  status: StatusResponse | null;
  catalog: CatalogResponse | undefined;
  onOpenPalette: () => void;
  onOpenGuide: () => void;
}

/** Navigation, the jobs running now, and the safety summary read from /api/status. */
export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onNavigate,
  status,
  catalog,
  onOpenPalette,
  onOpenGuide,
}) => {
  const navButton = (tab: TabId, label: string, icon: React.ReactNode, badge?: React.ReactNode) => (
    <button
      type="button"
      key={tab}
      onClick={() => onNavigate(tab)}
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

  return (
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

      {/* Quick Search / Command Palette button */}
      <button
        type="button"
        onClick={onOpenPalette}
        className="flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-gray-950 border border-gray-800 text-xs text-gray-400 hover:text-gray-200 hover:border-gray-700 transition-colors"
      >
        <span className="flex items-center gap-2">
          <Search className="w-3.5 h-3.5 text-gray-500" />
          <span>Search / Jump</span>
        </span>
        <kbd className="px-1.5 py-0.5 text-[9px] font-mono text-gray-500 bg-gray-900 rounded border border-gray-800">
          ⌘K
        </kbd>
      </button>

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
          'Trading Terminal',
          <Zap className="w-4 h-4" />,
          status?.jobs?.paper.running ? (
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          ) : undefined,
        )}

        <div className="my-0.5 border-t border-gray-800/60" />

        {navButton('scan', 'Arb Scanner', <ArrowLeftRight className="w-4 h-4" />)}
        {navButton('alpha', 'Alpha Ideas', <Sparkles className="w-4 h-4" />)}

        <div className="my-0.5 border-t border-gray-800/60" />

        {navButton('settings', 'Settings', <ShieldAlert className="w-4 h-4" />)}

        <button
          type="button"
          onClick={onOpenGuide}
          className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium transition-colors text-blue-400/90 hover:bg-blue-600/10 hover:text-blue-300 border border-blue-500/20"
        >
          <HelpCircle className="w-4 h-4 text-blue-400" />
          <span className="flex-1 text-left">Guide &amp; Docs</span>
          <kbd className="px-1.5 py-0.5 text-[9px] font-mono text-blue-300 bg-blue-950 rounded border border-blue-800/50">
            ?
          </kbd>
        </button>
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
              onClick={() => onNavigate(JOB_TABS[key])}
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
  );
};
