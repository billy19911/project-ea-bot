'use client';

import { useEffect, useMemo, useState } from 'react';
import AppShell from '@/components/AppShell';
import { apiFetch } from '@/lib/api';
import { useApiData, errorMessageFor } from '@/lib/useApiData';
import styles from '@/components/ops.module.css';

/**
 * Decision Replay — pick a real decision, then replay its recorded snapshot
 * (`/v2/decision/:id/replay`, Phase 45).
 *
 * The decision list is real (`/decisions`); the replay is fetched on demand so
 * we never call the replay endpoint with a fabricated id.
 */

type Decision = {
  decision_id?: string;
  event_type?: string;
  symbol?: string;
  status?: string;
  decision?: string;
};

type DecisionsBody = { decisions?: Decision[] };

type ReplayBody = { value?: unknown; status?: string; source?: string };

export default function DecisionReplayPage() {
  const list = useApiData<DecisionsBody>('/decisions');
  const decisions = useMemo(
    () => (Array.isArray(list.data?.decisions) ? list.data!.decisions! : []),
    [list.data]
  );

  const [selected, setSelected] = useState<string>('');
  const [replay, setReplay] = useState<ReplayBody | null>(null);
  const [replayError, setReplayError] = useState<string | null>(null);
  const [loadingReplay, setLoadingReplay] = useState(false);

  // Auto-select the newest decision once the list arrives.
  useEffect(() => {
    if (!selected && decisions.length > 0 && decisions[0].decision_id) {
      setSelected(String(decisions[0].decision_id));
    }
  }, [decisions, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoadingReplay(true);
    setReplayError(null);
    (async () => {
      try {
        const res = await apiFetch(`/v2/decision/${encodeURIComponent(selected)}/replay`);
        const body = (await res.json().catch(() => ({}))) as ReplayBody;
        if (cancelled) return;
        setReplay(body);
        if (!res.ok) setReplayError(errorMessageFor(res.status));
      } catch {
        if (!cancelled) setReplayError('Could not reach the API.');
      } finally {
        if (!cancelled) setLoadingReplay(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const current = decisions.find((d) => String(d.decision_id) === selected) ?? null;
  const replayValue = replay?.value;

  return (
    <AppShell activeKey="decision-replay" eyebrow="Xynn / Decisions" title="Decision Replay">
      <div className={styles.wrap}>
        {list.error && <div className={styles.error}>{list.error}</div>}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Select decision</span>
            <button type="button" className={styles.btn} onClick={list.refresh}>
              Refresh list
            </button>
          </div>
          <div className={styles.panelBody}>
            {decisions.length === 0 ? (
              <p className={styles.empty}>
                No decisions recorded yet — replay needs at least one stored decision snapshot.
              </p>
            ) : (
              <select
                className={styles.input}
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
                aria-label="Select decision to replay"
              >
                {decisions.map((d) => (
                  <option key={String(d.decision_id)} value={String(d.decision_id)}>
                    {d.decision_id} · {d.event_type ?? '?'} · {d.symbol ?? '?'} · {d.status ?? '?'}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {current && (
          <div className={styles.grid}>
            <div className={styles.card}>
              <span className={styles.cardLabel}>Decision</span>
              <span className={styles.cardValue} style={{ fontSize: 'var(--fs-lg)' }}>
                {current.decision ?? '—'}
              </span>
              <span className={styles.cardHint}>{current.event_type ?? '—'}</span>
            </div>
            <div className={styles.card}>
              <span className={styles.cardLabel}>Symbol</span>
              <span className={styles.cardValue} style={{ fontSize: 'var(--fs-lg)' }}>
                {current.symbol ?? '—'}
              </span>
              <span className={styles.cardHint}>original status: {current.status ?? '—'}</span>
            </div>
          </div>
        )}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Replayed snapshot</span>
            <span className={styles.cardHint}>
              {loadingReplay ? 'loading…' : replay?.status ?? '—'}
            </span>
          </div>
          <div className={styles.panelBody}>
            {replayError && <div className={styles.error}>{replayError}</div>}
            {!selected ? (
              <p className={styles.empty}>Select a decision to replay.</p>
            ) : loadingReplay ? (
              <p className={styles.empty}>Loading replay…</p>
            ) : replayValue == null ? (
              <p className={styles.empty}>
                No stored snapshot for this decision — replay is honest about missing data instead
                of inventing a graph.
              </p>
            ) : (
              <pre className={styles.mono} style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                {JSON.stringify(replayValue, null, 2)}
              </pre>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
