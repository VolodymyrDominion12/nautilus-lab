import React from 'react';
import { overridePairs, type PlannedCell } from '../../lib/batch';

interface BatchPlanPreviewProps {
  plan: PlannedCell[];
}

export const BatchPlanPreview: React.FC<BatchPlanPreviewProps> = ({ plan }) => {
  const runnableCount = plan.filter((cell) => cell.runnable).length;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] text-gray-500">
        Прогонів до запуску: <span className="text-emerald-400">{runnableCount}</span>, заблоковано:{' '}
        <span className="text-amber-400">{plan.length - runnableCount}</span>. Заблокований прогін
        не стартує — причина вказана в плані (немає серії барів, перп-ноги, серії фандингу чи
        моделі).
      </p>
      <table className="w-full text-[11px] font-mono">
        <thead className="text-gray-500">
          <tr>
            <th className="text-left py-1">Прогін</th>
            <th className="text-left">Інструмент</th>
            <th className="text-left">TF</th>
            <th className="text-left">Каталог</th>
            <th className="text-left">Параметри</th>
            <th className="text-left">Витрати</th>
            <th className="text-left">Стан</th>
          </tr>
        </thead>
        <tbody>
          {plan.map((cell) => (
            <tr key={cell.cell_id} className="border-t border-gray-800">
              <td className="py-1 text-gray-200">{cell.cell_id}</td>
              <td className="text-gray-400">{cell.instrument_id ?? cell.symbol}</td>
              <td className="text-gray-400">{cell.interval}</td>
              <td className="text-gray-400">{cell.catalog}</td>
              {/* A sweep is only readable here if the value is spelled out next to the cell. */}
              <td className="text-[10px] text-gray-300">
                {overridePairs(cell.env)
                  .map(([key, value]) => `${key}=${value}`)
                  .join(' ') || '—'}
              </td>
              <td className="font-mono text-[10px] text-gray-400">{cell.cost_profile ?? '—'}</td>
              <td className={cell.runnable ? 'text-emerald-400' : 'text-amber-400'}>
                {cell.runnable ? 'буде запущено' : cell.blocked}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
