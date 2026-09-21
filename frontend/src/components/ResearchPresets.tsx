import React from 'react';
import {
  Cpu,
  Flame,
  Gauge,
  Layers,
  Sparkles,
  Zap,
} from 'lucide-react';

export interface ResearchPresetConfig {
  id: string;
  name: string;
  description: string;
  badge: string;
  badgeColor: string;
  icon: React.ReactNode;
  config: {
    robot?: string;
    source?: 'catalog' | 'synthetic';
    bars?: number;
    folds?: number;
    isFraction?: number;
    embargoBars?: number;
    useOptuna?: boolean;
    optunaTrials?: number;
    usePbo?: boolean;
    pboBlocks?: number;
    barVpin?: boolean;
    tickVpin?: boolean;
    hawkes?: boolean;
    stressSlice?: string;
    generateTearsheet?: boolean;
    fullSample?: boolean;
    windowMode?: 'fraction' | 'custom';
  };
}

const PRESETS: ResearchPresetConfig[] = [
  {
    id: 'wf-4fold',
    name: '4-Fold Walk-Forward',
    description: 'Gold standard test: 4 rolling unseen out-of-sample windows against Buy & Hold.',
    badge: 'Recommended',
    badgeColor: 'bg-blue-950/60 text-blue-300 border-blue-800/40',
    icon: <Layers className="w-4 h-4 text-blue-400" />,
    config: {
      source: 'catalog',
      folds: 4,
      isFraction: 0.7,
      embargoBars: 10,
      useOptuna: false,
      usePbo: false,
      barVpin: false,
      tickVpin: false,
      hawkes: false,
      stressSlice: '',
      generateTearsheet: true,
      fullSample: false,
      windowMode: 'fraction',
    },
  },
  {
    id: 'optuna-bayes',
    name: 'Optuna Bayesian Search',
    description: 'Automated 25-trial parameter optimization with purged CV on 3 folds.',
    badge: 'Bayesian',
    badgeColor: 'bg-emerald-950/60 text-emerald-300 border-emerald-800/40',
    icon: <Sparkles className="w-4 h-4 text-emerald-400" />,
    config: {
      source: 'catalog',
      folds: 3,
      isFraction: 0.7,
      embargoBars: 10,
      useOptuna: true,
      optunaTrials: 25,
      usePbo: false,
      generateTearsheet: true,
      fullSample: false,
      windowMode: 'fraction',
    },
  },
  {
    id: 'pbo-audit',
    name: 'PBO Overfitting Audit',
    description: 'CSCV with 8 blocks: measures selection probability without PnL illusions.',
    badge: 'PBO / CSCV',
    badgeColor: 'bg-purple-950/60 text-purple-300 border-purple-800/40',
    icon: <Gauge className="w-4 h-4 text-purple-400" />,
    config: {
      source: 'catalog',
      usePbo: true,
      pboBlocks: 8,
      useOptuna: false,
      generateTearsheet: false,
      fullSample: false,
      windowMode: 'fraction',
    },
  },
  {
    id: 'hawkes-flow',
    name: 'Hawkes & Tick VPIN',
    description: 'Clustered-flow intensity gate and tick aggressor split on regime router.',
    badge: 'Microstructure',
    badgeColor: 'bg-cyan-950/60 text-cyan-300 border-cyan-800/40',
    icon: <Zap className="w-4 h-4 text-cyan-400" />,
    config: {
      robot: 'regime',
      source: 'catalog',
      folds: 2,
      isFraction: 0.7,
      embargoBars: 10,
      hawkes: true,
      tickVpin: true,
      barVpin: false,
      usePbo: false,
      useOptuna: false,
      generateTearsheet: true,
      fullSample: false,
      windowMode: 'fraction',
    },
  },
  {
    id: 'stress-ftx',
    name: 'FTX Crash Stress Slice',
    description: 'Runs on the historical 2022 FTX collapse window to test survival in panic regimes.',
    badge: 'Stress',
    badgeColor: 'bg-red-950/60 text-red-300 border-red-800/40',
    icon: <Flame className="w-4 h-4 text-red-400" />,
    config: {
      source: 'catalog',
      stressSlice: 'ftx_collapse',
      folds: 1,
      isFraction: 0.7,
      embargoBars: 10,
      useOptuna: false,
      usePbo: false,
      generateTearsheet: true,
      fullSample: false,
      windowMode: 'fraction',
    },
  },
  {
    id: 'synthetic-smoke',
    name: 'Synthetic Smoke Test',
    description: 'Fast offline run with 3,000 synthetic bars: no catalog download needed.',
    badge: 'Offline',
    badgeColor: 'bg-gray-800/80 text-gray-300 border-gray-700/50',
    icon: <Cpu className="w-4 h-4 text-gray-400" />,
    config: {
      source: 'synthetic',
      bars: 3000,
      folds: 2,
      isFraction: 0.7,
      embargoBars: 10,
      useOptuna: false,
      usePbo: false,
      barVpin: false,
      tickVpin: false,
      hawkes: false,
      stressSlice: '',
      generateTearsheet: true,
      fullSample: false,
      windowMode: 'fraction',
    },
  },
];

interface ResearchPresetsProps {
  onApplyPreset: (preset: ResearchPresetConfig) => void;
  activePresetId?: string | null;
}

export const ResearchPresets: React.FC<ResearchPresetsProps> = ({
  onApplyPreset,
  activePresetId,
}) => {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-blue-400" />
          Research Presets
        </span>
        <span className="text-[10px] text-gray-500">1-click quant experiment configs</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {PRESETS.map((preset) => {
          const isActive = activePresetId === preset.id;
          return (
            <button
              type="button"
              key={preset.id}
              onClick={() => onApplyPreset(preset)}
              className={`p-2.5 rounded-xl border text-left flex flex-col justify-between transition-all group ${
                isActive
                  ? 'bg-blue-950/40 border-blue-500/50 ring-1 ring-blue-500/30'
                  : 'bg-gray-950/70 border-gray-800/70 hover:border-gray-700 hover:bg-gray-900/80'
              }`}
            >
              <div className="flex items-center justify-between gap-1 mb-1">
                <span className="p-1 rounded-lg bg-gray-900 border border-gray-800/80 group-hover:scale-105 transition-transform">
                  {preset.icon}
                </span>
                <span
                  className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${preset.badgeColor}`}
                >
                  {preset.badge}
                </span>
              </div>

              <div>
                <div className="text-xs font-bold text-gray-200 group-hover:text-blue-300 transition-colors line-clamp-1">
                  {preset.name}
                </div>
                <div className="text-[10px] text-gray-500 line-clamp-2 mt-0.5 leading-tight">
                  {preset.description}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
