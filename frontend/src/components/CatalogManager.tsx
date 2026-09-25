import React, { useCallback, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle } from 'lucide-react';

import { CatalogChart } from './CatalogChart';
import { CatalogHeader } from './catalog/CatalogHeader';
import { IngestPanel } from './catalog/IngestPanel';
import { InstrumentCards } from './catalog/InstrumentCards';
import { SeriesCoverage } from './catalog/SeriesCoverage';
import {
  catalogDataKeys,
  catalogQuery,
  catalogsQuery,
  dataHealthQuery,
} from '../services/queries';

interface CatalogManagerProps {
  selectedCatalogPath: string;
  onCatalogChange: (path: string) => void;
}

/**
 * The Catalog tab: what the selected catalog holds, a price preview, and the ingest that
 * fills it. Data comes from the shared query cache (services/queries.ts); the pieces
 * live in `components/catalog/`.
 */
export const CatalogManager: React.FC<CatalogManagerProps> = ({
  selectedCatalogPath,
  onCatalogChange,
}) => {
  const queryClient = useQueryClient();
  const catalogResult = useQuery(catalogQuery(selectedCatalogPath));
  const catalogsResult = useQuery(catalogsQuery());
  const healthResult = useQuery(dataHealthQuery(selectedCatalogPath));
  const [actionError, setActionError] = useState('');
  const [pickedInstrument, setPickedInstrument] = useState<string | undefined>(undefined);

  const catalog = catalogResult.data;
  const instruments = catalog?.instruments ?? [];
  const defaultCatalog = catalogsResult.data?.default;
  // The picked instrument while this catalog has it, else the first one.
  const chartInstrument = instruments.some((item) => item.instrument_id === pickedInstrument)
    ? pickedInstrument
    : instruments[0]?.instrument_id;
  const chartSymbol = instruments.find((item) => item.instrument_id === chartInstrument)?.raw_symbol;

  useEffect(() => {
    if (!selectedCatalogPath && defaultCatalog) onCatalogChange(defaultCatalog);
  }, [selectedCatalogPath, defaultCatalog, onCatalogChange]);

  const refresh = useCallback(() => {
    setActionError('');
    for (const queryKey of catalogDataKeys) {
      void queryClient.invalidateQueries({ queryKey });
    }
  }, [queryClient]);

  const loadError =
    catalog?.error ||
    (catalogResult.error ? catalogResult.error.message || 'Failed to load the catalog' : '');
  const errorMsg = actionError || loadError;

  return (
    <div className="flex flex-col gap-6">
      <CatalogHeader
        catalog={catalog}
        catalogOptions={catalogsResult.data?.catalogs ?? []}
        selectedCatalogPath={selectedCatalogPath}
        onCatalogChange={onCatalogChange}
        loading={catalogResult.isFetching || catalogsResult.isFetching}
        onRefresh={refresh}
      />

      {errorMsg && (
        <div className="p-4 bg-red-950/40 border border-red-800/50 rounded-xl flex items-center gap-3 text-red-400 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      <InstrumentCards
        instruments={instruments}
        selected={chartInstrument}
        onChart={setPickedInstrument}
      />

      <SeriesCoverage health={healthResult.data?.instruments ?? []} instruments={instruments} />

      {chartInstrument && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
          <h3 className="text-sm font-bold text-gray-100">
            Price preview
            <span className="text-gray-500 font-normal ml-2">{chartSymbol}</span>
          </h3>
          <CatalogChart
            instrumentId={chartInstrument}
            catalogPath={selectedCatalogPath}
            barInterval={catalog?.bar_interval}
            limit={600}
            height={300}
            title={chartSymbol}
          />
        </div>
      )}

      <IngestPanel
        selectedCatalogPath={selectedCatalogPath}
        onFinished={refresh}
        onError={setActionError}
      />
    </div>
  );
};
