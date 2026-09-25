import React from 'react';
import { BookOpen } from 'lucide-react';

/** How many journal rows carry each decision. */
export const JournalSummary: React.FC<{ journal: Record<string, number> }> = ({ journal }) => {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <BookOpen className="w-5 h-5 text-purple-400" />
        <h3 className="font-semibold text-gray-100">Journal decisions</h3>
      </div>
      {Object.keys(journal).length === 0 ? (
        <p className="text-sm text-gray-500">No journal rows yet.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(journal).map(([decision, count]) => (
            <div key={decision} className="p-2 rounded-lg bg-gray-950 border border-gray-800">
              <div className="text-[10px] uppercase text-gray-500">{decision}</div>
              <div className="text-lg font-mono text-gray-100">{count}</div>
            </div>
          ))}
        </div>
      )}
      <p className="text-[11px] text-gray-500">
        Decisions live in research/journal.jsonl; the Experiment Journal tab edits them.
      </p>
    </div>
  );
};
