'use client';

import { useState } from 'react';

// Reusable pagination for long tables/lists. Renders a compact, accessible
// control. Pages that use it keep the full dataset in memory and slice the
// visible window; the parent owns the page state so it can also reset on
// filter changes.

export type PaginationProps = {
  page: number; // 1-based
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  pageSizeOptions?: number[];
  /** Optional label suffix, e.g. "rows". */
  unitLabel?: string;
};

export function usePagination(total: number, initialSize = 25) {
  const [page, setPageState] = useState(1);
  const [pageSize, setPageSizeState] = useState(initialSize);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;
  const end = Math.min(start + pageSize, total);
  const setPage = (p: number) => setPageState(Math.min(Math.max(p, 1), pageCount));
  const setPageSize = (s: number) => {
    setPageSizeState(s);
    setPageState(1);
  };
  const slice = <T,>(rows: T[]) => rows.slice(start, end);
  return { page: safePage, pageSize, setPage, setPageSize, pageCount, start, end, slice };
}

export default function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = [10, 25, 50, 100],
  unitLabel = 'rows',
}: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(page, 1), pageCount);
  const start = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, total);

  // Window of page numbers with ellipses.
  const pages: (number | '…')[] = [];
  const push = (p: number | '…') => pages.push(p);
  const around = 1;
  for (let p = 1; p <= pageCount; p++) {
    if (p === 1 || p === pageCount || (p >= safePage - around && p <= safePage + around)) {
      push(p);
    } else if (pages[pages.length - 1] !== '…') {
      push('…');
    }
  }

  return (
    <div className="ea-pagination">
      <span className="ea-pagination__info">
        {total === 0 ? `0 ${unitLabel}` : `${start}–${end} of ${total} ${unitLabel}`}
      </span>

      <div className="ea-pagination__controls">
        {onPageSizeChange && (
          <select
            className="ea-pagination__size"
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            aria-label="Rows per page"
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n} / page
              </option>
            ))}
          </select>
        )}

        <button
          type="button"
          className="ea-pagination__btn"
          onClick={() => onPageChange(safePage - 1)}
          disabled={safePage <= 1}
          aria-label="Previous page"
        >
          ‹
        </button>

        {pages.map((p, i) =>
          p === '…' ? (
            <span key={`e${i}`} className="ea-pagination__ellipsis">
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              className={`ea-pagination__btn ${p === safePage ? 'is-active' : ''}`}
              onClick={() => onPageChange(p)}
              aria-current={p === safePage ? 'page' : undefined}
            >
              {p}
            </button>
          ),
        )}

        <button
          type="button"
          className="ea-pagination__btn"
          onClick={() => onPageChange(safePage + 1)}
          disabled={safePage >= pageCount}
          aria-label="Next page"
        >
          ›
        </button>
      </div>
    </div>
  );
}
