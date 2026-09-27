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

type ReplayStep = {
  stage?: string;
  payload?: Record<string, unknown>;
  timestamp?: string;
};

type ReplayValue = {
  decision_id?: string;
  event_id?: string;
  trade_id?: string;
  execution_id?: string;
  strategy_version?: string;
  created_at?: string;
  steps?: ReplayStep[];
};

/** Human labels + a semantic tone per stage so the timeline is scannable. */
const STAGE_META: Record<string, { label: string; tone: string }> = {
  EVENT: { label: 'Event', tone: 'pillNeutral' },
  MARKET_SNAPSHOT: { label: 'Market snapshot', tone: 'pillNeutral' },
  AGENTS_ACTIVATED: { label: 'Agents activated', tone: 'pillNeutral' },
  AGENT_OUTPUTS: { label: 'Agent outputs', tone: 'pillNeutral' },
  CONFLICTS: { label: 'Conflicts', tone: 'pillWarn' },
  SUPERVISOR_SUMMARY: { label: 'Supervisor summary', tone: 'pillNeutral' },
  TRADE_PROPOSAL: { label: 'Trade proposal', tone: 'pillOk' },
  RISK_CHECKS: { label: 'Risk checks', tone: 'pillWarn' },
  EXECUTION: { label: 'Execution', tone: 'pillOk' },
  BROKER_RESULT: { label: 'Broker result', tone: 'pillOk' },
  POSITION: { label: 'Position', tone: 'pillOk' },
  RESULT: { label: 'Result', tone: 'pillNeutral' },
  REVIEW: { label: 'Review', tone: 'pillNeutral' },
};

function stageMeta(stage: string | undefined) {
  const key = String(stage ?? '').toUpperCase();
  return STAGE_META[key] ?? { label: key || 'Step', tone: 'pillNeutral' };
}

function fmtTime(ts: string | undefined): string {
  if (!ts) return '—';
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

/** Render a payload value compactly (primitives inline, objects as JSON). */
function PayloadValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>—</span>;
  if (typeof value === 'boolean') return <span>{value ? 'true' : 'false'}</span>;
  if (typeof value === 'number' || typeof value === 'string') {
    return <span className={styles.mono}>{String(value)}</span>;
  }
  return (
    <pre className={styles.mono} style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

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
  const replayValue = replay?.value as ReplayValue | null | undefined;
  const steps = Array.isArray(replayValue?.steps) ? replayValue!.steps! : [];
  const [showRaw, setShowRaw] = useState(false);

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
              <span className={`${styles.cardValue} ${styles.cardValueSm}`}>
                {current.decision ?? '—'}
              </span>
              <span className={styles.cardHint}>{current.event_type ?? '—'}</span>
            </div>
            <div className={styles.card}>
              <span className={styles.cardLabel}>Symbol</span>
              <span className={`${styles.cardValue} ${styles.cardValueSm}`}>
                {current.symbol ?? '—'}
              </span>
              <span className={styles.cardHint}>original status: {current.status ?? '—'}</span>
            </div>
          </div>
        )}

        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <span className={styles.panelTitle}>Replayed snapshot</span>
            <div className={styles.row}>
              <button
                type="button"
                className={styles.btn}
                onClick={() => setShowRaw((v) => !v)}
                disabled={replayValue == null}
              >
                {showRaw ? 'Timeline view' : 'Raw JSON'}
              </button>
              <span className={styles.cardHint}>
                {loadingReplay ? 'loading…' : replay?.status ?? '—'}
              </span>
            </div>
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
            ) : showRaw ? (
              <pre className={styles.mono} style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                {JSON.stringify(replayValue, null, 2)}
              </pre>
            ) : (
              <>
                {/* Correlation ids */}
                <div className={styles.kvGrid}>
                  <div className={styles.kv}>
                    <span className={styles.kvKey}>Decision</span>
                    <span className={styles.kvVal}>{replayValue.decision_id || '—'}</span>
                  </div>
                  <div className={styles.kv}>
                    <span className={styles.kvKey}>Event</span>
                    <span className={styles.kvVal}>{replayValue.event_id || '—'}</span>
                  </div>
                  <div className={styles.kv}>
                    <span className={styles.kvKey}>Strategy</span>
                    <span className={styles.kvVal}>{replayValue.strategy_version || '—'}</span>
                  </div>
                  <div className={styles.kv}>
                    <span className={styles.kvKey}>Created</span>
                    <span className={styles.kvVal}>{fmtTime(replayValue.created_at)}</span>
                  </div>
                </div>

                {/* Stage timeline */}
                {steps.length === 0 ? (
                  <p className={styles.empty}>Snapshot has no recorded stages.</p>
                ) : (
                  <ol className={styles.timeline}>
                    {steps.map((step, i) => {
                      const meta = stageMeta(step.stage);
                      const entries = Object.entries(step.payload ?? {});
                      return (
                        <li key={`${step.stage ?? 'step'}-${i}`} className={styles.timelineItem}>
                          <div className={styles.timelineHead}>
                            <span className={`${styles.pill} ${styles[meta.tone] ?? ''}`}>
                              {meta.label}
                            </span>
                            <span className={styles.cardHint}>{fmtTime(step.timestamp)}</span>
                          </div>
                          {entries.length === 0 ? (
                            <p className={styles.cardHint}>No payload.</p>
                          ) : (
                            <div className={styles.kvGrid}>
                              {entries.map(([k, v]) => (
                                <div key={k} className={styles.kv}>
                                  <span className={styles.kvKey}>{k}</span>
                                  <span className={styles.kvVal}>
                                    <PayloadValue value={v} />
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
