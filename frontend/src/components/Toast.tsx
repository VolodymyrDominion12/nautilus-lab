import React, { useCallback, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';
import { ToastContext } from './toastContext';
import type { ToastItem, ToastType } from './toastContext';

export type { ToastItem, ToastType } from './toastContext';

/** Play a subtle pleasant audio chime on task finish (Web Audio API) */
const playChime = (type: 'success' | 'alert' = 'success') => {
  try {
    const AudioContextClass =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextClass) return;
    const ctx = new AudioContextClass();
    const now = ctx.currentTime;

    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    if (type === 'success') {
      osc.frequency.setValueAtTime(587.33, now); // D5
      osc.frequency.exponentialRampToValueAtTime(880, now + 0.12); // A5
    } else {
      osc.frequency.setValueAtTime(440, now); // A4
      osc.frequency.exponentialRampToValueAtTime(349.23, now + 0.15); // F4
    }

    gain.gain.setValueAtTime(0.08, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.28);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start(now);
    osc.stop(now + 0.3);
  } catch {
    // AudioContext blocked by browser policy before user interaction; ignore silently
  }
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (title: string, message?: string, type: ToastType = 'info') => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
      const newItem: ToastItem = { id, type, title, message, timestamp: Date.now() };

      setToasts((prev) => [...prev.slice(-4), newItem]); // Keep last 5 max

      if (type === 'success') {
        playChime('success');
      }

      setTimeout(() => {
        removeToast(id);
      }, 5000);
    },
    [removeToast],
  );

  const success = useCallback(
    (title: string, message?: string) => showToast(title, message, 'success'),
    [showToast],
  );
  const error = useCallback(
    (title: string, message?: string) => showToast(title, message, 'error'),
    [showToast],
  );
  const info = useCallback(
    (title: string, message?: string) => showToast(title, message, 'info'),
    [showToast],
  );

  return (
    <ToastContext.Provider value={{ showToast, success, error, info }}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none max-w-sm w-full">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto flex items-start gap-3 p-3.5 rounded-2xl border shadow-2xl backdrop-blur-md transition-all animate-in fade-in slide-in-from-bottom-3 ${
              toast.type === 'success'
                ? 'bg-emerald-950/90 border-emerald-800/60 text-emerald-100'
                : toast.type === 'error'
                  ? 'bg-red-950/90 border-red-800/60 text-red-100'
                  : 'bg-gray-900/95 border-gray-700 text-gray-100'
            }`}
          >
            <div className="mt-0.5 shrink-0">
              {toast.type === 'success' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
              {toast.type === 'error' && <AlertTriangle className="w-4 h-4 text-red-400" />}
              {toast.type === 'info' && <Info className="w-4 h-4 text-blue-400" />}
            </div>

            <div className="flex-1 min-w-0">
              <div className="text-xs font-bold leading-snug">{toast.title}</div>
              {toast.message && (
                <div className="text-[11px] opacity-80 mt-0.5 leading-tight line-clamp-2">
                  {toast.message}
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={() => removeToast(toast.id)}
              className="p-1 rounded-lg hover:bg-white/10 opacity-70 hover:opacity-100 transition-opacity"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};
