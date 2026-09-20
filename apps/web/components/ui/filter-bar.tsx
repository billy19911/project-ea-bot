import * as React from 'react';
import { cn } from '@/lib/utils';

export interface FilterOption {
  label: string;
  value: string;
}

export interface FilterBarProps {
  /** Simple text filter */
  search?: {
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
  };
  /** Dropdown filter(s) */
  selects?: Array<{
    label: string;
    value: string;
    options: FilterOption[];
    onChange: (v: string) => void;
  }>;
  /** Extra content slots */
  extra?: React.ReactNode;
  className?: string;
}

export function FilterBar({ search, selects, extra, className }: FilterBarProps) {
  return (
    <div className={cn('flex flex-wrap items-end gap-2 p-2 bg-[var(--surface-muted)] border border-[var(--border-strong)] rounded-md', className)}>
      {search && (
        <label className="flex flex-col gap-0.5 text-xs">
          <span className="text-[var(--text-muted)]">Search</span>
          <input
            type="text"
            value={search.value}
            placeholder={search.placeholder}
            onChange={(e) => search.onChange(e.target.value)}
            className="h-8 rounded border border-[var(--border-strong)] bg-[var(--surface)] px-2 text-xs text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus-visible:border-[var(--primary)]"
          />
        </label>
      )}
      {selects?.map((sel, i) => (
        <label key={i} className="flex flex-col gap-0.5 text-xs">
          <span className="text-[var(--text-muted)]">{sel.label}</span>
          <select
            value={sel.value}
            onChange={(e) => sel.onChange(e.target.value)}
            className="h-8 rounded border border-[var(--border-strong)] bg-[var(--surface)] px-2 text-xs text-[var(--text)] focus:outline-none focus-visible:border-[var(--primary)]"
          >
            {sel.options.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      ))}
      {extra && <div className="ml-auto flex items-center gap-2">{extra}</div>}
    </div>
  );
}
