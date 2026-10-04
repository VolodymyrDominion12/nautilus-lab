import React from 'react';
import { ROBOTS } from '../../lib/batchForm';

interface BatchMatrixSelectorsProps {
  robots: string[];
  setRobots: React.Dispatch<React.SetStateAction<string[]>>;
  symbols: string[];
  setSymbols: React.Dispatch<React.SetStateAction<string[]>>;
  extraSymbols: string;
  setExtraSymbols: (v: string) => void;
  availableSymbols: string[];
  inCatalogSymbols: string[];
  catalog: string;
}

export const BatchMatrixSelectors: React.FC<BatchMatrixSelectorsProps> = ({
  robots,
  setRobots,
  symbols,
  setSymbols,
  extraSymbols,
  setExtraSymbols,
  availableSymbols,
  inCatalogSymbols,
  catalog,
}) => {
  const chip = (active: boolean) =>
    `px-2.5 py-1 rounded-lg text-xs font-mono border transition-colors cursor-pointer ${
      active
        ? 'bg-blue-600/20 text-blue-300 border-blue-500/40'
        : 'bg-gray-950 text-gray-500 border-gray-800 hover:text-gray-300'
    }`;
  const input =
    'bg-gray-950 border border-gray-800 rounded-lg px-2 py-1 text-xs font-mono text-gray-200';

  const toggle = (list: string[], item: string, set: React.Dispatch<React.SetStateAction<string[]>>) =>
    set(list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);

  return (
    <>
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-wide text-gray-500">
            Роботи ({robots.length}/{ROBOTS.length})
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
              onClick={() => setRobots([...ROBOTS])}
            >
              Всі
            </button>
            <button
              type="button"
              className="text-[10px] text-gray-500 hover:text-gray-400 transition-colors"
              onClick={() => setRobots([])}
            >
              Очистити
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {ROBOTS.map((robot) => (
            <button
              key={robot}
              type="button"
              className={chip(robots.includes(robot))}
              onClick={() => toggle(robots, robot, setRobots)}
            >
              {robot}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-wide text-gray-500">
            Інструменти ({symbols.length}/{availableSymbols.length})
          </span>
          <div className="flex gap-2">
            {inCatalogSymbols.length > 0 && inCatalogSymbols.length < availableSymbols.length && (
              <button
                type="button"
                className="text-[10px] text-emerald-400 hover:text-emerald-300 transition-colors"
                onClick={() => setSymbols([...inCatalogSymbols])}
                title={`Обрати інструменти, присутні в каталозі «${catalog}»`}
              >
                У каталозі ({inCatalogSymbols.length})
              </button>
            )}
            <button
              type="button"
              className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
              onClick={() => setSymbols([...availableSymbols])}
            >
              Всі ({availableSymbols.length})
            </button>
            <button
              type="button"
              className="text-[10px] text-gray-500 hover:text-gray-400 transition-colors"
              onClick={() => setSymbols([])}
            >
              Очистити
            </button>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5 items-center">
          {availableSymbols.map((symbol) => {
            const inCatalog = inCatalogSymbols.length === 0 || inCatalogSymbols.includes(symbol);
            const selected = symbols.includes(symbol);
            return (
              <button
                key={symbol}
                type="button"
                className={`${chip(selected)} ${!inCatalog ? 'opacity-50 border-dashed' : ''}`}
                onClick={() => toggle(symbols, symbol, setSymbols)}
                title={inCatalog ? `Є в каталозі ${catalog}` : `Відсутній у каталозі ${catalog}`}
              >
                {symbol}
              </button>
            );
          })}
          <input
            className={`${input} w-36`}
            placeholder="ще: NEARUSDT…"
            value={extraSymbols}
            onChange={(e) => setExtraSymbols(e.target.value)}
          />
        </div>
      </div>
    </>
  );
};
