import React from 'react';
import { InfoTooltip } from '../InfoTooltip';

interface SessionConfigCardProps {
  sessionName: string;
  setSessionName: (val: string) => void;
  sessionNotes: string;
  setSessionNotes: (val: string) => void;
  robot: string;
  setRobot: (val: string) => void;
  supportedRobots: string[];
  startingEquity: string;
  setStartingEquity: (val: string) => void;
  riskPct: string;
  setRiskPct: (val: string) => void;
  stopPct: string;
  setStopPct: (val: string) => void;
  tpMultiple: string;
  setTpMultiple: (val: string) => void;
  autoTrade: boolean;
  setAutoTrade: (val: boolean) => void;
  isActive?: boolean;
  symbol: string;
}

export const SessionConfigCard: React.FC<SessionConfigCardProps> = ({
  sessionName,
  setSessionName,
  sessionNotes,
  setSessionNotes,
  robot,
  setRobot,
  supportedRobots,
  startingEquity,
  setStartingEquity,
  riskPct,
  setRiskPct,
  stopPct,
  setStopPct,
  tpMultiple,
  setTpMultiple,
  autoTrade,
  setAutoTrade,
  isActive = false,
  symbol,
}) => {
  return (
    <div className="bg-[#0d131f] border border-gray-800 p-4 rounded-2xl space-y-3">
      <span className="text-xs font-semibold text-gray-300 block">Конфігурація сесії (Config)</span>

      <div className="space-y-2 text-xs">
        <div>
          <label className="text-[10px] text-gray-400 block mb-1">Назва сесії</label>
          <input
            type="text"
            value={sessionName}
            onChange={(e) => setSessionName(e.target.value)}
            disabled={isActive}
            placeholder={`${robot}-${symbol.replace('USDT', '').toLowerCase()}`}
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs disabled:opacity-50 text-gray-200 font-mono"
          />
        </div>
        <div>
          <label className="text-[10px] text-gray-400 block mb-1">
            Гіпотеза / критерій зупинки
          </label>
          <textarea
            value={sessionNotes}
            onChange={(e) => setSessionNotes(e.target.value)}
            disabled={isActive}
            rows={2}
            placeholder="напр. випереджає hold-eth з урахуванням комісій протягом 60 днів, інакше відхилити"
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs disabled:opacity-50 text-gray-200"
          />
        </div>
        <div>
          <label className="text-[10px] text-gray-400 block mb-1">Торговий робот</label>
          <select
            value={robot}
            onChange={(e) => setRobot(e.target.value)}
            disabled={isActive}
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs disabled:opacity-50 text-gray-200"
          >
            {supportedRobots.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-[10px] text-gray-400 block mb-1">Початковий капітал ($)</label>
          <input
            type="number"
            value={startingEquity}
            onChange={(e) => setStartingEquity(e.target.value)}
            disabled={isActive}
            className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2.5 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
          />
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="flex items-center gap-1 mb-1">
              <label className="text-[10px] text-gray-400 block">Ризик (%)</label>
              <InfoTooltip term="risk_per_trade" size="xs" />
            </div>
            <input
              type="number"
              step="0.005"
              value={riskPct}
              onChange={(e) => setRiskPct(e.target.value)}
              disabled={isActive}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
            />
          </div>
          <div>
            <div className="flex items-center gap-1 mb-1">
              <label className="text-[10px] text-gray-400 block">Stop Loss (%)</label>
              <InfoTooltip term="stop_loss" size="xs" />
            </div>
            <input
              type="number"
              step="0.005"
              value={stopPct}
              onChange={(e) => setStopPct(e.target.value)}
              disabled={isActive}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
            />
          </div>
          <div>
            <div className="flex items-center gap-1 mb-1">
              <label className="text-[10px] text-gray-400 block">TP Multiple</label>
              <InfoTooltip term="take_profit" size="xs" />
            </div>
            <input
              type="number"
              step="0.5"
              value={tpMultiple}
              onChange={(e) => setTpMultiple(e.target.value)}
              disabled={isActive}
              className="w-full bg-gray-950 border border-gray-800 rounded-xl px-2 py-1.5 text-xs font-mono disabled:opacity-50 text-gray-200"
            />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-gray-400">Автономне виконання</span>
          <input
            type="checkbox"
            checked={autoTrade}
            onChange={(e) => setAutoTrade(e.target.checked)}
            disabled={isActive}
            className="rounded bg-gray-950 border-gray-800 text-blue-600 focus:ring-0"
          />
        </div>
      </div>
    </div>
  );
};
