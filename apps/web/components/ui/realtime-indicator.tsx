import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * RealtimeIndicator — topbar badge menampilkan status koneksi websocket.
 * Values: LIVE, RECONNECTING, DEGRADED, OFFLINE (PRD §75‑78).
 */
export type RealtimeStatus = 'LIVE' | 'RECONNECTING' | 'DEGRADED' | 'OFFLINE';

const STATUS_MAP: Record<RealtimeStatus, { label: string; class: string }> = {
  LIVE: { label: 'LIVE', class: 'bg-[var(--success)] text-[var(--surface)]' },
  RECONNECTING: { label: 'RECONNECTING', class: 'bg-[var(--warning)] text-[var(--surface)]' },
  DEGRADED: { label: 'DEGRADED', class: 'bg-[var(--danger)] text-[var(--surface)]' },
  OFFLINE: { label: 'OFFLINE', class: 'bg-[var(--border-strong)] text-[var(--text-muted)]' },
};

export interface RealtimeIndicatorProps {
  status: RealtimeStatus;
  className?: string;
}

export function RealtimeIndicator({ status, className }: RealtimeIndicatorProps) {
  const cfg = STATUS_MAP[status];
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        cfg.class,
        className
      )}
      data-realtime={status}
    >
      {cfg.label}
    </span>
  );
}
