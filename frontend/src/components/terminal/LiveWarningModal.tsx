import React from 'react';
import { ShieldAlert } from 'lucide-react';

interface LiveWarningModalProps {
  isOpen: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const LiveWarningModal: React.FC<LiveWarningModalProps> = ({
  isOpen,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#0f172a] border border-red-500/40 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
        <div className="flex items-center gap-3 text-red-400">
          <ShieldAlert className="w-7 h-7" />
          <h3 className="text-lg font-bold text-white">Live Trading Mode (Guarded)</h3>
        </div>

        <p className="text-xs text-gray-300 leading-relaxed">
          You are switching to <strong>Live Trading Mode</strong>. In Nautilus Lab, real exchange
          order routing is intentionally <strong>fail-closed</strong> (`lab live` exits with code 1
          by design).
        </p>

        <div className="p-3 bg-red-950/40 border border-red-900/60 rounded-xl text-xs text-red-200">
          This terminal will stream live Binance market data and show where orders would trigger,
          but <strong>no actual funds will be risked</strong> on any exchange.
        </div>

        <div className="flex gap-3 pt-2">
          <button
            type="button"
            onClick={onConfirm}
            className="flex-1 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl text-xs font-bold transition-colors"
          >
            Acknowledge & Proceed
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-xl text-xs font-semibold transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};
