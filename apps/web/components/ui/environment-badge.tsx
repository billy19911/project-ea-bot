import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * EnvironmentBadge — PRD §105/§60.
 *
 * Label eksplisit, tidak pernah disingkat saja. LIVE/PRODUCTION harus
 * visually distinct (warna bahaya + border).
 */
export type Environment = 'PAPER' | 'DEMO' | 'PRODUCTION' | 'UNKNOWN';

const STYLE: Record<Environment, string> = {
  PAPER: 'border-[var(--border-strong)] text-[var(--text-secondary)] bg-[var(--neutral-muted)]',
  DEMO: 'border-[var(--demo)] text-[var(--demo)] bg-[var(--demo-soft)]',
  PRODUCTION: 'border-[var(--live)] text-[var(--live)] bg-[var(--live-soft)]',
  UNKNOWN: 'border-[var(--border-strong)] text-[var(--text-muted)] bg-[var(--surface-muted)]',
};

export function EnvironmentBadge({
  environment,
  className,
}: {
  environment: Environment;
  className?: string;
}) {
  const label = environment === 'UNKNOWN' ? 'UNKNOWN' : environment;
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide',
        STYLE[environment],
        className
      )}
      data-env={environment}
    >
      {label}
    </span>
  );
}
