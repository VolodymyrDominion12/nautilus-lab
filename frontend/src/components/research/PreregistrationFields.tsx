import React from 'react';
import { InfoTooltip } from '../InfoTooltip';
import type { ResearchForm } from '../../lib/researchForm';

interface PreregistrationFieldsProps {
  register: ResearchForm['register'];
  promote: ResearchForm['promote'];
  source: ResearchForm['source'];
  update: (patch: Partial<ResearchForm>) => void;
}

/**
 * Pre-registration and candidate mode (docs/27 R-2, docs/35 §8 п.19).
 *
 * These two switches decide whether a run can ever be promoted, and both were previously
 * reachable only from the terminal (`lab research --register`, and no single command that
 * measures both halves of the gate). They sit together because they answer one question:
 * is this the deliberate final look, or an exploratory run that may not be promoted?
 */
export const PreregistrationFields: React.FC<PreregistrationFieldsProps> = ({
  register,
  promote,
  source,
  update,
}) => (
  <>
    <div className="flex flex-col gap-1 md:col-span-2">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] text-gray-400">
          Гіпотеза для пререєстрації (умови записуються ДО прогону)
        </span>
        <InfoTooltip
          title="Пререєстрація тесту"
          content="Умови тесту (робот, дані, сітка, вікна фолдів, пороги воріт) записуються у research/preregistrations/ до першого бектесту. Просунути далі може лише прогін, чиї умови збігаються з записаними — те саме робить `lab research --register`. Потрібні folds >= 2 і дані з каталогу."
          size="xs"
        />
      </div>
      <input
        type="text"
        value={register}
        onChange={(e) => update({ register: e.target.value })}
        placeholder="H: робот X має перевершити buy&hold у кожному OOS-вікні, бо …"
        className="bg-gray-950 border border-gray-800 text-xs text-gray-200 rounded-lg p-1.5"
      />
      <span className="text-[10px] text-gray-500">
        Порожнє поле — прогін без пререєстрації; у воротах він тоді читається як
        `preregistered=not measured`.
      </span>
    </div>

    {source === 'catalog' && (
      <div className="flex flex-col gap-1">
        <label className="flex items-center gap-2 cursor-pointer text-xs text-purple-300">
          <input
            type="checkbox"
            checked={promote}
            onChange={(e) =>
              // Candidate mode includes the audit, so the pbo-only run would make the backend
              // refuse the combination; turn it off instead of failing later.
              update({ promote: e.target.checked, usePbo: false })
            }
            className="rounded bg-gray-950 border-gray-700 text-purple-500 focus:ring-0"
          />
          Кандидат: додати аудит перенавчання (PBO/DSR)
        </label>
        <span className="text-[10px] text-gray-500">
          Ворота читають і фолди, і PBO/DSR — поодинокий `lab research` не дає обидві половини. Цей
          режим доганяє другу, тому прогін довший: аудит повторює сітку на кожному блоці. Це та сама
          «одна свідома спроба», а не швидкий тріаж.
        </span>
      </div>
    )}
  </>
);
