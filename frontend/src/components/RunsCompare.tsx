import React, { useEffect, useMemo, useState } from 'react';
import { ArrowDownUp, Check, Copy, GitCompare, RefreshCw } from 'lucide-react';
import { fetchResearchHistory } from '../services/api';
import type { HistoryEntry } from '../services/api';
import { formatBps, formatDateTime, formatPct, toNumber } from '../lib/format';

interface RunsCompareProps {
  /** Bump to force a reload after a run finishes. */
  refreshKey?: number;
}

interface CompareRow {
  entry: HistoryEntry;
  evidence: 'out-of-sample' | 'in-sample-only' | 'overfitting-audit' | 'unknown';
  oos: number | null;
  buyHold: number | null;
  excess: number | null;
  folds: number | null;
  profitable: string | null;
  fills: number | null;
  headroom: number | null;
  breakeven: number | null;
}

const toRow = (entry: HistoryEntry): CompareRow => {
  const multi = entry.multi_window;
  const single = entry.single_backtest;
  const evidence =
    entry.run_type === 'pbo'
      ? 'overfitting-audit'
      : multi
        ? 'out-of-sample'
        : entry.run_type === 'walk_forward'
          ? 'out-of-sample'
          : single
            ? 'in-sample-only'
            : 'unknown';
  return {
    entry,
    evidence,
    oos: multi ? toNumber(multi.mean_oos_raw) : toNumber(entry.walk_forward?.out_of_sample_return_raw),
    buyHold: multi ? toNumber(multi.buy_and_hold_mean_raw) : null,
    excess: multi ? toNumber(multi.mean_excess_return_raw) : null,
    folds: multi?.fold_count ?? (multi?.folds?.length || null),
    profitable: multi?.profitable ?? null,
    fills: multi ? multi.total_oos_fills : (single?.fills ?? null),
    headroom: multi?.cost_headroom ?? single?.cost_headroom ?? null,
    breakeven: multi?.mean_breakeven_cost ?? single?.breakeven_cost ?? null,
  };
};

type SortKey = 'date' | 'oos' | 'excess';

/**
 * Side-by-side comparison of archived runs.
 *
 * A single walk-forward answers "did this robot work on this window". Research needs the
 * other question too — "which of these, if any, is better" — and a baseline row makes the
 * answer readable: a positive out-of-sample return that still trails buy&hold is not a win.
 */
