import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * LoadingState — skeleton berikut PRD §138‑140.
 * Menyediakan animasi shimmer tanpa warna‑berkebal.
 */
export interface LoadingStateProps {
  /** Number of skeleton rows, default 4 */
  rows?: number;
  className?: string;
}

export function LoadingState({ rows = 4, className }: LoadingStateProps) {
  const items = Array.from({ length: rows });
  return (
    <div className={cn('space-y-2', className)}>
      {items.map((_, i) => (
        <div
          key={i}
          className="h-4 w-full rounded bg-[var(--border-strong)] animate-pulse"
        />
      ))}
    </div>
  );
}
