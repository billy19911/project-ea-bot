'use client';

import { useCallback, useState } from 'react';
import styles from './page.module.css';
import { apiFetch } from '../../lib/api';
import { useAutoRefresh } from '../../lib/useAutoRefresh';
import AppShell from '../../components/AppShell';

// ── Types ───────────────────────────────────────────────────────────────────
interface DecisionLevels {
  direction?: string | null;
  entry?: number | null;
  sl?: number | null;
  tp1?: number | null;
  tp2?: number | null;
  tpmax?: number | null;
  risk_distance?: number | null;
  rr?: number | null;
  source?: string | null;
}

interface AgentResult {
  agent?: string;
  signal?: string;
  confidence?: number | null;
  reasoning?: string;
  reasons?: string[];
  evidence?: unknown[];
}

interface DecisionRecord {
  event_id?: string;
  task_id?: string;
  decision_id?: string;
  decision?: string;
  status?: string;
  risk_approved?: boolean;
  risk_reason?: string;
  executed?: boolean;
  execution_result?: { ticket?: number | string } | null;
  event_type?: string;
  confidence?: number | null;
  summary?: string;
  trace_id?: string;
  symbol?: string;
  levels?: DecisionLevels | null;
  agent_results?: Record<string, AgentResult> | null;
  supervisor_summary?: string;
  /** Epoch detik — ditambahkan runtime saat mencatat siklus. */
  recorded_at?: number;
}

interface ControlAgent {
  name: string;
  type: string;
  status: string;
  priority?: number | null;
  invocations?: number | null;
  errors?: number | null;
  errorRate?: number | null;
  avgConfidence?: number | null;
  lastActive?: string | number | null;
  signalCounts?: Record<string, number>;
}

interface ControlStatus {
  supervisor?: {
    status?: string;
    routing_policy?: string;
    max_concurrency?: number | null;
    token_budget?: number | null;
    token_used?: number | null;
    uptime?: number | null;
  };
  agents?: ControlAgent[];
}

interface Lesson {
  id?: string;
  category?: string;
  outcome?: string;
  symbol?: string;
  text?: string;
}

interface LearningAnalytics {
  available?: boolean;
  lessons?: Lesson[];
  total?: number;
}

// ── Helpers ─────────────────────────────────────────────────────────────────
// Harga: > 100 → 2 desimal (XAUUSD), <= 100 → 5 desimal. null/undefined → '—'.
function formatPrice(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value > 100 ? value.toFixed(2) : value.toFixed(5);
}

// Epoch detik (angka/string digit) atau ISO string → "HH:MM" lokal. Absen → '—'.
function formatClock(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  let date: Date;
  if (typeof value === 'number') {
    date = new Date(value * 1000);
  } else if (/^\d+$/.test(value)) {
    date = new Date(Number(value) * 1000);
  } else {
    date = new Date(value);
  }
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
}

function initials(name: string): string {
  const trimmed = (name || '').trim();
  return trimmed ? trimmed.charAt(0).toUpperCase() : '?';
}

// Chip signal: BULLISH/BUY → trendUp, BEARISH/SELL → trendDown, else muted.
function signalClass(signal: string | undefined): string {
  const s = String(signal || '').toUpperCase();
  if (s.includes('BULL') || s.includes('BUY')) return styles.trendUp;
  if (s.includes('BEAR') || s.includes('SELL')) return styles.trendDown;
  return styles.chipMuted;
}

// Badge status keputusan.
function statusBadgeClass(status: string | undefined): string {
  switch ((status || '').toUpperCase()) {
    case 'EXECUTED': return styles.badgeOk;
    case 'BLOCKED': return styles.badgeBlock;
    default: return styles.badgeMuted;
  }
}

