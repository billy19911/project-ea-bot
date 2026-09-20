'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import Pagination from './pagination';

/**
 * DataTable – generic table primitive with built-in pagination.
 *
 * columns: array of { header: string; accessor: (row: T) => React.ReactNode }
 * rows: T[]
 *
 * When `paginate` is true (default for long tables) the table shows a page
 * control. Set `paginate={false}` for short tables that should show every row.
 * Pass a `pageSize` to tune the initial window.
 */
export function DataTable<T extends unknown>({
  columns,
  rows,
  className,
  paginate = true,
  pageSize: initialPageSize = 25,
  unitLabel = 'rows',
}: {
  columns: { header: string; accessor: (row: T) => React.ReactNode }[];
  rows: T[];
  className?: string;
  paginate?: boolean;
  pageSize?: number;
  unitLabel?: string;
}) {
  const [page, setPage] = React.useState(1);
  const [pageSize, setPageSize] = React.useState(initialPageSize);

  // Keep the page in range when the data shrinks.
  React.useEffect(() => {
    setPage(1);
  }, [rows.length]);

  const shouldPaginate = paginate && rows.length > pageSize;
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = shouldPaginate
    ? rows.slice((safePage - 1) * pageSize, safePage * pageSize)
    : rows;

  return (
    <div className={cn('ea-datatable rounded-md border border-[var(--border-strong)] bg-[var(--surface)]', className)}>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-[var(--surface-muted)]">
            <tr>
              {columns.map((col, i) => (
                <th
                  key={i}
                  className="px-4 py-2.5 text-left font-[family-name:var(--font-mono)] text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]"
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, rIdx) => (
              <tr
                key={rIdx}
                className="border-t border-[var(--border)] transition-colors hover:bg-[var(--surface-muted)]"
              >
                {columns.map((col, cIdx) => (
                  <td key={cIdx} className="px-4 py-2.5 text-[var(--text-secondary)]">
                    {col.accessor(row)}
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-6 text-center text-[var(--text-muted)]"
                >
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {shouldPaginate && (
        <Pagination
          page={safePage}
          pageSize={pageSize}
          total={rows.length}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          unitLabel={unitLabel}
        />
      )}
    </div>
  );
}
