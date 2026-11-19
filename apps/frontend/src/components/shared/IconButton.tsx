import * as React from 'react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

type ButtonProps = React.ComponentProps<typeof Button>;

export interface IconButtonProps extends ButtonProps {
  /** Text shown on hover and exposed to screen readers. */
  tooltip: string;
  /** Which side the tooltip appears on. */
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left';
}

/**
 * An icon-only action button that always shows a hover tooltip describing what
 * it does. Standardizes the "icon + hover tooltip" pattern used app-wide so
 * every action reads the same way. Relies on the app-level <TooltipProvider>.
 */
export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ tooltip, tooltipSide = 'top', variant = 'ghost', size = 'icon', children, ...props }, ref) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button ref={ref} variant={variant} size={size} aria-label={tooltip} {...props}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side={tooltipSide}>{tooltip}</TooltipContent>
    </Tooltip>
  ),
);

IconButton.displayName = 'IconButton';