// Badge outcome pelajaran: tp/win/profit → ok, sl/loss → block, else muted.
function outcomeBadgeClass(outcome: string | undefined): string {
  const s = String(outcome || '').toLowerCase();
  if (s.includes('tp') || s.includes('win') || s.includes('profit')) return styles.badgeOk;
  if (s.includes('sl') || s.includes('loss')) return styles.badgeBlock;
  return styles.badgeMuted;
}

function formatConf(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `conf ${value.toFixed(2)}` : 'conf —';
}

// Tipe agent untuk label bubble. Map dari /ai-control/status tidak memuat
// specialist, jadi lead/analyst diberi fallback di tempat (tanpa fetch baru).
function agentTypeLabel(name: string, typeByName: Map<string, string>): string {
  const known = typeByName.get(name);
  if (known) return known;
  if (name === 'market_lead' || name.endsWith('_lead')) return 'Market Lead';
  if (name.endsWith('_analyst') || name === 'news_sentiment') return 'Market Analyst';
  return '-';
}

// Hitung konsensus dari entry agent: BULLISH/BEARISH/NETRAL.
type Consensus = { total: number; bullish: number; bearish: number; neutral: number };

function classifySignal(signal: string | undefined): 'BULLISH' | 'BEARISH' | 'NEUTRAL' {
  const s = String(signal || '').toUpperCase();
  if (s.includes('BULL') || s.includes('BUY')) return 'BULLISH';
  if (s.includes('BEAR') || s.includes('SELL')) return 'BEARISH';
  return 'NEUTRAL';
}

function collectConsensus(entries: [string, AgentResult][]): Consensus {
  const c: Consensus = { total: entries.length, bullish: 0, bearish: 0, neutral: 0 };
  for (const [, result] of entries) {
    const kind = classifySignal(result?.signal);
    if (kind === 'BULLISH') c.bullish += 1;
    else if (kind === 'BEARISH') c.bearish += 1;
    else c.neutral += 1;
  }
  return c;
}

function formatAvgConf(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
}

// Evidence bisa berupa string atau objek — jangan pernah render objek mentah.
function evidenceText(item: unknown): string {
  if (typeof item === 'string') return item;
  try {
    return JSON.stringify(item);
  } catch {
    return String(item);
  }
}

