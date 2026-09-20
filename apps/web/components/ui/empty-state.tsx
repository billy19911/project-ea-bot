import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * EmptyState — tampilan ketika tidak ada data (PRD §130).
 * Ikon placeholder menggunakan Lucide (icon CircleDashed).
 */
export interface EmptyStateProps {
  title: string;
  description?: string;
  /** optional action button */
  actionLabel?: string;
  onAction?: () => void;
  className?: string;
}

export function EmptyState({ title, description, actionLabel, onAction, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-4 p-8 text-center border border-dashed border-[var(--border-strong)] rounded-md bg-[var(--surface-muted)]',
        className
      )}
    >
      {/* Lucide CircleDashed */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        className="h-12 w-12 text-[var(--text-muted)]"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth="1.5"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 4.5v-1m0 17v-1M4.5 12h-1m17 0h-1M7.757 7.757l-.707-.707M16.95 16.95l-.707-.707M7.757 16.243l-.707.707M16.95 7.05l-.707.707"
        />
      </svg>
      <h2 className="text-[var(--text)] text-lg font-semibold">{title}</h2>
      {description && <p className="text-[var(--text-muted)]">{description}</p>}
      {actionLabel && onAction && (
        <button
          className={cn('mt-2 px-4 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-md hover:bg-[var(--primary-hover)]')}
          onClick={onAction}
        >{actionLabel}</button>
      )}
    </div>
  );
}
