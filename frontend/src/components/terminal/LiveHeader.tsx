import React from 'react';
import { Play, ShieldAlert, Square, Zap } from 'lucide-react';

interface LiveHeaderProps {
  mode: 'paper' | 'live_guarded';
  onModeSwitch: (mode: 'paper' | 'live_guarded') => void;
  isConnected: boolean;
  isActive?: boolean;
  onStartSession: () => void;
  onStopSession: () => void;
  actionError?: string | null;
}

export const LiveHeader: React.FC<LiveHeaderProps> = ({
  mode,
  onModeSwitch,
  isConnected,
  isActive = false,
  onStartSession,
  onStopSession,
  actionError,
}) => {
  return (
    <>
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4 bg-[#0d131f] border border-gray-800 p-4 rounded-2xl">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-blue-600/10 border border-blue-500/20 rounded-xl">
            <Zap className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-gray-100">Live Trading Terminal</h2>
              <span
                className={`px-2 py-0.5 text-[10px] font-bold tracking-wider rounded-md uppercase border ${
                  mode === 'paper'
                    ? 'bg-amber-950/40 text-amber-300 border-amber-800/40'
                    : 'bg-red-950/50 text-red-300 border-red-800/50'
                }`}
              >
                {mode === 'paper' ? 'Paper Simulation' : 'Live Monitor (Guarded)'}
              </span>
            </div>
            <p className="text-xs text-gray-400 mt-0.5">
              Real-time candlestick charts, visual SL/TP triggers & dynamic position risk control.
            </p>
          </div>
        </div>

        {/* Mode Selector & Status */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Mode Toggle Button */}
          <div className="bg-gray-950 border border-gray-800 p-1 rounded-xl flex items-center">
            <button
              type="button"
              onClick={() => onModeSwitch('paper')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'paper'
                  ? 'bg-amber-600/20 text-amber-300 border border-amber-500/30'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Paper Simulator
            </button>
            <button
              type="button"
              onClick={() => onModeSwitch('live_guarded')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'live_guarded'
                  ? 'bg-red-600/20 text-red-300 border border-red-500/30'
                  : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              Live Trading
            </button>
          </div>

          {/* Connection Indicator */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-950 border border-gray-800 rounded-xl text-xs font-mono">
            <span
              className={`w-2 h-2 rounded-full ${
                isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'
              }`}
            />
            <span className={isConnected ? 'text-gray-300' : 'text-red-400'}>
              {isConnected ? 'Stream Active' : 'Disconnected'}
            </span>
          </div>

          {/* Start / Stop Session */}
          {isActive ? (
            <button
              type="button"
              onClick={onStopSession}
              className="flex items-center gap-2 px-4 py-2 bg-red-950/60 hover:bg-red-900/60 text-red-200 border border-red-800/50 rounded-xl text-xs font-semibold transition-colors"
            >
              <Square className="w-3.5 h-3.5" /> Stop Session
            </button>
          ) : (
            <button
              type="button"
              onClick={onStartSession}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-xs font-semibold transition-colors shadow-lg shadow-emerald-900/20"
            >
              <Play className="w-3.5 h-3.5" /> Start Live Paper
            </button>
          )}
        </div>
      </div>

      {/* Safety Notice for Live Guarded mode */}
      {mode === 'live_guarded' && (
        <div className="p-3.5 rounded-xl bg-red-950/30 border border-red-800/40 flex items-start gap-3 text-xs text-red-200">
          <ShieldAlert className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-red-300">Live Trading Guard: Active. </span>
            In accordance with project architecture (AGENTS.md), real execution adapters are
            fail-closed. You receive real-time exchange prices and see live strategy signals, but no
            real capital or API keys reach an external exchange.
          </div>
        </div>
      )}

      {actionError && (
        <div className="p-3 rounded-xl bg-red-950/30 border border-red-800/50 text-red-300 text-xs">
          {actionError}
        </div>
      )}
    </>
  );
};
