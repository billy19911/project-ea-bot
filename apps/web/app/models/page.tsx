'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import Pagination from '@/components/ui/pagination';
import styles from '@/components/ops.module.css';

type Telemetry = {
  request_id: string;
  agent: string;
  provider: string;
  model: string;
  latency: number;
  fallback: boolean;
  error: string;
  input_tokens: number;
  output_tokens: number;
  structured_output_valid: boolean;
  created_at: string;
};

export default function ModelsPage() {
  const [records, setRecords] = useState<Telemetry[]>([]);
  const [count, setCount] = useState(0);
  const [source, setSource] = useState('unknown');
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/v2/llm/telemetry');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        setSource('unavailable');
        return;
      }
      const data = await res.json();
      setRecords(Array.isArray(data.value) ? data.value : []);
      setCount(typeof data.count === 'number' ? data.count : 0);
      setSource(typeof data.source === 'string' ? data.source : 'unknown');
      setError(null);
    } catch {
      setError('Could not reach the API.');
      setSource('unavailable');
    }
  }, []);

  useAutoRefresh(load);

  const failures = records.filter(r => r.error).length;
  const avgLatency =
    records.length > 0
      ? (records.reduce((sum, r) => sum + (r.latency || 0), 0) / records.length).toFixed(3)
      : '—';

  const pageCount = Math.max(1, Math.ceil(records.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = records.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <AppShell activeKey="models" eyebrow="Xynn / AI" title="Models & LLM Observability">
      <div className={styles.wrap}>
        <p className={styles.cardHint}>
          Observability — hanya memantau; bukan pemilih model. Halaman ini tidak mengubah
          routing model.
        </p>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Requests Tracked</span>
            <span className={styles.cardValue}>{count}</span>
            <span className={styles.cardHint}>
              source: {source} · menampilkan {records.length} terakhir
            </span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Failures (recent)</span>
            <span className={styles.cardValue}>{failures}</span>
            <span className={styles.cardHint}>Failures never cause unsafe trades</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Avg Latency</span>
            <span className={`${styles.cardValue} ${styles.mono}`}>{avgLatency}</span>
            <span className={styles.cardHint}>seconds</span>
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Request Telemetry</span>
            <button type="button" className={styles.btn} onClick={load}>
              Refresh
            </button>
          </div>
          {records.length === 0 ? (
            <div className={styles.empty}>No LLM requests recorded yet.</div>
          ) : (
            <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Request</th>
                  <th>Model</th>
                  <th>Agent</th>
                  <th>Latency</th>
                  <th>Tokens (in/out)</th>
                  <th>Structured</th>
                  <th>Fallback</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {visible.map(r => (
                  <tr key={r.request_id}>
                    <td className={styles.mono}>{r.request_id}</td>
                    <td>{r.model}</td>
                    <td>{r.agent || '—'}</td>
                    <td className={styles.mono}>{r.latency}</td>
                    <td className={styles.mono}>
                      {r.input_tokens} / {r.output_tokens}
                    </td>
                    <td>
                      {r.structured_output_valid ? (
                        <span className={`${styles.pill} ${styles.pillOk}`}>VALID</span>
                      ) : (
                        <span className={`${styles.pill} ${styles.pillWarn}`}>INVALID</span>
                      )}
                    </td>
                    <td>{r.fallback ? 'yes' : 'no'}</td>
                    <td>{r.error || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              page={safePage}
              pageSize={pageSize}
              total={records.length}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              unitLabel="requests"
            />
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
