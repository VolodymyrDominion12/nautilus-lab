import React, { useMemo, useState } from 'react';
import {
  Filter,
  Flame,
  GitBranch,
  RefreshCw,
  Search,
  ShieldCheck,
  TrendingUp,
  Trophy,
} from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  type LeaderboardEntry,
  type LeaderboardQueryParams,
  syncLeaderboard,
} from '../../services/api';
import { leaderboardQuery, queryKeys } from '../../services/queries';
import { formatPct, toNumber } from '../../lib/format';
import { useToast } from '../toastContext';
import { LeaderboardTable } from './LeaderboardTable';

interface LeaderboardTabProps {
  onRunInLab: (entry: LeaderboardEntry) => void;
}

export const LeaderboardTab: React.FC<LeaderboardTabProps> = ({ onRunInLab }) => {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [sortBy, setSortBy] = useState<LeaderboardQueryParams['sort_by']>('excess');
  const [selectedRobot, setSelectedRobot] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [syncing, setSyncing] = useState(false);

  const { data, isLoading, isFetching, error, refetch } = useQuery(
    leaderboardQuery({
      sort_by: sortBy,
      robot: selectedRobot !== 'all' ? selectedRobot : undefined,
    }),
  );

  const allEntries = data?.entries ?? [];

  // Client-side search query filtering
  const filteredEntries = useMemo(() => {
    if (!searchQuery.trim()) return allEntries;
    const q = searchQuery.toLowerCase();
    return allEntries.filter(
      (e) =>
        e.robot.toLowerCase().includes(q) ||
        e.instrument_id.toLowerCase().includes(q) ||
        e.timeframe.toLowerCase().includes(q) ||
        (e.notes && e.notes.toLowerCase().includes(q)),
    );
  }, [allEntries, searchQuery]);

  // Distinct robot names for filter dropdown
  const robotOptions = useMemo(() => {
    const set = new Set<string>();
    allEntries.forEach((e) => set.add(e.robot));
    return Array.from(set).sort();
  }, [allEntries]);

  // Key KPI highlights
  const highlights = useMemo(() => {
    if (allEntries.length === 0) return null;

    // Best excess return
    const sortedByExcess = [...allEntries].sort(
      (a, b) => (toNumber(b.excess_return) ?? -999) - (toNumber(a.excess_return) ?? -999),
    );
    const bestExcess = sortedByExcess[0];

    // Best raw OOS return
    const sortedByOos = [...allEntries].sort(
      (a, b) => (toNumber(b.oos_return) ?? -999) - (toNumber(a.oos_return) ?? -999),
    );
    const bestOos = sortedByOos[0];

    // Most active by fills
    const sortedByFills = [...allEntries].sort((a, b) => (b.fills ?? 0) - (a.fills ?? 0));
    const mostActive = sortedByFills[0];

    return { bestExcess, bestOos, mostActive };
  }, [allEntries]);

  const handleSyncGit = async () => {
    setSyncing(true);
    try {
      const res = await syncLeaderboard();
      toast.success('Лідерборд синхронізовано з Git!', res.message);
      void queryClient.invalidateQueries({ queryKey: queryKeys.leaderboard() });
    } catch (err) {
      toast.error(
        'Помилка синхронізації',
        err instanceof Error ? err.message : 'Не вдалося оновити leaderboard.md',
      );
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-amber-500/10 border border-amber-500/20 rounded-xl">
              <Trophy className="w-6 h-6 text-amber-400" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-100">Backtest Leaderboard</h2>
              <span className="text-xs text-gray-400">
                Рейтинг найкращих перевірених бектестів за Out-of-Sample (OOS) та альфою над Buy &amp; Hold
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleSyncGit}
              disabled={syncing}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-gray-200 text-xs font-medium border border-gray-700 transition-colors disabled:opacity-50"
              title="Згенерувати research/leaderboard.md"
            >
              <GitBranch className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : 'text-blue-400'}`} />
              <span>{syncing ? 'Синхронізація...' : 'Sync with Git'}</span>
            </button>

            <button
              type="button"
              onClick={() => refetch()}
              className="p-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors"
              title="Оновити список"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Highlight KPI Cards */}
        {highlights && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 border-t border-gray-800/80">
            {/* Best Alpha */}
            <div className="p-3.5 rounded-xl bg-[#0b101b] border border-amber-500/20 flex items-center justify-between">
              <div>
                <span className="text-[10px] text-amber-400 uppercase font-bold tracking-wider block">
                  🥇 Топ Альфа (Excess)
                </span>
                <span className="text-base font-bold text-gray-100 font-mono">
                  {formatPct(toNumber(highlights.bestExcess?.excess_return))}
                </span>
                <span className="text-[11px] text-gray-400 block">
                  {highlights.bestExcess?.robot} · {highlights.bestExcess?.instrument_id}
                </span>
              </div>
              <TrendingUp className="w-6 h-6 text-amber-400/60" />
            </div>

            {/* Best OOS */}
            <div className="p-3.5 rounded-xl bg-[#0b101b] border border-blue-500/20 flex items-center justify-between">
              <div>
                <span className="text-[10px] text-blue-400 uppercase font-bold tracking-wider block">
                  📈 Топ OOS Return
                </span>
                <span className="text-base font-bold text-gray-100 font-mono">
                  {formatPct(toNumber(highlights.bestOos?.oos_return))}
                </span>
                <span className="text-[11px] text-gray-400 block">
                  {highlights.bestOos?.robot} · {highlights.bestOos?.timeframe}
                </span>
              </div>
              <ShieldCheck className="w-6 h-6 text-blue-400/60" />
            </div>

            {/* Most Active */}
            <div className="p-3.5 rounded-xl bg-[#0b101b] border border-purple-500/20 flex items-center justify-between">
              <div>
                <span className="text-[10px] text-purple-400 uppercase font-bold tracking-wider block">
                  ⚡ Найбільше угод (Fills)
                </span>
                <span className="text-base font-bold text-gray-100 font-mono">
                  {highlights.mostActive?.fills?.toLocaleString() ?? 0}
                </span>
                <span className="text-[11px] text-gray-400 block">
                  {highlights.mostActive?.robot} · {highlights.mostActive?.profitable_folds ?? 'folds'}
                </span>
              </div>
              <Flame className="w-6 h-6 text-purple-400/60" />
            </div>
          </div>
        )}
      </div>

      {/* Filter and Control Bar */}
      <div className="flex flex-col md:flex-row items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 w-full md:w-auto">
          {/* Search box */}
          <div className="relative flex-1 md:w-64">
            <Search className="w-3.5 h-3.5 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Пошук стратегії, пари..."
              className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-gray-900 border border-gray-800 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Robot filter */}
          {robotOptions.length > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-gray-400">
              <Filter className="w-3.5 h-3.5 text-gray-500" />
              <select
                value={selectedRobot}
                onChange={(e) => setSelectedRobot(e.target.value)}
                className="bg-gray-900 border border-gray-800 text-gray-200 rounded-xl px-2.5 py-1.5 text-xs focus:outline-none focus:border-blue-500"
              >
                <option value="all">Усі роботи</option>
                {robotOptions.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Sort selector */}
        <div className="flex items-center gap-2 text-xs text-gray-400 w-full md:w-auto justify-end">
          <span>Сортувати за:</span>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as LeaderboardQueryParams['sort_by'])}
            className="bg-gray-900 border border-gray-800 text-gray-200 rounded-xl px-2.5 py-1.5 text-xs focus:outline-none focus:border-blue-500 font-mono"
          >
            <option value="excess">Excess Return (Альфа над Buy&amp;Hold)</option>
            <option value="oos">Out-of-Sample Return</option>
            <option value="sharpe">Sharpe Ratio</option>
            <option value="fills">Кількість fills</option>
            <option value="date">Дата додавання</option>
          </select>
        </div>
      </div>

      {/* Main Table or Empty State */}
      {isLoading ? (
        <div className="p-12 text-center text-gray-500 text-xs flex flex-col items-center gap-3">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-400" />
          <span>Завантаження лідерборду...</span>
        </div>
      ) : error ? (
        <div className="p-4 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-xs">
          Помилка завантаження: {error instanceof Error ? error.message : 'Невідома помилка'}
        </div>
      ) : filteredEntries.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-8 text-center flex flex-col items-center gap-3">
          <Trophy className="w-10 h-10 text-gray-600" />
          <h3 className="text-sm font-bold text-gray-300">Немає записів у лідерборді</h3>
          <p className="text-xs text-gray-500 max-w-md">
            Щоб додати новий бектест до лідерборду, запустіть дослідження з прапорцем{' '}
            <code className="text-amber-300 bg-gray-950 px-1.5 py-0.5 rounded border border-gray-800">
              --leaderboard
            </code>
            :
          </p>
          <pre className="p-3 bg-gray-950 border border-gray-800 rounded-xl text-xs font-mono text-gray-300 select-all">
            uv run lab research --robot regime --folds 4 --leaderboard
          </pre>
        </div>
      ) : (
        <LeaderboardTable entries={filteredEntries} onRunInLab={onRunInLab} />
      )}
    </div>
  );
};
