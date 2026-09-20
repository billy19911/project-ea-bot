import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * DataTable – generic table primitive (F4b).
 * columns: array of { header: string; accessor: (row: T) => React.ReactNode }
 * rows: T[]
 */
export function DataTable<T extends unknown>({
  columns,
  rows,
  className,
}: {
  columns: { header: string; accessor: (row: T) => React.ReactNode }[];
  rows: T[];
  className?: string;
}) {
  return (
    <div className={cn('overflow-x-auto rounded-md border border-[var(--border-strong)] bg-[var(--surface)]', className)}>
      <table className="min-w-full text-sm">
        <thead className="bg-[var(--surface-muted)]">
          <tr>
            {columns.map((col, i) => (
              <th key={i} className="px-4 py-2 text-left font-medium text-[var(--text-muted)]">
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rIdx) => (
            <tr
              key={rIdx}
              className={cn(
                rIdx % 2 === 0 ? 'bg-[var(--surface)]' : 'bg-[var(--surface-muted)]',
                'hover:bg-[var(--surface-muted)]'
              )}
            >
              {columns.map((col, cIdx) => (
                <td key={cIdx} className="px-4 py-2 border-t border-[var(--border-strong)]">
                  {col.accessor(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
