import { Button } from '@/components/ui/button';
import { Plus } from 'lucide-react';
import { useTerm } from '@/contexts/TermContext';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  showTerm?: boolean;
  actionLabel?: string;
  onAction?: () => void;
}

export function PageHeader({ title, subtitle, showTerm, actionLabel, onAction }: PageHeaderProps) {
  const { terms, currentTerm } = useTerm();
  const currentTermName = terms.find(t => t.id === currentTerm)?.name;

  return (
    <div className="flex items-center justify-between mb-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        {subtitle && (
          <p className="text-sm text-muted-foreground mt-1">
            {subtitle}
            {showTerm && currentTermName && ` • ${currentTermName}`}
          </p>
        )}
      </div>
      {actionLabel && onAction && (
        <Button onClick={onAction}>
          <Plus className="h-4 w-4 mr-2" />
          {actionLabel}
        </Button>
      )}
    </div>
  );
}

