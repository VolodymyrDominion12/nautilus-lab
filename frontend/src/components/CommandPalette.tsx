import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeftRight,
  BookOpen,
  Brain,
  Cpu,
  Database,
  FlaskConical,
  Layers,
  LayoutDashboard,
  Play,
  Search,
  Settings,
  Sparkles,
  Zap,
} from 'lucide-react';
import type { StrategySpec } from '../services/api';

export interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigateTab: (tabId: string) => void;
  onSelectStrategy: (robotName: string) => void;
  onOpenGuide?: () => void;
  strategies: StrategySpec[];
}

interface PaletteItem {
  id: string;
  category: 'Tabs' | 'Strategies' | 'Actions';
  title: string;
  subtitle?: string;
  badge?: string;
  icon: React.ReactNode;
  action: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onNavigateTab,
  onSelectStrategy,
  onOpenGuide,
  strategies,
}) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  const items = useMemo<PaletteItem[]>(() => {
    const list: PaletteItem[] = [
      // Navigation Tabs
      {
        id: 'tab-home',
        category: 'Tabs',
        title: 'Command Center',
        subtitle: 'Live jobs, last measured result, data coverage & health',
        icon: <LayoutDashboard className="w-4 h-4 text-blue-400" />,
        action: () => {
          onNavigateTab('home');
          onClose();
        },
      },
      {
        id: 'tab-research',
        category: 'Tabs',
        title: 'Research & Backtest',
        subtitle: 'Walk-forward engine, fold breakdown, tearsheets, PBO audit',
        icon: <Layers className="w-4 h-4 text-blue-400" />,
        action: () => {
          onNavigateTab('research');
          onClose();
        },
      },
      {
        id: 'tab-catalog',
        category: 'Tabs',
        title: 'Parquet Catalog',
        subtitle: 'Binance klines, aggregated trades, funding, L2 depth',
        icon: <Database className="w-4 h-4 text-emerald-400" />,
        action: () => {
          onNavigateTab('catalog');
          onClose();
        },
      },
      {
        id: 'tab-strategies',
        category: 'Tabs',
        title: 'Strategy Specs',
        subtitle: 'Machine-validated strategy directory from specs/strategies/*.yaml',
        icon: <Cpu className="w-4 h-4 text-purple-400" />,
        action: () => {
          onNavigateTab('strategies');
          onClose();
        },
      },
      {
        id: 'tab-ml',
        category: 'Tabs',
        title: 'ML Pipeline',
        subtitle: 'LightGBM model training with purged CV, formulaic & meta-label',
        icon: <Brain className="w-4 h-4 text-amber-400" />,
        action: () => {
          onNavigateTab('ml');
          onClose();
        },
      },
      {
        id: 'tab-journal',
        category: 'Tabs',
        title: 'Experiment Journal',
        subtitle: 'Kanban board of hypothesis accept / reject / rerun decisions',
        icon: <BookOpen className="w-4 h-4 text-pink-400" />,
        action: () => {
          onNavigateTab('journal');
          onClose();
        },
      },
      {
        id: 'tab-paper',
        category: 'Tabs',
        title: 'Paper Simulator',
        subtitle: 'Hypothetical order stream generator without live exchange',
        icon: <FlaskConical className="w-4 h-4 text-cyan-400" />,
        action: () => {
          onNavigateTab('paper');
          onClose();
        },
      },
      {
        id: 'tab-scan',
        category: 'Tabs',
        title: 'Arb Scanner',
        subtitle: 'Triangular currency path arbitrage opportunity scanner',
        icon: <ArrowLeftRight className="w-4 h-4 text-indigo-400" />,
        action: () => {
          onNavigateTab('scan');
          onClose();
        },
      },
      {
        id: 'tab-alpha',
        category: 'Tabs',
        title: 'Alpha Ideas & Hypotheses',
        subtitle: 'Offline LLM alpha generation and formulaic hypothesis inspector',
        icon: <Sparkles className="w-4 h-4 text-yellow-400" />,
        action: () => {
          onNavigateTab('alpha');
          onClose();
        },
      },
      {
        id: 'tab-settings',
        category: 'Tabs',
        title: 'Settings & Config',
        subtitle: 'Environment configuration, execution fees, risk limits',
        icon: <Settings className="w-4 h-4 text-gray-400" />,
        action: () => {
          onNavigateTab('settings');
          onClose();
        },
      },
      {
        id: 'action-guide',
        category: 'Actions',
        title: 'Interface & Methodology Guide',
        subtitle: 'Повний довідник по метриках, розрахунках, правилах та роботі модулів',
        icon: <BookOpen className="w-4 h-4 text-blue-400" />,
        action: () => {
          onClose();
          onOpenGuide?.();
        },
      },
    ];

    // Strategies
    strategies.forEach((strat) => {
      list.push({
        id: `strat-${strat.name}`,
        category: 'Strategies',
        title: `Robot: ${strat.name}`,
        subtitle: strat.summary || `Strategy ${strat.strategy_class}`,
        badge: strat.wired_in_backtest ? 'Wired' : 'Fail Closed',
        icon: <Cpu className="w-4 h-4 text-indigo-400" />,
        action: () => {
          onSelectStrategy(strat.name);
          onClose();
        },
      });
    });

    // Actions
    list.push(
      {
        id: 'act-new-research',
        category: 'Actions',
        title: 'Quick Action: Launch Walk-Forward Backtest',
        subtitle: 'Switch to Research tab and ready to run',
        icon: <Play className="w-4 h-4 text-emerald-400" />,
        action: () => {
          onNavigateTab('research');
          onClose();
        },
      },
      {
        id: 'act-ingest-data',
        category: 'Actions',
        title: 'Quick Action: Ingest Historical Market Data',
        subtitle: 'Open Binance catalog downloader',
        icon: <Zap className="w-4 h-4 text-amber-400" />,
        action: () => {
          onNavigateTab('catalog');
          onClose();
        },
      },
    );

    return list;
  }, [strategies, onNavigateTab, onSelectStrategy, onClose, onOpenGuide]);

  const filteredItems = useMemo(() => {
    if (!query.trim()) return items;
    const q = query.toLowerCase().trim();
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        (item.subtitle && item.subtitle.toLowerCase().includes(q)) ||
        item.category.toLowerCase().includes(q),
    );
  }, [items, query]);

  // Handle keyboard navigation
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1 < filteredItems.length ? prev + 1 : 0));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 >= 0 ? prev - 1 : filteredItems.length - 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const item = filteredItems[selectedIndex];
        if (item) {
          item.action();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, filteredItems, selectedIndex, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-150">
      <div
        className="w-full max-w-2xl bg-[#0c121e] border border-gray-700/80 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[75vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-gray-800 bg-gray-900/60">
          <Search className="w-5 h-5 text-gray-400 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder="Type a command, robot, or tab... (e.g. 'research', 'regime', 'catalog')"
            className="flex-1 bg-transparent border-0 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-0"
          />
          <kbd className="hidden sm:inline-block px-2 py-0.5 text-[10px] font-mono text-gray-400 bg-gray-800/80 rounded border border-gray-700">
            ESC
          </kbd>
        </div>

        {/* Results List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {filteredItems.length === 0 ? (
            <div className="p-8 text-center text-xs text-gray-500">
              No matching commands or robots found for &quot;{query}&quot;
            </div>
          ) : (
            filteredItems.map((item, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <button
                  type="button"
                  key={item.id}
                  onClick={item.action}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-xl text-left transition-all ${
                    isSelected
                      ? 'bg-blue-600/20 text-white border border-blue-500/30'
                      : 'text-gray-300 hover:bg-gray-800/50'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="p-1.5 rounded-lg bg-gray-800/80 border border-gray-700/60 shrink-0">
                      {item.icon}
                    </span>
                    <div className="min-w-0">
                      <div className="text-xs font-bold truncate flex items-center gap-2">
                        <span>{item.title}</span>
                        {item.badge && (
                          <span
                            className={`text-[9px] font-mono px-1.5 py-0.2 rounded border ${
                              item.badge === 'Wired'
                                ? 'bg-emerald-950/60 text-emerald-400 border-emerald-800/40'
                                : 'bg-red-950/60 text-red-400 border-red-800/40'
                            }`}
                          >
                            {item.badge}
                          </span>
                        )}
                      </div>
                      {item.subtitle && (
                        <div className="text-[11px] text-gray-400 truncate mt-0.5">
                          {item.subtitle}
                        </div>
                      )}
                    </div>
                  </div>

                  <span className="text-[10px] font-mono text-gray-500 uppercase shrink-0">
                    {item.category}
                  </span>
                </button>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="px-4 py-2 border-t border-gray-800/80 bg-gray-950/80 flex items-center justify-between text-[11px] text-gray-500 font-mono">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="px-1 bg-gray-800 rounded text-gray-400">↑</kbd>{' '}
              <kbd className="px-1 bg-gray-800 rounded text-gray-400">↓</kbd> navigate
            </span>
            <span>
              <kbd className="px-1 bg-gray-800 rounded text-gray-400">↵</kbd> select
            </span>
          </div>
          <span>Nautilus Lab Command Palette</span>
        </div>
      </div>
    </div>
  );
};
