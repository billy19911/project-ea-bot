import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * RiskBadge — PRD §93/§94.
 * Level: OK, WARN, BLOCK, UNKNOWN. Tidak pernah menghilangkan label teks.
 */
export type RiskLevel = 'OK' | 'WARN' | 'BLOCK' | 'UNKNOWN';

const RISK_STYLE: Record<RiskLevel, { cls: string; label: string }> = {
  OK: { cls: 'border-[var(--success-border)] text-[var(--success)] bg-[var(--success-soft)]', label: 'OK' },
  WARN: { cls: 'border-[var(--warning-border)] text-[var(--warning)] bg-[var(--warning-soft)]', label: 'WARN' },
  BLOCK: { cls: 'border-[var(--danger-border)] text-[var(--danger)] bg-[var(--danger-soft)]', label: 'BLOCK' },
  UNKNOWN: { cls: 'border-[var(--border-strong)] text-[var(--text-muted)] bg-[var(--surface-muted)]', label: 'UNKNOWN' },
};

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  const cfg = RISK_STYLE[level];
  return (
    <span
      className={cn(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide',
        cfg.cls,
        className
      )}
      data-risk={level}
    >
      {cfg.label}
    </span>
  );
}