export const RunsCompare: React.FC<RunsCompareProps> = ({ refreshKey = 0 }) => {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [onlyOutOfSample, setOnlyOutOfSample] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchResearchHistory(40);
      setEntries(data.history);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load experiment history');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [refreshKey]);

  const rows = useMemo(() => {
    const mapped = entries.map(toRow);
    const filtered = onlyOutOfSample
      ? mapped.filter((row) => row.evidence === 'out-of-sample')
      : mapped;
    const sorted = [...filtered];
    sorted.sort((a, b) => {
      if (sortKey === 'date') {
        return (b.entry.finished_at ?? '').localeCompare(a.entry.finished_at ?? '');
      }
      const key = sortKey;
      const left = a[key] ?? Number.NEGATIVE_INFINITY;
      const right = b[key] ?? Number.NEGATIVE_INFINITY;
      return right - left;
    });
    return sorted;
  }, [entries, onlyOutOfSample, sortKey]);

  const compared = rows.filter((row) => selected.includes(row.entry.history_id));
  const chartRows = compared.length > 0 ? compared : rows.slice(0, 6);
  const chartMax = Math.max(
    ...chartRows.flatMap((row) => [Math.abs(row.oos ?? 0), Math.abs(row.buyHold ?? 0)]),
    0.0001,
  );

  const toggle = (historyId: string) => {
    setSelected((prev) =>
      prev.includes(historyId)
        ? prev.filter((id) => id !== historyId)
        : prev.length >= 4
          ? [...prev.slice(1), historyId]
          : [...prev, historyId],
    );
  };

  const handleCopyMarkdown = () => {
    const targetRows = compared.length > 0 ? compared : rows.slice(0, 8);
    if (targetRows.length === 0) return;

    const lines: string[] = [
      '### Nautilus Lab Experiments Comparison',
      `*Compared ${targetRows.length} runs on ${new Date().toISOString().slice(0, 10)}*`,
      '',
      '| Robot | Run Type | Date | Evidence | OOS Return | Buy & Hold | Excess | Folds | Fills | Headroom |',
      '|---|---|---|---|---|---|---|---|---|---|',
    ];

    targetRows.forEach((r) => {
      const e = r.entry;
      lines.push(
        `| **${e.robot}** | \`${e.run_type}\` | ${e.finished_at?.slice(0, 16) ?? 'n/a'} | ${r.evidence} | **${formatPct(r.oos)}** | ${formatPct(r.buyHold)} | ${formatPct(r.excess)} | ${r.folds ?? '1'} | ${r.fills ?? 0} | ${formatBps(r.headroom)} |`,
      );
    });

    navigator.clipboard.writeText(lines.join('\n'));
    setCopiedMd(true);
    setTimeout(() => setCopiedMd(false), 2500);
  };

  const evidenceTag = (evidence: CompareRow['evidence']) => {
    switch (evidence) {
      case 'out-of-sample':
        return 'bg-emerald-950/60 text-emerald-400 border-emerald-800/50';
      case 'in-sample-only':
        return 'bg-amber-950/60 text-amber-400 border-amber-800/50';
      case 'overfitting-audit':
        return 'bg-purple-950/60 text-purple-300 border-purple-800/50';
      default:
        return 'bg-gray-950 text-gray-500 border-gray-800';
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <GitCompare className="w-4 h-4 text-cyan-400" />
          <h3 className="text-sm font-bold text-gray-100">Compare runs</h3>
          <span className="text-[11px] text-gray-500">
            {entries.length} archived · pick up to 4 ({selected.length} selected)
          </span>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleCopyMarkdown}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-mono bg-gray-950 hover:bg-gray-800 border border-gray-800 text-gray-300 transition-colors"
            title="Copy comparison table as Markdown"
          >
            {copiedMd ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copiedMd ? 'Copied Table' : 'Copy Table'}</span>
          </button>
          <label className="flex items-center gap-1.5 text-[11px] text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={onlyOutOfSample}
              onChange={(e) => setOnlyOutOfSample(e.target.checked)}
              className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
            />
            out-of-sample only
          </label>
          <button
            type="button"
            onClick={() => setSortKey(sortKey === 'date' ? 'excess' : sortKey === 'excess' ? 'oos' : 'date')}
            className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 font-mono"
            title="Cycle sort: date -> excess -> OOS"
          >
            <ArrowDownUp className="w-3.5 h-3.5" />
            sort: {sortKey}
          </button>
          <button
            type="button"
            onClick={load}
            className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-red-950/30 border border-red-800/40 text-red-300 text-xs">
          {error}
        </div>
      )}

      {rows.length === 0 ? (
        <p className="text-xs text-gray-500">
          {onlyOutOfSample
            ? 'No out-of-sample runs archived yet. Run a walk-forward with 2+ folds.'
            : 'No archived runs yet. Finish a research job to populate history.'}
        </p>
      ) : (
        <>
          <div className="overflow-x-auto border border-gray-800 rounded-xl">
            <table className="w-full text-[11px] font-mono">
              <thead className="bg-gray-950/80 text-gray-400">
                <tr>
                  <th className="p-2"></th>
                  <th className="text-left p-2">robot</th>
                  <th className="text-left p-2">run</th>
                  <th className="text-left p-2">evidence</th>
                  <th className="text-right p-2">OOS mean</th>
                  <th className="text-right p-2">buy&hold</th>
                  <th className="text-right p-2">excess</th>
                  <th className="text-right p-2">fold wins</th>
                  <th className="text-right p-2">fills</th>
                  <th className="text-right p-2">breakeven</th>
                  <th className="text-right p-2">headroom</th>
                  <th className="text-left p-2">finished</th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                {rows.map((row) => (
                  <tr
                    key={row.entry.history_id}
                    className={`border-t border-gray-800/70 ${
                      selected.includes(row.entry.history_id) ? 'bg-blue-950/20' : ''
                    }`}
                  >
                    <td className="p-2">
                      <input
                        type="checkbox"
                        checked={selected.includes(row.entry.history_id)}
                        onChange={() => toggle(row.entry.history_id)}
                        className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
                      />
                    </td>
                    <td className="p-2 text-blue-300">{row.entry.robot}</td>
                    <td className="p-2 text-gray-400">{row.entry.run_type}</td>
                    <td className="p-2">
                      <span className={`px-1.5 py-0.5 rounded border text-[10px] ${evidenceTag(row.evidence)}`}>
                        {row.evidence}
                      </span>
                    </td>
                    <td className="p-2 text-right">{row.oos == null ? 'n/a' : formatPct(row.oos)}</td>
                    <td className="p-2 text-right">{row.buyHold == null ? 'n/a' : formatPct(row.buyHold)}</td>
                    <td
                      className={`p-2 text-right ${
                        row.excess == null ? '' : row.excess > 0 ? 'text-emerald-400' : 'text-red-400'
                      }`}
                    >
                      {row.excess == null ? 'n/a' : formatPct(row.excess)}
                    </td>
                    <td className="p-2 text-right">{row.profitable ?? (row.folds ? `0/${row.folds}` : 'n/a')}</td>
                    <td className="p-2 text-right">{row.fills ?? 'n/a'}</td>
                    <td className="p-2 text-right">{formatBps(row.breakeven)}</td>
                    <td
                      className={`p-2 text-right ${
                        row.headroom == null ? '' : row.headroom > 0 ? 'text-emerald-400' : 'text-red-400'
                      }`}
                    >
                      {formatBps(row.headroom)}
                    </td>
                    <td className="p-2 text-gray-500 whitespace-nowrap">
                      {formatDateTime(row.entry.finished_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-2">
            <h4 className="text-[11px] font-semibold text-gray-300 uppercase tracking-wider">
              {compared.length > 0 ? 'Selected runs' : 'Most recent runs'} — out-of-sample vs buy&hold
            </h4>
            <div className="flex flex-col gap-1.5">
              {chartRows.map((row) => (
                <div key={row.entry.history_id} className="flex items-center gap-2 text-[11px] font-mono">
                  <span className="w-40 truncate text-gray-400" title={`${row.entry.robot} ${row.entry.run_type}`}>
                    {row.entry.robot}·{row.entry.finished_at?.slice(5, 16) ?? ''}
                  </span>
                  <div className="flex-1 flex flex-col gap-0.5">
                    <div className="h-3 bg-gray-950 rounded-sm relative">
                      <div
                        className={`h-3 rounded-sm ${
                          (row.oos ?? 0) >= 0 ? 'bg-emerald-500/80' : 'bg-red-500/80'
                        }`}
                        style={{
                          width: `${Math.min(Math.abs(row.oos ?? 0) / chartMax, 1) * 100}%`,
                        }}
                      />
                    </div>
                    {row.buyHold != null && (
                      <div className="h-2 bg-gray-950 rounded-sm relative">
                        <div
                          className="h-2 rounded-sm bg-gray-500/60"
                          style={{
                            width: `${Math.min(Math.abs(row.buyHold) / chartMax, 1) * 100}%`,
                          }}
                        />
                      </div>
                    )}
                  </div>
                  <span className="w-16 text-right text-gray-300">
                    {row.oos == null ? 'n/a' : formatPct(row.oos)}
                  </span>
                  <span className="w-16 text-right text-gray-500">
                    {row.buyHold == null ? '—' : formatPct(row.buyHold)}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-gray-600">
              Bars are scaled to the largest absolute value on screen; the thin bar is buy&hold.
            </p>
          </div>
        </>
      )}
    </div>
  );
};
