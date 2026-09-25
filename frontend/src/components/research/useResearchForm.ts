import { useCallback, useEffect, useState } from 'react';

import {
  FORM_STORAGE_KEY,
  applyArchivedRun,
  applyPreset,
  archivedRunWarning,
  loadSavedForm,
  resetSplit,
  restoreForm,
  specDefaults,
} from '../../lib/researchForm';
import type { ResearchForm } from '../../lib/researchForm';
import type { ResearchRunConfig, StrategySpec } from '../../services/api';
import type { CatalogInstrument } from './BasicControls';

interface Options {
  initialRobot: string;
  externalConfig: { robot?: string; formula?: string; notes?: string } | null;
  strategies: StrategySpec[];
  catalogInstruments: CatalogInstrument[];
}

function storage(): Storage | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

/**
 * The Research Lab form: restored from localStorage, saved on every change, and kept
 * consistent with the page around it (the robot picked elsewhere, an alpha hypothesis
 * handed over, spec defaults, an instrument that left the catalog).
 */
export function useResearchForm({
  initialRobot,
  externalConfig,
  strategies,
  catalogInstruments,
}: Options) {
  const [form, setForm] = useState<ResearchForm>(() => {
    const restored = restoreForm(loadSavedForm(storage()), initialRobot);
    return externalConfig?.robot ? { ...restored, robot: externalConfig.robot } : restored;
  });
  const update = useCallback(
    (patch: Partial<ResearchForm>) => setForm((current) => ({ ...current, ...patch })),
    [],
  );

  // Save the form so a reload does not silently reset the research conditions.
  useEffect(() => {
    try {
      storage()?.setItem(FORM_STORAGE_KEY, JSON.stringify(form));
    } catch {
      // storage disabled: losing form memory is acceptable, losing the run is not
    }
  }, [form]);

  useEffect(() => {
    update({ robot: initialRobot });
  }, [initialRobot, update]);

  useEffect(() => {
    if (!externalConfig) return;
    const { robot, formula } = externalConfig;
    setForm((current) => ({
      ...current,
      ...(robot ? { robot } : {}),
      ...(formula
        ? { overrideParams: true, paramOverrides: { ...current.paramOverrides, formula } }
        : {}),
    }));
  }, [externalConfig]);

  // Seed the override inputs from the spec defaults the first time they are empty.
  useEffect(() => {
    const spec = strategies.find((item) => item.name === form.robot);
    if (!spec?.params?.length) return;
    setForm((current) =>
      Object.keys(current.paramOverrides).length > 0
        ? current
        : { ...current, paramOverrides: specDefaults(spec.params) },
    );
  }, [form.robot, strategies]);

  // Keep the instrument valid when the catalog changes.
  useEffect(() => {
    const first = catalogInstruments[0];
    if (first === undefined) return;
    if (!catalogInstruments.some((item) => item.instrument_id === form.instrumentId)) {
      update({ instrumentId: first.instrument_id });
    }
  }, [catalogInstruments, form.instrumentId, update]);

  const applyPresetConfig = useCallback(
    (config: Partial<ResearchForm>) => setForm((current) => applyPreset(current, config)),
    [],
  );

  /** Restores an archived run's form; returns the warning to show, if any. */
  const loadArchived = useCallback((config: ResearchRunConfig): string | null => {
    setForm((current) => applyArchivedRun(current, config).form);
    return archivedRunWarning(config);
  }, []);

  const reset = useCallback(() => {
    try {
      storage()?.removeItem(FORM_STORAGE_KEY);
    } catch {
      // ignore: the form still resets in memory
    }
    setForm(resetSplit);
  }, []);

  return { form, update, applyPreset: applyPresetConfig, loadArchived, reset };
}
