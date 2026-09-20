import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Metric — angka tunggal + label, sesuai PRD §17/§40.
 *
 * Aturan PRD §4.2 "No fake zero": bila value null/undefined, tampilkan "—"
 * (bukan 0). Pemanggil bertanggung jawab mengirim null saat data tak tersedia.
 */
export interface MetricProps {
  label: string;
  value: string | number | null | undefined;
  /** Teks konteks tambahan di bawah value (mis. "N = 284 trades"). */
  sub?: string;
  /** Nada warna untuk value (mis. PnL negatif = danger). */
  tone?: 'default' | 'success' | 'danger' | 'warning' | 'muted';
  /** Format value sebagai angka monospaced/tabular (PRD §5.2). */
  mono?: boolean;
  className?: string;
}

const TONE_CLASS: Record<NonNullable<MetricProps['tone']>, string> = {
  default: 'text-[var(--text)]',
  success: 'text-[var(--success)]',
  danger: 'text-[var(--danger)]',
  warning: 'text-[var(--warning)]',
  muted: 'text-[var(--text-muted)]',
};

export function Metric({ label, value, sub, tone = 'default', mono = true, className }: MetricProps) {
  const display =
    value === null || value === undefined || (typeof value === 'number' && Number.isNaN(value))
      ? '—'
      : value;
  return (
    <div className={cn('flex flex-col gap-0.5', className)}>
      <span className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
      <span
        className={cn(
          'text-lg font-semibold leading-tight',
          mono && 'font-mono tabular-nums',
          TONE_CLASS[tone]
        )}
      >
        {display}
      </span>
      {sub && <span className="text-[11px] text-[var(--text-muted)]">{sub}</span>}
    </div>
  );
}

export function MetricGroup({
  children,
  columns = 4,
  className,
}: {
  children: React.ReactNode;
  columns?: 2 | 3 | 4 | 5 | 6;
  className?: string;
}) {
  const gridCols: Record<number, string> = {
    2: 'grid-cols-2',
    3: 'grid-cols-3',
    4: 'grid-cols-2 sm:grid-cols-4',
    5: 'grid-cols-2 sm:grid-cols-5',
    6: 'grid-cols-2 sm:grid-cols-6',
  };
  return (
    <div className={cn('grid gap-4', gridCols[columns], className)}>{children}</div>
  );
}
