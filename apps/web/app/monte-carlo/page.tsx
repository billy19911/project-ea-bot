'use client';

import { useEffect, useMemo, useState } from 'react';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import { useApiData, fmtNum, fmtPct, errorMessageFor } from '@/lib/useApiData';
import { PARAM_LABELS, labelFor } from '@/lib/labels';
import { LoadingState } from '@/components/ui/loading-state';
import styles from '@/components/ops.module.css';

/**
 * Monte Carlo — real robustness statistics for a chosen research experiment.
 *
 * Data source: `GET /research/experiments/:id` → `metrics.monte_carlo`, which
 * is `MonteCarloResult.to_dict()` from the Python engine:
 *   median_return, 5th_percentile_return, 95th_percentile_drawdown,
 *   worst_drawdown, max_loss_streak, probability_severe_drawdown, status.
 *
 * No simulation is re-run in the browser and nothing is synthesized — if the
 * experiment has no Monte Carlo block yet, we say so explicitly.
 */

type Experiment = { id?: string; label?: string; strategy_type?: string; status?: string };
type ExperimentsBody = { experiments?: Experiment[] };

type MC = {
  median_return?: number;
  '5th_percentile_return'?: number;
  '95th_percentile_drawdown'?: number;
  worst_drawdown?: number;
  max_loss_streak?: number;
  probability_severe_drawdown?: number;
  status?: string;
};

type DetailBody = {
  ok?: boolean;
  metrics?: { monte_carlo?: MC } | null;
  trades_total?: number;
};

export default function MonteCarloPage() {
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

  const mc: MC | undefined = detail?.metrics?.monte_carlo ?? undefined;
  const hasMC = mc != null;

  return (
    <AppShell activeKey="monte-carlo" eyebrow="Xynn / Riset" title="Monte Carlo">
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
                No research experiments yet. Create one on the Research page and run a backtest —
                the Monte Carlo block is produced as part of that run.
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

        {detailError && <div className={styles.error}>{detailError}</div>}

        {loadingDetail ? (
          <LoadingState rows={6} />
        ) : !hasMC ? (
          <div className={styles.notice}>
            This experiment has no Monte Carlo result yet — run a backtest to produce one. The
            page shows nothing rather than placeholder numbers.
          </div>
        ) : (
          <>
            <div className={styles.grid}>
              <div className={styles.card}>
                <span className={styles.cardLabel}>Median return</span>
                <span className={styles.cardValue}>{fmtNum(mc!.median_return, 2)}</span>
                <span className={styles.cardHint}>simulations</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>5th pct return</span>
                <span className={styles.cardValue}>
                  {fmtNum(mc!['5th_percentile_return'], 2)}
                </span>
                <span className={styles.cardHint}>downside</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>95th pct drawdown</span>
                <span className={styles.cardValue}>
                  {fmtPct(mc!['95th_percentile_drawdown'], 2)}
                </span>
                <span className={styles.cardHint}>tail risk</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>Worst drawdown</span>
                <span className={styles.cardValue}>{fmtPct(mc!.worst_drawdown, 2)}</span>
                <span className={styles.cardHint}>observed extreme</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>Max loss streak</span>
                <span className={styles.cardValue}>{mc!.max_loss_streak ?? '—'}</span>
                <span className={styles.cardHint}>consecutive</span>
              </div>
              <div className={styles.card}>
                <span className={styles.cardLabel}>P(severe DD)</span>
                <span className={styles.cardValue}>
                  {fmtPct(mc!.probability_severe_drawdown, 2)}
                </span>
                <span className={styles.cardHint}>probability</span>
              </div>
            </div>

            <div className={styles.panel}>
              <div className={styles.panelHead}>
                <span className={styles.panelTitle}>Verdict</span>
                <span
                  className={
                    String(mc!.status).toUpperCase() === 'PASSED'
                      ? `${styles.pill} ${styles.pillOk}`
                      : `${styles.pill} ${styles.pillDanger}`
                  }
                >
                  {mc!.status ?? '—'}
                </span>
              </div>
              <div className={styles.panelBody}>
                <div className={styles.kv}>
                  <span className={styles.kvKey}>Trades evaluated</span>
                  <span className={styles.kvVal}>{detail?.trades_total ?? '—'}</span>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
