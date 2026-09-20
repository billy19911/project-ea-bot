import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Card — surface dasar (PRD §5.3/§5.4).
 *
 * Radius 10–14px, border sangat subtle, shadow halus. Bukan glassmorphism.
 */
export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Optional title, rendered in a header bar. */
  title?: string;
  /** Optional descriptive text under title. */
  description?: string;
  /** Slot for header actions (aligned to the right). */
  actions?: React.ReactNode;
  /** Remove inner padding (e.g. for tables). */
  noPadding?: boolean;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, title, description, actions, noPadding, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-sm)]',
          className
        )}
        {...props}
      >
        {(title || actions) && (
          <div className="flex items-start justify-between gap-4 border-b border-[var(--border)] px-4 py-3">
            <div>
              {title && <h3 className="text-sm font-semibold text-[var(--text)]">{title}</h3>}
              {description && <p className="text-xs text-[var(--text-muted)] mt-0.5">{description}</p>}
            </div>
            {actions && <div className="flex items-center gap-2">{actions}</div>}
          </div>
        )}
        <div className={cn(noPadding ? '' : 'p-4')}>{children}</div>
      </div>
    );
  }
);
Card.displayName = 'Card';
