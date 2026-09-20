import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * ErrorState — PRD §138: jelaskan apa yang terjadi, apa yang terdampak,
 * apa yang bisa dilakukan user.
 */
export interface ErrorStateProps {
  title: string;
  description?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({ title, description, onRetry, className }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col gap-2 p-4 border border-[var(--danger-border)] bg-[var(--danger-soft)] rounded-md',
        className
      )}
    >
      <div className="flex items-center gap-2">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-4 w-4 text-[var(--danger)]"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <strong className="text-sm text-[var(--danger)]">{title}</strong>
      </div>
      {description && <p className="text-xs text-[var(--text-secondary)]">{description}</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="self-start mt-1 text-xs underline text-[var(--primary)] hover:text-[var(--primary-hover)]"
        >
          Retry
        </button>
      )}
    </div>
  );
}
