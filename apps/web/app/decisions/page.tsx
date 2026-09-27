'use client';

import { useMemo, useState } from 'react';
import AppShell from '@/components/AppShell';
import Pagination, { usePagination } from '@/components/ui/pagination';
import { useApiData } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Decisions — the pipeline's real decision ledger (`/decisions`).
 *
 * Each row is a real `PipelineResult.to_dict()` from the process-wide history
 * (newest first). Nothing is fabricated: an empty ledger shows an honest empty
 * state and every status comes straight from the pipeline.
 */

type Decision = {
  decision_id?: string;
  event_type?: string;
  symbol?: string;
  decision?: string;
  status?: string;
  risk_approved?: boolean;
  risk_reason?: string;
  executed?: boolean;
  confidence?: number;
  summary?: string;
};

type DecisionsBody = { decisions?: Decision[]; count?: number; source?: string };

function statusPillClass(status: string): string {
  const s = status.toUpperCase();
  if (s === 'EXECUTED' || s === 'APPROVED') return `${styles.pill} ${styles.pillOk}`;
  if (s === 'BLOCKED' || s === 'ERROR') return `${styles.pill} ${styles.pillDanger}`;
  if (s === 'NO_TRADE' || s === 'WAIT') return `${styles.pill} ${styles.pillWarn}`;
  return `${styles.pill} ${styles.pillNeutral}`;
}

export default function DecisionsPage() {
  const { data, error, loading, refresh } = useApiData<DecisionsBody>('/decisions');
  const [filter, setFilter] = useState('');

  const all = useMemo(() => (Array.isArray(data?.decisions) ? data!.decisions! : []), [data]);

  const rows = useMemo(() => {
    const q = filter.trim().toUpperCase();
    if (!q) return all;
    return all.filter(
      (d) =>
        String(d.status ?? '').toUpperCase().includes(q) ||
        String(d.decision ?? '').toUpperCase().includes(q) ||
        String(d.event_type ?? '').toUpperCase().includes(q) ||
        String(d.symbol ?? '').toUpperCase().includes(q)
    );
  }, [all, filter]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const d of all) {
      const k = String(d.status || 'UNKNOWN').toUpperCase();
      c[k] = (c[k] ?? 0) + 1;
    }
    return c;
  }, [all]);

  const { page, pageSize, setPage, setPageSize, slice } = usePagination(rows.length, 25);
  const pageRows = slice(rows);

  return (
    <AppShell activeKey="decisions" eyebrow="Xynn / Decisions" title="Decisions">
      <div className={styles.wrap}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Total decisions</span>
            <span className={styles.cardValue}>{data?.count ?? '—'}</span>
            <span className={styles.cardHint}>in-process history</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Executed</span>
            <span className={styles.cardValue}>{counts['EXECUTED'] ?? 0}</span>
            <span className={styles.cardHint}>reached execution</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Blocked</span>
            <span className={styles.cardValue}>{counts['BLOCKED'] ?? 0}</span>
            <span className={styles.cardHint}>risk gate / guards</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>No trade / wait</span>
            <span className={styles.cardValue}>
              {(counts['NO_TRADE'] ?? 0) + (counts['WAIT'] ?? 0)}
            </span>
            <span className={styles.cardHint}>committee declined</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Decision ledger</span>
            <div className={styles.row}>
              <input
                className={styles.input}
                placeholder="Filter status / symbol / event…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                aria-label="Filter decisions"
              />
              <button type="button" className={styles.btn} onClick={refresh}>
                Refresh
              </button>
            </div>
          </div>
          <div className={styles.panelBody}>
            {loading && rows.length === 0 ? (
              <p className={styles.empty}>Loading…</p>
            ) : rows.length === 0 ? (
              <p className={styles.empty}>
                {filter
                  ? 'No decisions match the filter.'
                  : 'No decisions recorded yet — run a pipeline cycle to populate the ledger.'}
              </p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Decision ID</th>
                    <th>Event</th>
                    <th>Symbol</th>
                    <th>Decision</th>
                    <th>Status</th>
                    <th>Risk</th>
                    <th>Conf.</th>
                    <th>Executed</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((d, i) => (
                    <tr key={String(d.decision_id ?? i)}>
                      <td className={styles.mono}>{d.decision_id ?? '—'}</td>
                      <td>{d.event_type ?? '—'}</td>
                      <td>{d.symbol ?? '—'}</td>
                      <td>{d.decision ?? '—'}</td>
                      <td>
                        <span className={statusPillClass(String(d.status ?? ''))}>
                          {d.status ?? '—'}
                        </span>
                      </td>
                      <td title={d.risk_reason || ''}>
                        {d.risk_approved == null ? '—' : d.risk_approved ? 'approved' : 'rejected'}
                      </td>
                      <td className={styles.mono}>
                        {typeof d.confidence === 'number' ? d.confidence.toFixed(2) : '—'}
                      </td>
                      <td>{d.executed == null ? '—' : d.executed ? 'yes' : 'no'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          {rows.length > 0 && (
            <Pagination
              page={page}
              pageSize={pageSize}
              total={rows.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
