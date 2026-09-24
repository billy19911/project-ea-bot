'use client';

import { useCallback, useState } from 'react';
import { useAutoRefresh } from '@/lib/useAutoRefresh';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import Pagination from '@/components/ui/pagination';
import styles from '@/components/ops.module.css';

type Incident = {
  incident_id: string;
  severity: string;
  component: string;
  trigger: string;
  system_state: string;
  action_taken: string;
  recovery_state: string;
  detected_at: string;
  resolved_at: string | null;
  open: boolean;
};

function severityClass(severity: string): string {
  switch (severity) {
    case 'CRITICAL':
    case 'EMERGENCY':
      return styles.pillDanger;
    case 'HIGH':
      return styles.pillWarn;
    case 'WARNING':
      return styles.pillWarn;
    default:
      return styles.pillNeutral;
  }
}

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [openCritical, setOpenCritical] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await apiFetch('/v2/incidents');
      if (!res.ok) {
        setError(res.status === 503 ? 'Python service unavailable.' : `Request failed (${res.status})`);
        return;
      }
      const data = await res.json();
      setIncidents(Array.isArray(data.value) ? data.value : []);
      setOpenCritical(data.open_critical === true);
    } catch {
      setError('Could not reach the API.');
    } finally {
      setLoaded(true);
    }
  }, []);

  useAutoRefresh(load);

  const resolve = async (id: string) => {
    await apiFetch(`/v2/incidents/${encodeURIComponent(id)}/resolve`, { method: 'POST' });
    load();
  };

  const pageCount = Math.max(1, Math.ceil(incidents.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const visible = incidents.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <AppShell activeKey="incidents" eyebrow="Xynn / Incidents" title="Incidents">
      <div className={styles.wrap}>
        <div className={styles.grid}>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Open Incidents</span>
            <span className={styles.cardValue}>
              {incidents.filter(i => i.open).length}
            </span>
            <span className={styles.cardHint}>Total recorded: {incidents.length}</span>
          </div>
          <div className={styles.card}>
            <span className={styles.cardLabel}>Critical</span>
            <span className={styles.cardValue}>
              {openCritical ? (
                <span className={`${styles.pill} ${styles.pillDanger}`}>OPEN CRITICAL</span>
              ) : (
                <span className={`${styles.pill} ${styles.pillOk}`}>NONE</span>
              )}
            </span>
            <span className={styles.cardHint}>A critical incident forces HALTED.</span>
          </div>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Incident Log</span>
            <span className={styles.row}>
              <button type="button" className={styles.btn} onClick={load}>
                Refresh
              </button>
            </span>
          </div>
          {loaded && incidents.length === 0 ? (
            <div className={styles.empty}>No incidents recorded.</div>
          ) : (
            <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Severity</th>
                  <th>Component</th>
                  <th>Trigger</th>
                  <th>System State</th>
                  <th>Action</th>
                  <th>Detected</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visible.map(inc => (
                  <tr key={inc.incident_id}>
                    <td className={styles.mono}>{inc.incident_id}</td>
                    <td>
                      <span className={`${styles.pill} ${severityClass(inc.severity)}`}>
                        {inc.severity}
                      </span>
                    </td>
                    <td>{inc.component}</td>
                    <td>{inc.trigger}</td>
                    <td>{inc.system_state || '—'}</td>
                    <td>{inc.action_taken || '—'}</td>
                    <td className={styles.mono}>
                      {inc.detected_at ? inc.detected_at.slice(0, 19).replace('T', ' ') : '—'}
                    </td>
                    <td>
                      {inc.open ? (
                        <span className={`${styles.pill} ${styles.pillWarn}`}>OPEN</span>
                      ) : (
                        <span className={`${styles.pill} ${styles.pillOk}`}>RESOLVED</span>
                      )}
                    </td>
                    <td>
                      {inc.open && (
                        <button
                          type="button"
                          className={styles.btn}
                          onClick={() => resolve(inc.incident_id)}
                        >
                          Resolve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {incidents.length > 0 && (
              <Pagination
                page={safePage}
                pageSize={pageSize}
                total={incidents.length}
                onPageChange={setPage}
                onPageSizeChange={setPageSize}
                unitLabel="incidents"
              />
            )}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
