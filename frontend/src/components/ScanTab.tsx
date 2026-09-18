import React, { useState } from 'react';
import { ArrowLeftRight, Play, RefreshCw, TriangleAlert } from 'lucide-react';
import { scanTriangular } from '../services/api';

interface ScanResult {
  status: string;
  message?: string;
  triangular_opportunities?: number;
}

/**
 * UI for `lab scan --triangular`.
 *
 * The scan is intentionally read-only and never executes orders. It finds
 * price-path anomalies in a static rate table — the current implementation
 * always returns 0, which the UI explains rather than hides.
 */
export const ScanTab: React.FC = () => {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleScan = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const data = (await scanTriangular()) as ScanResult;
      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setRunning(false);
    }
  };

  const opportunities = result?.triangular_opportunities ?? null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
          <ArrowLeftRight className="w-6 h-6 text-cyan-400" />
          Arbitrage Scanner
        </h2>
        <p className="text-sm text-gray-400 mt-1">
          Scans a static rate table for triangular arbitrage paths.{' '}
          <span className="font-mono text-xs">lab scan --triangular</span>
        </p>
      </div>

      {/* Explanation banner */}
      <div className="p-4 bg-blue-950/30 border border-blue-800/40 rounded-2xl text-xs text-blue-300 leading-relaxed">
        <span className="font-semibold">What this does:</span> Enumerates all 3-leg currency paths
        through hardcoded rates and reports paths where round-trip return{' >'} 1. The current
        implementation always returns 0 — this is intentional (a demonstration scaffold, not a live
        feed). Connect a live quote stream and replace the rate table to get real signals.
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col gap-5">
        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={handleScan}
            disabled={running}
            className="px-5 py-2.5 bg-cyan-700 hover:bg-cyan-600 disabled:bg-gray-800 disabled:text-gray-500 text-white font-medium rounded-xl transition-colors flex items-center gap-2"
          >
            {running ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {running ? 'Scanning\u2026' : 'Run Triangular Scan'}
          </button>
          <span className="text-xs text-gray-500 font-mono">
            CLI: <span className="text-gray-300">lab scan --triangular</span>
          </span>
        </div>

        {error && (
          <div className="p-3 bg-red-950/40 border border-red-800/60 rounded-xl text-red-300 text-xs flex items-start gap-2">
            <TriangleAlert className="w-4 h-4 shrink-0 mt-0.5" />
            {error}
          </div>
        )}

        {result && (
          <div className="flex flex-col gap-4">
            <div
              className={`p-5 rounded-2xl border flex flex-col gap-2 ${
                opportunities != null && opportunities > 0
                  ? 'bg-emerald-950/40 border-emerald-800/50'
                  : 'bg-gray-950 border-gray-800'
              }`}
            >
              <div className="flex items-center gap-3">
                <span
                  className={`text-4xl font-mono font-bold ${
                    opportunities != null && opportunities > 0
                      ? 'text-emerald-400'
                      : 'text-gray-300'
                  }`}
                >
                  {opportunities ?? '\u2014'}
                </span>
                <div>
                  <div className="text-sm font-semibold text-gray-100">
                    triangular {opportunities === 1 ? 'opportunity' : 'opportunities'} found
                  </div>
                  {opportunities === 0 && (
                    <div className="text-xs text-gray-500 mt-0.5">
                      No profitable 3-leg paths in the current rate table.
                    </div>
                  )}
                </div>
                {opportunities != null && opportunities > 0 && (
                  <span className="ml-auto w-3 h-3 rounded-full bg-emerald-400 animate-pulse" />
                )}
              </div>
              {result.message && (
                <p className="text-xs text-gray-400 border-t border-gray-800/60 pt-2 mt-1">
                  {result.message}
                </p>
              )}
            </div>

            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span
                className={`px-2 py-0.5 rounded-full border font-mono text-[11px] ${
                  result.status === 'success'
                    ? 'bg-emerald-950/40 border-emerald-800/40 text-emerald-400'
                    : 'bg-gray-900 border-gray-800 text-gray-400'
                }`}
              >
                {result.status}
              </span>
              <span>No orders are submitted \u2014 read-only scan.</span>
            </div>
          </div>
        )}

        {!result && !running && !error && (
          <div className="flex flex-col items-center justify-center py-10 text-gray-600 text-sm gap-2">
            <ArrowLeftRight className="w-10 h-10 text-gray-700" />
            <span>Press \u00abRun Triangular Scan\u00bb to check for price-path anomalies.</span>
          </div>
        )}
      </div>

      <div className="p-4 bg-gray-900 border border-gray-800 rounded-2xl text-xs text-gray-500 leading-relaxed">
        <span className="font-semibold text-gray-400">Architecture:</span> The scanner runs
        synchronously and returns immediately. To extend it, edit{' '}
        <span className="font-mono text-gray-300">interfaces/cli.py \u2192 lab scan</span>{' '}
        and the corresponding API handler.
      </div>
    </div>
  );
};
