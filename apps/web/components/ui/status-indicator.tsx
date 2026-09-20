import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * StatusIndicator — PRD §4.1 / §4.3 / §86.
 *
 * Aturan keras PRD:
 *  - "No fake health": status TIDAK BOLEH ditampilkan kalau backend tidak
 *    memberi hasil. Karena itu prop `status` wajib, dan `UNKNOWN` tetap
 *    dirender sebagai teks (bukan disembunyikan).
 *  - "State > color": titik warna SELALU didampingi label teks.
 *
 * Mapping state → warna + label mengikuti status model PRD §86.
 */
export type UiStatus =
  | 'HEALTHY'
  | 'RUNNING'
  | 'READY'
  | 'PAUSED'
  | 'WAITING'
  | 'DEGRADED'
  | 'STALE'
  | 'DISCONNECTED'
  | 'BLOCKED'
  | 'FAILED'
  | 'UNKNOWN'
  | 'NOT_CONFIGURED'
  | 'INSUFFICIENT_DATA';

const TONE: Record<UiStatus, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  HEALTHY: 'success',
  RUNNING: 'success',
  READY: 'success',
  PAUSED: 'warning',
  WAITING: 'info',
  DEGRADED: 'warning',
  STALE: 'warning',
  DISCONNECTED: 'danger',
  BLOCKED: 'danger',
  FAILED: 'danger',
  UNKNOWN: 'neutral',
  NOT_CONFIGURED: 'neutral',
  INSUFFICIENT_DATA: 'neutral',
};

const DOT_CLASS: Record<'success' | 'warning' | 'danger' | 'info' | 'neutral', string> = {
  success: 'bg-[var(--success)]',
  warning: 'bg-[var(--warning)]',
  danger: 'bg-[var(--danger)]',
  info: 'bg-[var(--info)]',
  neutral: 'bg-[var(--text-muted)]',
};

const LABEL: Record<UiStatus, string> = {
  HEALTHY: 'Healthy',
  RUNNING: 'Running',
  READY: 'Ready',
  PAUSED: 'Paused',
  WAITING: 'Waiting',
  DEGRADED: 'Degraded',
  STALE: 'Stale',
  DISCONNECTED: 'Disconnected',
  BLOCKED: 'Blocked',
  FAILED: 'Failed',
  UNKNOWN: 'Unknown',
  NOT_CONFIGURED: 'Not configured',
  INSUFFICIENT_DATA: 'Insufficient data',
};

export interface StatusIndicatorProps {
  status: UiStatus;
  /** Override teks; default = label standar status model. */
  label?: string;
  /** Sembunyikan titik (mis. di dalam tabel padat). */
  hideDot?: boolean;
  className?: string;
}

export function StatusIndicator({ status, label, hideDot, className }: StatusIndicatorProps) {
  const tone = TONE[status];
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 text-xs font-medium', className)}
      data-status={status}
      title={status}
    >
      {!hideDot && (
        <span
          className={cn('inline-block h-1.5 w-1.5 shrink-0 rounded-full', DOT_CLASS[tone])}
          aria-hidden="true"
        />
      )}
      <span className="text-[var(--text-secondary)]">{label ?? LABEL[status]}</span>
    </span>
  );
}