// Thin wrapper: hanya 2xx OK yang diterima sebagai data (pola observability)
// supaya body error 401/503 tidak pernah disimpan seolah data nyata.
async function fetchJson(
  path: string,
): Promise<{ ok: boolean; status: number; data: any }> {
  try {
    const res = await apiFetch(path);
    if (!res.ok) return { ok: false, status: res.status, data: null };
    const data = await res.json();
    return { ok: true, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  }
}

// ── Component ───────────────────────────────────────────────────────────────
export default function AgentsPage() {
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [status, setStatus] = useState<ControlStatus | null>(null);
  const [learning, setLearning] = useState<LearningAnalytics | null>(null);
  const [selected, setSelected] = useState<DecisionRecord | null>(null);
  const [errors, setErrors] = useState<{ decisions?: string; status?: string; learning?: string }>({});
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const [decRes, statusRes, learnRes] = await Promise.allSettled([
      fetchJson('/decisions?limit=20'),
      fetchJson('/ai-control/status'),
      fetchJson('/learning/analytics'),
    ]);

    const nextErrors: { decisions?: string; status?: string; learning?: string } = {};

    // Keputusan komite.
    if (decRes.status === 'fulfilled' && decRes.value.ok) {
      const list = Array.isArray(decRes.value.data?.decisions)
        ? (decRes.value.data.decisions as DecisionRecord[])
        : [];
      setDecisions(list);
      // Pertahankan siklus terpilih bila masih ada; selain itu → terbaru.
      setSelected((prev) => {
        if (prev?.decision_id) {
          const still = list.find((d) => d.decision_id === prev.decision_id);
          if (still) return still;
        }
        return list[0] ?? null;
      });
    } else {
      nextErrors.decisions = 'Gagal memuat daftar keputusan.';
    }

    // Status agent.
    if (
      statusRes.status === 'fulfilled' &&
      statusRes.value.ok &&
      statusRes.value.data &&
      Array.isArray(statusRes.value.data?.agents)
    ) {
      setStatus(statusRes.value.data as ControlStatus);
    } else {
      nextErrors.status = 'Gagal memuat status agent.';
    }

    // Pelajaran.
    if (learnRes.status === 'fulfilled' && learnRes.value.ok) {
      setLearning(learnRes.value.data as LearningAnalytics);
    } else {
      nextErrors.learning = 'Gagal memuat pelajaran.';
    }

    setErrors(nextErrors);
    setLoaded(true);
  }, []);

  useAutoRefresh(load);

  const agentList = status?.agents ?? [];
  const agentTypeByName = new Map<string, string>();
  for (const a of agentList) {
    if (a?.name) agentTypeByName.set(a.name, a.type ?? '-');
  }

  // Store is append-only (oldest first): show the 10 LATEST, newest on top.
  const allLessons = Array.isArray(learning?.lessons) ? learning!.lessons ?? [] : [];
  const lessons = allLessons.slice(-10).reverse();
  const totalLessons =
    typeof learning?.total === 'number' ? learning.total : allLessons.length;

  const activeAgentCount = agentList.filter((a) => a.status === 'active').length;
  const lastCycleAt = decisions[0]?.recorded_at ?? null;

  const agentEntries = selected?.agent_results
    ? Object.entries(selected.agent_results)
    : [];

  const consensus = collectConsensus(agentEntries);

  // "Agent nyala" hanya untuk siklus terbaru (decisions[0]).
  const viewingLatest =
    !!selected && !!decisions[0] &&
    (selected.decision_id
      ? selected.decision_id === decisions[0].decision_id
      : selected === decisions[0]);

  return (
    <AppShell activeKey="agents" eyebrow="Xynn / Agents" title="Ruang Komite">
      <div className={styles.wrap}>
        <div className={styles.left}>
          {!loaded && <p className={styles.muted}>Memuat…</p>}

          {/* A. Ringkasan */}
          <div className={styles.summaryRow}>
            <div className={`${styles.card} ${styles.summaryCard}`}>
              <span className={styles.summaryLabel}>Total siklus</span>
              <span className={styles.summaryValue}>{decisions.length}</span>
            </div>
            <div className={`${styles.card} ${styles.summaryCard}`}>
              <span className={styles.summaryLabel}>Siklus terakhir (HH:MM)</span>
              <span className={styles.summaryValue}>{formatClock(lastCycleAt)}</span>
            </div>
            <div className={`${styles.card} ${styles.summaryCard}`}>
              <span className={styles.summaryLabel}>Agent aktif</span>
              <span className={styles.summaryValue}>{activeAgentCount}</span>
            </div>
          </div>

          {errors.decisions && <p className={styles.inlineError}>{errors.decisions}</p>}

          {/* B. Percakapan */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>💬 Percakapan Komite</h2>

            {!selected ? (
              <div className={styles.empty}>Belum ada data komite pada siklus ini.</div>
            ) : (
              <div key={selected.decision_id || selected.event_id || 'cycle'}>
                {/* 1. Bubble Supervisor */}
                <div
                  className={`${styles.bubble} ${styles.bubbleSupervisor} ${styles.bubbleIn}`}
                  style={{ animationDelay: '0ms' }}
                >
                  <span className={`${styles.avatar} ${styles.avatarSupervisor}`}>🧠</span>
                  <div className={styles.bubbleBody}>
                    <div className={styles.bubbleHead}>
                      <span className={styles.agentName}>Supervisor</span>
                      {status?.supervisor?.routing_policy && (
                        <span className={styles.chip}>
                          routing: {status.supervisor.routing_policy}
                        </span>
                      )}
                    </div>
                    <p className={styles.reasoning}>
                      {`Rapat Komite dibuka — ${selected.symbol || '—'} · ${selected.event_type || '—'}. Semua agent Market memberi kontribusi; satu keputusan disimpulkan di Sintesis.`}
                    </p>
                  </div>
                </div>

                {/* 2. Bubble tiap agent */}
                {agentEntries.length === 0 ? (
                  <div className={styles.empty}>Belum ada data komite pada siklus ini.</div>
                ) : (
                  agentEntries.map(([name, result], index) => {
                    const signal = result?.signal;
                    const confidence =
                      typeof result?.confidence === 'number' ? result.confidence : null;
                    const clamp =
                      confidence === null ? 0 : Math.max(0, Math.min(100, confidence * 100));
                    const evidence = Array.isArray(result?.evidence) ? result!.evidence! : [];
                    const shownEvidence = evidence.slice(0, 3);
                    const type = agentTypeLabel(name, agentTypeByName);
                    return (
                      <div
                        key={name}
                        className={`${styles.bubble} ${styles.bubbleIn}`}
                        style={{ animationDelay: `${index * 120}ms` }}
                      >
                        <span
                          className={`${styles.avatar} ${viewingLatest ? styles.avatarLive : ''}`}
                        >
                          {initials(name)}
                        </span>
                        <div className={styles.bubbleBody}>
                          <div className={styles.bubbleHead}>
                            <span className={styles.agentName}>{name}</span>
                            <span className={styles.chip}>{type}</span>
                            <span className={`${styles.chip} ${signalClass(signal)}`}>
                              {String(signal || 'NEUTRAL')}
                            </span>
                          </div>

                          <div className={styles.confWrap}>
                            <span className={styles.confBar}>
                              <span className={styles.confFill} style={{ width: `${clamp}%` }} />
                            </span>
                            <span className={styles.confText}>{formatConf(confidence)}</span>
                          </div>

                          {result?.reasoning && (
                            <p className={styles.reasoning}>{result.reasoning}</p>
                          )}

                          {shownEvidence.length > 0 && (
                            <ul className={styles.evidence}>
                              {shownEvidence.map((item, i) => (
                                <li key={i}>{evidenceText(item)}</li>
                              ))}
                              {evidence.length > 3 && (
                                <li className={styles.moreEvidence}>
                                  +{evidence.length - 3} lagi
                                </li>
                              )}
                            </ul>
                          )}
                        </div>
                      </div>
                    );
                  })
                )}

                {/* 3. Bubble Sintesis */}
                <div
                  className={`${styles.bubble} ${styles.bubbleSynthesis} ${styles.bubbleIn}`}
                  style={{ animationDelay: `${agentEntries.length * 120}ms` }}
                >
                  <span className={styles.avatar}>🧩</span>
                  <div className={styles.bubbleBody}>
                    <div className={styles.bubbleHead}>
                      <span className={styles.agentName}>🧩 Sintesis Komite</span>
                      <span className={`${styles.mono} ${styles.agentName}`}>
                        {selected.decision || '—'}
                      </span>
                      <span className={statusBadgeClass(selected.status)}>
                        {selected.status || '—'}
                      </span>
                    </div>

                    <div className={styles.consensusBar}>
                      <span className={styles.chip}>{consensus.total} agent</span>
                      <span className={`${styles.chip} ${styles.trendUp}`}>
                        BULLISH {consensus.bullish}
                      </span>
                      <span className={`${styles.chip} ${styles.trendDown}`}>
                        BEARISH {consensus.bearish}
                      </span>
                      <span className={styles.chipMuted}>NETRAL {consensus.neutral}</span>
                    </div>

                    {selected.levels && (
                      <dl className={styles.levels}>
                        <dt>Entry</dt><dd>{formatPrice(selected.levels.entry)}</dd>
                        <dt>SL</dt><dd>{formatPrice(selected.levels.sl)}</dd>
                        <dt>TP1</dt><dd>{formatPrice(selected.levels.tp1)}</dd>
                        <dt>TP2</dt><dd>{formatPrice(selected.levels.tp2)}</dd>
                        <dt>TPmax</dt><dd>{formatPrice(selected.levels.tpmax)}</dd>
                      </dl>
                    )}

                    {selected.risk_reason && (
                      <div className={styles.metaLine}>
                        <span>⛔ {selected.risk_reason}</span>
                      </div>
                    )}

                    {selected.execution_result?.ticket !== undefined &&
                      selected.execution_result?.ticket !== null && (
                        <div className={styles.metaLine}>
                          <span>🎫 ticket {selected.execution_result.ticket}</span>
                        </div>
                      )}

                    {selected.trace_id && (
                      <div className={styles.metaLine}>
                        <span className={styles.muted}>🔎 trace {selected.trace_id}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* C. Riwayat siklus */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>🕑 Riwayat Siklus</h2>
            {decisions.length === 0 ? (
              <div className={styles.empty}>Belum ada siklus terekam.</div>
            ) : (
              <div className={styles.history}>
                {decisions.map((d, i) => {
                  const isActive = !!selected &&
                    (selected.decision_id
                      ? d.decision_id === selected.decision_id
                      : d === selected);
                  return (
                    <button
                      type="button"
                      key={d.decision_id || d.event_id || i}
                      className={`${styles.historyRow} ${isActive ? styles.historyActive : ''}`}
                      onClick={() => setSelected(d)}
                    >
                      <span className={styles.historyTime}>
                        {formatClock(d.recorded_at ?? null)}
                      </span>
                      <span className={styles.historySymbol}>{d.symbol || '—'}</span>
                      <span className={styles.historyDecision}>{d.decision || '—'}</span>
                      <span className={styles.historyStatus}>{d.status || '—'}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* D. Sidebar */}
        <aside className={styles.sidebar}>
          {errors.status && <p className={styles.inlineError}>{errors.status}</p>}
          <div className={styles.panel}>
            <h2 className={styles.panelTitle}>👥 Anggota</h2>
            {agentList.length === 0 ? (
              <p className={styles.muted}>Belum ada agent terdaftar.</p>
            ) : (
              agentList.map((a) => (
                <div key={a.name} className={styles.memberRow}>
                  <span className={a.status === 'active' ? styles.dotLive : styles.dotIdle} />
                  <div className={styles.memberMain}>
                    <div className={styles.memberName}>{a.name}</div>
                    <div className={styles.memberMeta}>
                      {a.invocations ?? 0}× · conf {formatAvgConf(a.avgConfidence)}
                      {a.lastActive !== null && a.lastActive !== undefined
                        ? ` · ${formatClock(a.lastActive)}`
                        : ''}
                    </div>
                  </div>
                  <span className={styles.chip}>{a.type || '-'}</span>
                </div>
              ))
            )}
          </div>

          {errors.learning && <p className={styles.inlineError}>{errors.learning}</p>}
          <div className={styles.panel}>
            <h2 className={styles.panelTitle}>📚 Pelajaran</h2>
            {!learning?.available || lessons.length === 0 ? (
              <p className={styles.muted}>Belum ada pelajaran terekam.</p>
            ) : (
              <>
                <p className={styles.muted}>
                  {lessons.length} terbaru dari {totalLessons} pelajaran
                </p>
                {lessons.map((lesson, i) => (
                  <div key={lesson.id || i} className={styles.lesson}>
                    <div className={styles.lessonHead}>
                      <span className={outcomeBadgeClass(lesson.outcome)}>
                        {lesson.outcome || '—'}
                      </span>
                      {lesson.symbol && <span className={styles.lessonSymbol}>{lesson.symbol}</span>}
                    </div>
                    {lesson.text && <p className={styles.lessonText}>{lesson.text}</p>}
                  </div>
                ))}
              </>
            )}
          </div>
        </aside>
      </div>
    </AppShell>
  );
}
