import React from 'react';
import { ExternalLink, FileText } from 'lucide-react';

import { staticReportUrl } from '../../config';
import type { ReportItem } from '../../services/api';

interface TearsheetPanelProps {
  reports: ReportItem[];
  selectedTearsheetUrl: string | null;
  onSelect: (url: string) => void;
}

/** The selected HTML tearsheet in a frame, with the latest reports to switch between. */
export const TearsheetPanel: React.FC<TearsheetPanelProps> = ({
  reports,
  selectedTearsheetUrl,
  onSelect,
}) => (
  <div className="bg-gray-900 border border-gray-800 rounded-2xl flex flex-col overflow-hidden h-[460px]">
    <div className="bg-gray-900 px-5 py-3 border-b border-gray-800 flex justify-between items-center">
      <div className="flex items-center gap-2">
        <FileText className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-bold text-gray-100">Interactive tearsheet</h3>
      </div>
      {selectedTearsheetUrl && (
        <a
          href={staticReportUrl(selectedTearsheetUrl)}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
        >
          Open in new tab <ExternalLink className="w-3.5 h-3.5" />
        </a>
      )}
    </div>

    <div className="flex-1 bg-gray-950 flex flex-col">
      {selectedTearsheetUrl ? (
        <iframe
          src={staticReportUrl(selectedTearsheetUrl)}
          title="Tearsheet view"
          className="w-full h-full border-0 bg-white"
        />
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center text-gray-500 text-xs">
          <FileText className="w-8 h-8 text-gray-700 mb-2" />
          No tearsheet generated yet.
          <br />
          Run a backtest with &quot;Generate HTML tearsheet&quot; enabled.
        </div>
      )}
    </div>

    {reports.length > 0 && (
      <div className="p-2.5 bg-gray-950 border-t border-gray-800 flex items-center gap-2 overflow-x-auto text-xs">
        <span className="text-gray-500 text-[11px] whitespace-nowrap">Reports:</span>
        {reports.slice(0, 6).map((report) => (
          <button
            type="button"
            key={report.filename}
            onClick={() => onSelect(report.url)}
            title={`${report.modified} · ${report.size_kb} KB`}
            className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-colors whitespace-nowrap ${
              selectedTearsheetUrl === report.url
                ? 'bg-blue-600 text-white'
                : 'bg-gray-900 text-gray-400 hover:bg-gray-800'
            }`}
          >
            {report.filename.replace('.html', '')}
            <span className="text-[9px] text-gray-500 ml-1">{report.size_kb}KB</span>
          </button>
        ))}
      </div>
    )}
  </div>
);
