import React, { useCallback, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle } from 'lucide-react';

import { CatalogChart } from './CatalogChart';
import { CatalogCardsHub } from './catalog/CatalogCardsHub';
import { CatalogCoverageMatrix } from './catalog/CatalogCoverageMatrix';
import { CatalogHeader } from './catalog/CatalogHeader';
import type { CatalogViewMode } from './catalog/CatalogHeader';
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
 * The Catalog tab: datasets hub, cross-catalog coverage matrix, and in-depth inspector.
 * Provides complete visibility into all Spot & Perpetual datasets across all timeframes.
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
  const [viewMode, setViewMode] = useState<CatalogViewMode>('cards');

  const catalog = catalogResult.data;
  const instruments = catalog?.instruments ?? [];
  const defaultCatalog = catalogsResult.data?.default;
  const allCatalogs = catalogsResult.data?.catalogs ?? [];

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
        catalogOptions={allCatalogs}
        selectedCatalogPath={selectedCatalogPath}
        onCatalogChange={onCatalogChange}
        loading={catalogResult.isFetching || catalogsResult.isFetching}
        onRefresh={refresh}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
      />

      {errorMsg && (
        <div className="p-4 bg-red-950/40 border border-red-800/50 rounded-xl flex items-center gap-3 text-red-400 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Mode 1: Datasets Hub (Cards Grid) */}
      {viewMode === 'cards' && (
        <div className="flex flex-col gap-6">
          <CatalogCardsHub
            catalogs={allCatalogs}
            selectedCatalogPath={selectedCatalogPath}
            onSelectCatalog={onCatalogChange}
          />

          {chartInstrument && (
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-gray-100 flex items-center gap-2">
                  <span>Price preview:</span>
                  <span className="text-blue-400 font-mono text-sm">{chartSymbol}</span>
                  <span className="text-gray-500 font-mono text-xs font-normal">
                    ({selectedCatalogPath.split('/').pop()})
                  </span>
                </h3>
                <button
                  type="button"
                  onClick={() => setViewMode('details')}
                  className="text-xs text-blue-400 hover:text-blue-300 font-medium"
                >
                  Open Full Inspector →
                </button>
              </div>
              <CatalogChart
                instrumentId={chartInstrument}
                catalogPath={selectedCatalogPath}
                barInterval={catalog?.bar_interval}
                limit={600}
                height={280}
                title={chartSymbol}
              />
            </div>
          )}
        </div>
      )}

      {/* Mode 2: Cross-Dataset Coverage Matrix */}
      {viewMode === 'matrix' && (
        <CatalogCoverageMatrix
          catalogs={allCatalogs}
          allSymbols={catalogsResult.data?.all_symbols ?? []}
          fundingCoverage={catalogsResult.data?.funding_coverage}
          premiumCoverage={catalogsResult.data?.premium_coverage}
          selectedCatalogPath={selectedCatalogPath}
          onSelectCatalog={onCatalogChange}
        />
      )}

      {/* Mode 3: Inspector (Instruments, Side Series, Chart & Ingestion) */}
      {viewMode === 'details' && (
        <div className="flex flex-col gap-6">
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
                <span className="text-gray-400 font-normal ml-2">{chartSymbol}</span>
                {catalog?.bar_interval && (
                  <span className="text-emerald-400 font-mono text-xs ml-2">
                    [{catalog.bar_interval}]
                  </span>
                )}
              </h3>
              <CatalogChart
                instrumentId={chartInstrument}
                catalogPath={selectedCatalogPath}
                barInterval={catalog?.bar_interval}
                limit={600}
                height={320}
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
      )}
    </div>
  );
};
