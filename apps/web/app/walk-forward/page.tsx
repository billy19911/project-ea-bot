'use client';

import { useEffect, useMemo, useState } from 'react';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import { useApiData, errorMessageFor } from '@/lib/useApiData';
import { COLUMN_LABELS, PARAM_LABELS, labelFor } from '@/lib/labels';
import styles from '@/components/ops.module.css';

/**
 * Walk-Forward — real walk-forward windows for a chosen research experiment.
 *
 * Data source: `GET /research/experiments/:id`, which returns the engine's real
 * `walk_forward` block (`{windows, per-window metrics}`) alongside `metrics`.
 * We never fabricate windows: an experiment without a backtest shows an honest
 * empty state telling the operator to run one first.
 */

type Experiment = {
  id?: string;
  label?: string;
  strategy_type?: string;
  status?: string;
};

type ExperimentsBody = { ok?: boolean; experiments?: Experiment[]; count?: number };

type Window = Record<string, unknown>;

type DetailBody = {
  ok?: boolean;
  experiment?: Experiment;
  metrics?: Record<string, unknown> | null;
  walk_forward?: { windows?: Window[]; [k: string]: unknown } | null;
  trades_total?: number;
  provenance?: Record<string, unknown> | null;
};

function cell(v: unknown): string {
  if (v == null) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4);
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export default function WalkForwardPage() {
  const list = useApiData<ExperimentsBody>('/research/experiments');
  const experiments = useMemo(
    () => (Array.isArray(list.data?.experiments) ? list.data!.experiments! : []),
    [list.data]
  );

  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<DetailBody | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    if (!selected && experiments.length > 0 && experiments[0].id) {
      setSelected(String(experiments[0].id));
    }
  }, [experiments, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoadingDetail(true);
    setDetailError(null);
    (async () => {
      try {
        const res = await apiFetch(`/research/experiments/${encodeURIComponent(selected)}`);
        const body = (await res.json().catch(() => ({}))) as DetailBody;
        if (cancelled) return;
        setDetail(body);
        if (!res.ok || body.ok === false) setDetailError(errorMessageFor(res.status));
      } catch {
        if (!cancelled) setDetailError('Could not reach the API.');
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const windows = Array.isArray(detail?.walk_forward?.windows)
    ? (detail!.walk_forward!.windows as Window[])
    : [];
  const columns = windows.length > 0 ? Object.keys(windows[0]) : [];

  return (
    <AppShell activeKey="walk-forward" eyebrow="Xynn / Riset" title="Walk-Forward">
      <div className={styles.wrap}>
        {list.error && <div className={styles.error}>{list.error}</div>}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Select experiment</span>
            <button type="button" className={styles.btn} onClick={list.refresh}>
              Refresh list
            </button>
          </div>
          <div className={styles.panelBody}>
            {experiments.length === 0 ? (
              <p className={styles.empty}>
                No research experiments yet. Create one on the Research page, run a backtest, then
                its walk-forward windows appear here.
              </p>
            ) : (
              <select
                className={styles.input}
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                aria-label="Select experiment"
              >
                {experiments.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {x.label || x.id} · {labelFor(PARAM_LABELS, String(x.strategy_type ?? '?'))} ·{' '}
                    {x.status ?? '?'}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Walk-forward windows</span>
            <span className={styles.cardHint}>
              {loadingDetail ? 'loading…' : `${windows.length} window(s)`}
            </span>
          </div>
          <div className={styles.panelBody}>
            {detailError && <div className={styles.error}>{detailError}</div>}
            {!selected ? (
              <p className={styles.empty}>Select an experiment to view its windows.</p>
            ) : loadingDetail ? (
              <p className={styles.empty}>Loading…</p>
            ) : windows.length === 0 ? (
              <p className={styles.empty}>
                No walk-forward windows for this experiment yet. Run a backtest
                (`POST /research/experiments/:id/backtest`) over real MT5 bars — walk-forward is
                enabled by default and the windows will show up here.
              </p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th key={c} title={c}>
                        {labelFor(COLUMN_LABELS, c)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {windows.map((w, i) => (
                    <tr key={i}>
                      {columns.map((c) => (
                        <td key={c} className={styles.mono}>
                          {cell(w[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
