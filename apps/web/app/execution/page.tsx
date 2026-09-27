'use client';

import AppShell from '@/components/AppShell';
import Pagination, { usePagination } from '@/components/ui/pagination';
import { useApiData, fmtNum, fmtPct } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Execution — execution-quality metrics + recent executed decisions.
 *
 * Metrics come from `/v2/execution-quality` (real records only). When no
 * execution has been recorded the honest placeholder is shown instead of a
 * misleading zero, exactly like the `/execution-quality` page.
 */

type ExecQuality = {
  metrics?: Record<string, number>;
  alerts?: string[];
  count?: number;
};

type Decision = {
  decision_id?: string;
  symbol?: string;
  decision?: string;
  status?: string;
  executed?: boolean;
  execution_result?: Record<string, unknown> | null;
  confidence?: number;
};

type DecisionsBody = { decisions?: Decision[] };

export default function ExecutionPage() {
  const q = useApiData<ExecQuality>('/v2/execution-quality');
  const d = useApiData<DecisionsBody>('/decisions');

  const metrics = q.data?.metrics ?? {};
  const hasRecords = (q.data?.count ?? 0) > 0;
  const num = (k: string) => (hasRecords && typeof metrics[k] === 'number' ? metrics[k] : null);

  const executed = (Array.isArray(d.data?.decisions) ? d.data!.decisions! : []).filter(
    (x) => x.executed === true || String(x.status ?? '').toUpperCase() === 'EXECUTED'
  );

  // /decisions is newest-first; keep that order and page the window.
  const { page, pageSize, setPage, setPageSize, slice } = usePagination(executed.length, 10);
  const pageRows = slice(executed);

  const cards = [
    { label: 'Average slippage', value: fmtNum(num('average_slippage'), 6), hint: 'price units' },
    { label: 'p95 slippage', value: fmtNum(num('p95_slippage'), 6), hint: 'tail risk' },
    { label: 'Fill delay', value: fmtNum(num('fill_delay'), 1), hint: 'ms average' },
    { label: 'Rejection rate', value: fmtPct(num('rejection_rate')), hint: 'broker rejections' },
    { label: 'Partial fill rate', value: fmtPct(num('partial_fill_rate')), hint: '' },
  ];

  return (
    <AppShell activeKey="execution" eyebrow="Xynn / Execution" title="Execution">
      <div className={styles.wrap}>
        {q.error && <div className={styles.error}>{q.error}</div>}
        {d.error && <div className={styles.error}>{d.error}</div>}

        {q.data?.alerts && q.data.alerts.length > 0 && (
          <div className={styles.error}>
            {q.data.alerts.map((a, i) => (
              <div key={i}>{a}</div>
            ))}
          </div>
        )}

        <div className={styles.grid}>
          {cards.map((c) => (
            <div key={c.label} className={styles.card}>
              <span className={styles.cardLabel}>{c.label}</span>
              <span className={`${styles.cardValue} ${styles.mono}`}>{c.value}</span>
              {c.hint && <span className={styles.cardHint}>{c.hint}</span>}
            </div>
          ))}
        </div>

        {q.data && (
          <p className={styles.cardHint}>
            {hasRecords
              ? `Recorded executions: ${q.data.count}`
              : 'No executions recorded yet — metrics show — (not 0).'}
          </p>
        )}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Executed decisions</span>
            <button
              type="button"
              className={styles.btn}
              onClick={() => {
                void q.refresh();
                void d.refresh();
              }}
            >
              Refresh
            </button>
          </div>
          <div className={styles.panelBody}>
            {executed.length === 0 ? (
              <p className={styles.empty}>
                No decision has reached execution yet. Approved proposals appear here once the
                executor dispatches them (simulated or armed live).
              </p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Decision ID</th>
                    <th>Symbol</th>
                    <th>Decision</th>
                    <th>Conf.</th>
                    <th>Order / ticket</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((x, i) => {
                    const r = x.execution_result ?? {};
                    const orderId =
                      (r['order_id'] as number | string | undefined) ??
                      (r['ticket'] as number | string | undefined) ??
                      (r['client_order_id'] as string | undefined);
                    const resultMsg =
                      (r['message'] as string | undefined) ??
                      (r['status'] as string | undefined) ??
                      '—';
                    return (
                      <tr key={String(x.decision_id ?? i)}>
                        <td className={styles.mono}>{x.decision_id ?? '—'}</td>
                        <td>{x.symbol ?? '—'}</td>
                        <td>{x.decision ?? '—'}</td>
                        <td className={styles.mono}>
                          {typeof x.confidence === 'number' ? x.confidence.toFixed(2) : '—'}
                        </td>
                        <td className={styles.mono}>{orderId ?? '—'}</td>
                        <td>{resultMsg}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
          {executed.length > 0 && (
            <Pagination
              page={page}
              pageSize={pageSize}
              total={executed.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          )}
        </div>
      </div>
    </AppShell>
  );
}
