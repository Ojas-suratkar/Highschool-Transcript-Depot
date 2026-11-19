import { ReactNode } from 'react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type Accent = 'blue' | 'green' | 'violet' | 'amber' | 'cyan' | 'red' | 'pink';

const ACCENT: Record<Accent, { border: string; icon: string; value: string }> = {
  blue: { border: 'border-blue-200', icon: 'bg-blue-50 text-blue-600', value: 'text-blue-700' },
  green: { border: 'border-emerald-200', icon: 'bg-emerald-50 text-emerald-600', value: 'text-emerald-700' },
  violet: { border: 'border-violet-200', icon: 'bg-violet-50 text-violet-600', value: 'text-violet-700' },
  amber: { border: 'border-amber-200', icon: 'bg-amber-50 text-amber-600', value: 'text-amber-700' },
  cyan: { border: 'border-cyan-200', icon: 'bg-cyan-50 text-cyan-600', value: 'text-cyan-700' },
  red: { border: 'border-red-200', icon: 'bg-red-50 text-red-600', value: 'text-red-700' },
  pink: { border: 'border-pink-200', icon: 'bg-pink-50 text-pink-600', value: 'text-pink-700' },
};

interface StatCardProps {
  title: string;
  value: string | number;
  icon: ReactNode;
  trend?: {
    value: number;
    isPositive: boolean;
  };
  accent?: Accent;
  className?: string;
}

export function StatCard({ title, value, icon, trend, accent, className }: StatCardProps) {
  const a = accent ? ACCENT[accent] : null;
  return (
    <Card className={cn('p-6', a?.border, className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className={cn('text-2xl font-bold mt-2', a?.value)}>{value}</p>
          {trend && (
            <p className={cn(
              'text-sm font-medium mt-2',
              trend.isPositive ? 'text-green-600' : 'text-red-600'
            )}>
              {trend.isPositive ? '+' : ''}{trend.value}% from last term
            </p>
          )}
        </div>
        <div className={cn(
          'flex h-12 w-12 items-center justify-center rounded-lg shrink-0',
          a?.icon ?? 'bg-primary/10 text-primary',
        )}>
          {icon}
        </div>
      </div>
    </Card>
  );
}
