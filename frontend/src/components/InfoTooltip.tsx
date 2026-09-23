import React from 'react';
import { HelpCircle, Info } from 'lucide-react';
import { Tooltip } from './Tooltip';
import type { TooltipPosition } from './Tooltip';
import { GLOSSARY } from '../lib/glossary';
import type { GlossaryKey } from '../lib/glossary';

export interface InfoTooltipProps {
  term?: GlossaryKey;
  title?: string;
  subtitle?: string;
  formula?: string;
  content?: React.ReactNode;
  interpretation?: string;
  badge?: string;
  position?: TooltipPosition;
  icon?: 'help' | 'info';
  size?: 'xs' | 'sm' | 'md';
  className?: string;
}

const ICON_SIZES = {
  xs: 'w-3 h-3',
  sm: 'w-3.5 h-3.5',
  md: 'w-4 h-4',
};

export const InfoTooltip: React.FC<InfoTooltipProps> = ({
  term,
  title,
  subtitle,
  formula,
  content,
  interpretation,
  badge,
  position = 'top',
  icon = 'help',
  size = 'sm',
  className = '',
}) => {
  const glossaryEntry = term ? GLOSSARY[term] : undefined;

  const finalTitle = title ?? glossaryEntry?.title;
  const finalSubtitle = subtitle ?? glossaryEntry?.subtitle;
  const finalFormula = formula ?? glossaryEntry?.formula;
  const finalContent = content ?? glossaryEntry?.description;
  const finalInterpretation = interpretation ?? glossaryEntry?.interpretation;
  const finalBadge =
    badge ??
    (glossaryEntry?.importance === 'critical'
      ? 'Critical'
      : glossaryEntry?.category
        ? glossaryEntry.category.toUpperCase()
        : undefined);

  const badgeTone =
    glossaryEntry?.importance === 'critical'
      ? 'red'
      : glossaryEntry?.category === 'metric'
        ? 'blue'
        : glossaryEntry?.category === 'safety'
          ? 'amber'
          : 'purple';

  const IconComponent = icon === 'info' ? Info : HelpCircle;

  return (
    <Tooltip
      title={finalTitle}
      subtitle={finalSubtitle}
      formula={finalFormula}
      content={finalContent}
      interpretation={finalInterpretation}
      badge={finalBadge}
      badgeTone={badgeTone}
      position={position}
      className={className}
    >
      <span
        tabIndex={0}
        aria-label={finalTitle || 'Help information'}
        className="inline-flex items-center justify-center text-gray-500 hover:text-blue-400 focus:text-blue-400 focus:outline-none transition-colors cursor-help p-0.5 rounded-full hover:bg-gray-800/60"
      >
        <IconComponent className={ICON_SIZES[size]} />
      </span>
    </Tooltip>
  );
};
