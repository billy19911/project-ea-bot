import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * Panel — kartu panel dengan header opsional + area aksi.
 *
 * Menggantikan markup berulang `panel / panelHead / panelTitle / panelBody`
 * yang kini disalin di belasan halaman. Token-driven sehingga seragam di
 * seluruh dashboard (dan mendukung tema gelap/terang otomatis).
 */
export interface PanelProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  /** Judul panel (uppercase mono, sesuai gaya instrument). */
  title?: React.ReactNode;
  /** Slot aksi di kanan header (mis. tombol Refresh). */
  actions?: React.ReactNode;
  /** Isi panel. */
  children: React.ReactNode;
  /** Hilangkan padding body (mis. untuk tabel penuh). */
  noPadding?: boolean;
  className?: string;
  bodyClassName?: string;
}

export const Panel = React.forwardRef<HTMLDivElement, PanelProps>(
  ({ title, actions, children, noPadding, className, bodyClassName, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'rounded-[var(--r-lg)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden',
        className
      )}
      {...props}
    >
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--surface-muted)] px-4 py-2.5">
          <span className="font-mono text-[var(--fs-xs)] font-semibold uppercase tracking-[0.1em] text-[var(--text-secondary)]">
            {title}
          </span>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={cn(noPadding ? '' : 'p-4', bodyClassName)}>{children}</div>
    </div>
  )
);
Panel.displayName = 'Panel';
