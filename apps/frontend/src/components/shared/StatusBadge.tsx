import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

type StatusType =
  | 'processed' | 'pass' | 'active' | 'eligible' | 'generated' | 'mapped'  // success
  | 'failed' | 'fail' | 'ineligible' | 'revoked'  // error
  | 'verification' | 'warning'  // warning
  | 'queue' | 'pending' | 'received';  // pending

interface StatusBadgeProps {
  status: StatusType | string;
  className?: string;
}

// Exact mapping as specified
const getStatusVariant = (status: string): { label: string; className: string } => {
  const normalizedStatus = status.toLowerCase();

  // Success: green
  if (['processed', 'pass', 'active', 'eligible', 'generated', 'mapped'].includes(normalizedStatus)) {
    return {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      className: 'bg-green-100 text-green-800 border-green-200'
    };
  }

  // Error: red
  if (['failed', 'fail', 'ineligible', 'revoked'].includes(normalizedStatus)) {
    return {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      className: 'bg-red-100 text-red-800 border-red-200'
    };
  }

  // Warning: amber
  if (['verification', 'warning'].includes(normalizedStatus)) {
    return {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      className: 'bg-amber-100 text-amber-800 border-amber-200'
    };
  }

  // Pending: gray
  if (['queue', 'pending', 'received'].includes(normalizedStatus)) {
    return {
      label: status.charAt(0).toUpperCase() + status.slice(1),
      className: 'bg-gray-100 text-gray-800 border-gray-200'
    };
  }

  // Default: info (blue)
  return {
    label: status.charAt(0).toUpperCase() + status.slice(1),
    className: 'bg-blue-100 text-blue-800 border-blue-200'
  };
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = getStatusVariant(status);

  return (
    <Badge
      variant="outline"
      className={cn(config.className, className)}
    >
      {config.label}
    </Badge>
  );
}

