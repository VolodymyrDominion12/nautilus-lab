import React, { useState, useRef, useEffect } from 'react';

export type TooltipPosition = 'top' | 'bottom' | 'left' | 'right';

export interface TooltipProps {
  content?: React.ReactNode;
  title?: string;
  subtitle?: string;
  formula?: string;
  interpretation?: string;
  badge?: string;
  badgeTone?: 'emerald' | 'amber' | 'blue' | 'purple' | 'red' | 'gray';
  position?: TooltipPosition;
  delay?: number;
  maxWidth?: string;
  children: React.ReactNode;
  className?: string;
}

const BADGE_STYLES = {
  emerald: 'bg-emerald-950/80 text-emerald-300 border-emerald-800/60',
  amber: 'bg-amber-950/80 text-amber-300 border-amber-800/60',
  blue: 'bg-blue-950/80 text-blue-300 border-blue-800/60',
  purple: 'bg-purple-950/80 text-purple-300 border-purple-800/60',
  red: 'bg-red-950/80 text-red-300 border-red-800/60',
  gray: 'bg-gray-900 text-gray-400 border-gray-800',
};

export const Tooltip: React.FC<TooltipProps> = ({
  content,
  title,
  subtitle,
  formula,
  interpretation,
  badge,
  badgeTone = 'blue',
  position = 'top',
  delay = 150,
  maxWidth = 'max-w-xs sm:max-w-sm',
  children,
  className = '',
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const show = () => {
    timerRef.current = setTimeout(() => {
      setIsVisible(true);
    }, delay);
  };

  const hide = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setIsVisible(false);
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const positionClasses: Record<TooltipPosition, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  };

  const arrowClasses: Record<TooltipPosition, string> = {
    top: 'top-full left-1/2 -translate-x-1/2 -mt-1 border-t-gray-800 border-l-transparent border-r-transparent border-b-transparent',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 -mb-1 border-b-gray-800 border-l-transparent border-r-transparent border-t-transparent',
    left: 'left-full top-1/2 -translate-y-1/2 -ml-1 border-l-gray-800 border-t-transparent border-b-transparent border-r-transparent',
    right: 'right-full top-1/2 -translate-y-1/2 -mr-1 border-r-gray-800 border-t-transparent border-b-transparent border-l-transparent',
  };

  const hasRichContent = Boolean(title || subtitle || formula || interpretation || badge);

  return (
    <div
      ref={containerRef}
      className={`relative inline-flex items-center ${className}`}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}

      {isVisible && (content || hasRichContent) && (
        <div
          role="tooltip"
          className={`absolute ${positionClasses[position]} z-50 pointer-events-none transition-opacity duration-150 ease-out`}
        >
          <div
            className={`bg-[#0a0f1d]/95 backdrop-blur-md border border-gray-700/80 text-gray-200 text-xs shadow-2xl rounded-xl p-3.5 flex flex-col gap-2 w-max ${maxWidth} text-left leading-relaxed`}
          >
            {/* Header: Title + Badge */}
            {(title || badge) && (
              <div className="flex items-start justify-between gap-2 border-b border-gray-800/80 pb-2">
                <div>
                  {title && <span className="font-bold text-gray-100 block text-xs">{title}</span>}
                  {subtitle && (
                    <span className="text-[10px] text-gray-400 block font-normal">{subtitle}</span>
                  )}
                </div>
                {badge && (
                  <span
                    className={`text-[9px] font-mono px-1.5 py-0.5 rounded border uppercase tracking-wider shrink-0 ${BADGE_STYLES[badgeTone]}`}
                  >
                    {badge}
                  </span>
                )}
              </div>
            )}

            {/* Formula (if any) */}
            {formula && (
              <div className="bg-gray-950/80 px-2 py-1.5 rounded-lg border border-gray-800/80 font-mono text-[10px] text-cyan-300 overflow-x-auto whitespace-pre-wrap">
                {formula}
              </div>
            )}

            {/* Main Content / Description */}
            {content && <div className="text-gray-300 text-[11px] whitespace-pre-line">{content}</div>}

            {/* Interpretation / Takeaway (Why it matters) */}
            {interpretation && (
              <div className="bg-blue-950/20 border-l-2 border-blue-500/70 pl-2 py-1 text-[10px] text-blue-200/90 whitespace-pre-line">
                <span className="font-semibold text-blue-400 block text-[9px] uppercase tracking-wider mb-0.5">
                  Інтерпретація:
                </span>
                {interpretation}
              </div>
            )}
          </div>

          {/* Decorative Arrow */}
          <div className={`absolute w-0 h-0 border-4 ${arrowClasses[position]}`} />
        </div>
      )}
    </div>
  );
};
