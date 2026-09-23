import React, { useState, useMemo } from 'react';
import {
  BookOpen,
  Search,
  X,
  ShieldAlert,
} from 'lucide-react';
import { GLOSSARY } from '../lib/glossary';
import type { GlossaryEntry, GlossaryKey } from '../lib/glossary';

interface InterfaceGuideModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTerm?: GlossaryKey;
}

type CategoryFilter = 'all' | 'metric' | 'methodology' | 'module' | 'safety' | 'rules';

export const InterfaceGuideModal: React.FC<InterfaceGuideModalProps> = ({
  isOpen,
  onClose,
}) => {
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<CategoryFilter>('all');

  const filteredEntries = useMemo(() => {
    const q = search.toLowerCase().trim();
    const entries = Object.entries(GLOSSARY) as [GlossaryKey, GlossaryEntry][];

    return entries.filter(([, item]) => {
      const matchesCategory =
        selectedCategory === 'all' ||
        (selectedCategory !== 'rules' && item.category === selectedCategory);

      if (!matchesCategory) return false;

      if (!q) return true;
      return (
        item.title.toLowerCase().includes(q) ||
        (item.subtitle && item.subtitle.toLowerCase().includes(q)) ||
        item.description.toLowerCase().includes(q) ||
        (item.interpretation && item.interpretation.toLowerCase().includes(q)) ||
        (item.formula && item.formula.toLowerCase().includes(q))
      );
    });
  }, [search, selectedCategory]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in">
      <div
        className="bg-[#0b101d] border border-gray-800 rounded-3xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden"
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="p-6 border-b border-gray-800 flex items-center justify-between gap-4 bg-gray-950/60">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-blue-600/10 border border-blue-500/20 rounded-2xl text-blue-400">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-100 flex items-center gap-2">
                Довідник інтерфейсу та методології
                <span className="text-xs font-mono font-normal text-blue-400 bg-blue-950/60 px-2 py-0.5 rounded-full border border-blue-800/40">
                  Nautilus Lab
                </span>
              </h2>
              <p className="text-xs text-gray-400">
                Повне керівництво по метриках, розрахунках, правилах валідації та роботі модулів
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800/70 rounded-xl transition-colors"
            aria-label="Закрити довідник"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search & Category Filter Bar */}
        <div className="p-5 border-b border-gray-800/80 bg-gray-950/30 flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-gray-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Пошук метрик, формул або блоків (наприклад, PBO, Excess Return, Folds)..."
              className="w-full pl-10 pr-4 py-2 bg-gray-900 border border-gray-800 rounded-xl text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
            />
          </div>

          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0">
            {(
              [
                { id: 'all', label: 'Усі' },
                { id: 'metric', label: 'Метрики' },
                { id: 'methodology', label: 'Методологія' },
                { id: 'module', label: 'Модулі UI' },
                { id: 'safety', label: 'Безпека' },
                { id: 'rules', label: 'Правила Lab' },
              ] as const
            ).map((cat) => (
              <button
                type="button"
                key={cat.id}
                onClick={() => setSelectedCategory(cat.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                  selectedCategory === cat.id
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/40 border border-transparent'
                }`}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {selectedCategory === 'rules' && (
            <div className="space-y-4">
              <div className="p-4 bg-amber-950/20 border border-amber-800/40 rounded-2xl flex items-start gap-3">
                <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-bold text-amber-300">
                    Фундаментальні принципи дослідницької лабораторії
                  </h4>
                  <p className="text-xs text-amber-200/80 mt-1 leading-relaxed">
                    Nautilus Lab побудований на принципах наукового скептицизму. Будь-який бектест
                    вважається недійсним, поки він не доведе свою перевагу на незалежних даних (OOS) з
                    урахуванням комісій біржі.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                {[
                  {
                    num: '1',
                    title: 'In-Sample — лише вибір параметрів',
                    desc: 'Рядок in-sample ніколи не є результатом. Звіт і рішення — лише за out-of-sample (OOS).',
                  },
                  {
                    num: '2',
                    title: 'Порівнюй із Buy & Hold',
                    desc: 'Плюсовий PnL не має цінності, якщо пасивний ринок виріс більше. Справжня перевага — це Excess Return.',
                  },
                  {
                    num: '3',
                    title: 'Ніякої оптимізації на OOS',
                    desc: 'Параметри сітки та Optuna налаштовуються виключно на IS. OOS дивимось рівно один раз.',
                  },
                  {
                    num: '4',
                    title: 'Синтетика — лише smoke test',
                    desc: 'Синтетичні дані дають артефакти (+3000%). Вони потрібні лише щоб перевірити, що код не падає.',
                  },
                  {
                    num: '5',
                    title: 'Fail Closed захист капіталу',
                    desc: 'lab live свідомо заблоковано (вихід із кодом 1). Торговий адаптер виконання відсутній.',
                  },
                  {
                    num: '6',
                    title: 'Ніяких LLM на гарячому шляху',
                    desc: 'Моделі живуть лише в офлайн-контурі (propose, гіпотези). Виклик LLM під час бектесту заборонений.',
                  },
                ].map((rule) => (
                  <div
                    key={rule.num}
                    className="p-4 bg-gray-900/60 border border-gray-800 rounded-2xl flex items-start gap-3"
                  >
                    <span className="w-6 h-6 rounded-full bg-blue-600/20 text-blue-400 font-mono text-xs font-bold flex items-center justify-center shrink-0">
                      {rule.num}
                    </span>
                    <div>
                      <h5 className="text-xs font-bold text-gray-200">{rule.title}</h5>
                      <p className="text-[11px] text-gray-400 mt-1 leading-relaxed">{rule.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {selectedCategory !== 'rules' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredEntries.length === 0 ? (
                <div className="col-span-2 py-12 text-center text-gray-500 text-xs">
                  За запитом &laquo;{search}&raquo; нічого не знайдено.
                </div>
              ) : (
                filteredEntries.map(([key, entry]) => (
                  <div
                    key={key}
                    className="bg-gray-900/80 border border-gray-800/90 hover:border-gray-700/80 transition-all rounded-2xl p-4 flex flex-col gap-2.5 shadow-sm"
                  >
                    {/* Entry Header */}
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h4 className="text-sm font-bold text-gray-100">{entry.title}</h4>
                        {entry.subtitle && (
                          <span className="text-[11px] text-gray-400 font-medium block">
                            {entry.subtitle}
                          </span>
                        )}
                      </div>
                      <span
                        className={`text-[9px] font-mono px-2 py-0.5 rounded border uppercase tracking-wider shrink-0 ${
                          entry.importance === 'critical'
                            ? 'bg-red-950/60 text-red-300 border-red-800/50'
                            : entry.category === 'metric'
                              ? 'bg-blue-950/60 text-blue-300 border-blue-800/50'
                              : entry.category === 'safety'
                                ? 'bg-amber-950/60 text-amber-300 border-amber-800/50'
                                : 'bg-purple-950/60 text-purple-300 border-purple-800/50'
                        }`}
                      >
                        {entry.category}
                      </span>
                    </div>

                    {/* Formula */}
                    {entry.formula && (
                      <div className="bg-gray-950 px-2.5 py-1.5 rounded-lg border border-gray-800 font-mono text-[10px] text-cyan-300 overflow-x-auto whitespace-pre-wrap">
                        {entry.formula}
                      </div>
                    )}

                    {/* Description */}
                    <p className="text-xs text-gray-300 leading-relaxed whitespace-pre-line">
                      {entry.description}
                    </p>

                    {/* Interpretation */}
                    {entry.interpretation && (
                      <div className="mt-auto bg-blue-950/20 border-l-2 border-blue-500/80 pl-2.5 py-1.5 rounded-r-lg text-[11px] text-blue-200/90 whitespace-pre-line leading-relaxed">
                        <span className="font-semibold text-blue-400 block text-[9px] uppercase tracking-wider mb-0.5">
                          Як трактувати значення:
                        </span>
                        {entry.interpretation}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-800 bg-gray-950/60 flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span>Nautilus Lab Research Engine · Documentation v1.0</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-xl bg-gray-900 border border-gray-800 text-gray-300 hover:text-white hover:bg-gray-800 transition-colors"
          >
            Закрити
          </button>
        </div>
      </div>
    </div>
  );
};
