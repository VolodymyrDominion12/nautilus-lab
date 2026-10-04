import React from 'react';
import { InfoTooltip } from '../InfoTooltip';

export interface CostProfileOption {
  name: string;
  note: string;
  spot_taker_bps: number;
  usdm_taker_bps: number;
  is_default: boolean;
}

interface CostProfileSelectProps {
  value: string;
  profiles: CostProfileOption[];
  onChange: (name: string) => void;
}

/**
 * Which tariff this run pays — and the stress case it is judged against.
 *
 * Costs decide whether an edge survives: across the 2026-10 batches gross return was
 * positive almost everywhere while fees ate it. The name (not four fee numbers) is what
 * travels: it reaches the run manifest, so an artefact says which scenario it measured,
 * and `paid_cost_bps` can be compared against a breakeven that means the same thing
 * (docs/33 §4).
 */
export const CostProfileSelect: React.FC<CostProfileSelectProps> = ({
  value,
  profiles,
  onChange,
}) => {
  const selected = profiles.find((profile) => profile.name === value);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] text-gray-400">Сценарій витрат</span>
        <InfoTooltip
          title="Комісії прогону"
          content="Профіль — це назва тарифу, за яким рахується прогін (`binance_vip0_bnb`, `binance_vip0_no_bnb`, `stress_x1_5`). Назва потрапляє в манифест, тож артефакт каже, за яким тарифом його виміряли, і його можна порівняти з іншим сценарієм."
          size="xs"
        />
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={profiles.length === 0}
        className="bg-gray-950 border border-gray-800 text-xs text-gray-300 rounded-lg p-1.5 disabled:opacity-50"
      >
        <option value="">як у налаштуваннях машини</option>
        {profiles.map((profile) => (
          <option key={profile.name} value={profile.name}>
            {profile.name} — спот {profile.spot_taker_bps.toFixed(2)} bps / перп{' '}
            {profile.usdm_taker_bps.toFixed(2)} bps{profile.is_default ? ' (типовий)' : ''}
          </option>
        ))}
      </select>
      <span className="text-[10px] text-gray-500">
        {profiles.length === 0
          ? 'Бекенд не передав переліку профілів.'
          : selected
            ? selected.note
            : 'Порожньо — витрати беруться з налаштувань (COST_PROFILE або чотири поля комісій).'}
      </span>
    </div>
  );
};
