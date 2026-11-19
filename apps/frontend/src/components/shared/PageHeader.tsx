import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTerm } from '@/contexts/TermContext';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  showTerm?: boolean;
  actionLabel?: string;
  onAction?: () => void;
  /** Optional color tint to signal an admit (green) / deny (red) context. */
  tone?: 'success' | 'danger';
  /** Optional branded logo shown beside the title (matches the workflow icons). */
  icon?: LucideIcon;
  /** Tailwind text color class for the icon, e.g. "text-blue-600". */
  iconColor?: string;
  /** Custom content rendered on the right (e.g. an action button). */
  right?: ReactNode;
}

const TONE_WRAPPER: Record<NonNullable<PageHeaderProps['tone']>, string> = {
  success: 'rounded-lg border border-emerald-200 bg-emerald-50/70 px-4 py-3',
  danger: 'rounded-lg border border-red-200 bg-red-50/70 px-4 py-3',
};

const TONE_TITLE: Record<NonNullable<PageHeaderProps['tone']>, string> = {
  success: 'text-emerald-800',
  danger: 'text-red-800',
};

// Derive the icon tile's tint background from the icon's text-color class so the
// tile matches the workflow logo colors (blue/green/violet/amber), theme-aware.
const TINT: Record<string, string> = {
  blue: 'var(--blue-t)',
  emerald: 'var(--green-t)',
  green: 'var(--green-t)',
  violet: 'var(--violet-t)',
  purple: 'var(--violet-t)',
  amber: 'var(--amber-t)',
  orange: 'var(--amber-t)',
};
function tintFor(iconColor?: string): string {
  if (iconColor) {
    for (const key of Object.keys(TINT)) if (iconColor.includes(key)) return TINT[key];
  }
  return 'var(--panel-2)';
}

export function PageHeader({ title, subtitle, showTerm, actionLabel, onAction, tone, icon: Icon, iconColor, right }: PageHeaderProps) {
  const { terms, currentTerm } = useTerm();
  const currentTermName = terms.find(t => t.id === currentTerm)?.term_name;

  return (
    <div className={`flex items-center justify-between mb-6 ${tone ? TONE_WRAPPER[tone] : ''}`}>
      <div className="flex items-center gap-3">
        {Icon && (
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] ${iconColor ?? 'text-slate-600'}`}
            style={{ background: tintFor(iconColor) }}
          >
            <Icon className="h-5 w-5" />
          </span>
        )}
        <div>
          <h1 className={`text-[19px] font-bold tracking-tight ${tone ? TONE_TITLE[tone] : ''}`}>{title}</h1>
          {subtitle && (
            <p className="mt-0.5 text-[13px] text-muted-foreground">
              {subtitle}
              {showTerm && currentTermName && ` • ${currentTermName}`}
            </p>
          )}
        </div>
      </div>
      {right}
      {actionLabel && onAction && (
        <Button onClick={onAction}>
          <Plus className="h-4 w-4 mr-2" />
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
