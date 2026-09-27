'use client';

// Halaman Pengaturan (UI/UX F4 + ide #7).
//
// Prinsip anti-slop halaman ini: **tidak ada kontrol yang tidak tersambung**.
// Sebelumnya halaman ini adalah form localStorage penuh — termasuk toggle
// "Kill switch" dan "Emergency stop" yang mengklaim memblokir order padahal
// tidak terhubung ke apa pun. Itu teater, dan berbahaya pada akun LIVE.
//
// Sekarang halaman dibagi dua, dan pembagiannya jujur:
//
//  1. "Runtime (tersambung)" — knob yang benar-benar dikonsumsi sistem.
//     Nilainya dibaca dari GET /settings dan disimpan via PUT /settings
//     (diteruskan ke SupervisorAgent.token_budget & Scheduler.poll_interval).
//     Setiap baris menampilkan "dipakai oleh" supaya klaimnya bisa diaudit.
//  2. "Batas risiko (read-only)" — nilai nyata dari RiskEngine/RiskGate yang
//     sedang dipakai. Sengaja tidak bisa diedit dari UI: itu logika safety.
//
// Yang tidak tersambung (notifikasi email/telegram, slippage, timeout, dsb.)
// sudah DIHAPUS, bukan dipalsukan. Kalau nanti disambungkan, baru muncul lagi.

import Head from 'next/head';
import { Fragment, useCallback, useEffect, useState } from 'react';
import styles from '../page.module.css';
import { apiFetch } from '../../lib/api';
import { useAutoRefresh } from '../../lib/useAutoRefresh';
import AppShell from '../../components/AppShell';
import Pagination from '../../components/ui/pagination';

type SourceState = 'live' | 'defaults' | 'unavailable';

type AiModel = { id: string; provider: string; context: number; is_free: boolean; capabilities?: string[] };
type ModelsState = { models: AiModel[]; source: SourceState };

type Knob = {
  key: string;
  kind: string;
  value: number;
  minimum: number;
  maximum: number;
  default: number;
  description: string;
  applied_to: string;
};

type RiskLimits = { available: boolean; limits: Record<string, number | null> };

type SettingsPayload = {
  writable: Knob[];
  values: Record<string, number>;
  risk_limits: RiskLimits;
};

type Notice = { kind: 'ok' | 'error'; text: string } | null;

// Label manusiawi untuk limit risiko (nama kunci datang dari RiskEngine).
const RISK_LABELS: Record<string, string> = {
  max_drawdown: 'Max drawdown (fraksi ekuitas)',
  daily_loss_limit: 'Batas rugi harian (fraksi ekuitas)',
  max_exposure: 'Max exposure (fraksi ekuitas)',
  margin_threshold: 'Ambang margin',
  max_positions: 'Max posisi terbuka',
  max_position_size: 'Max ukuran posisi (fraksi)',
  max_spread_pips: 'Max spread (pips)',
  min_rr: 'Min risk/reward',
};

// Quick presets for fractional knobs — a lot size is easier to pick from a
// shortlist than to type, and avoids the spinner jumping past valid values.
const KNOB_PRESETS: Record<string, number[]> = {
  max_lot_per_trade: [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
  risk_per_trade_pct: [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0],
  scheduler_poll_interval: [0.25, 0.5, 1.0, 2.0, 5.0],
  trend_sample_interval: [5, 10, 15, 30, 60, 120, 300],
};

/** Step for a numeric knob — decimal-aware so floats step finely. */
function knobStep(knob: Knob): number {
  if (knob.kind === 'int') return 1;
  const span = Math.abs((knob.maximum ?? 0) - (knob.minimum ?? 0));
  // Small ranges (0–5) step by 0.01; larger ranges by 0.1.
  return span <= 10 ? 0.01 : 0.1;
}

/** Round a float to a sane number of decimals (avoids 0.30000000000004). */
function roundValue(value: number, step: number): number {
  const decimals = step < 0.1 ? 2 : step < 1 ? 2 : 0;
  return Number(value.toFixed(decimals));
}

/** Parse a draft string into a number, or null when not a finite number. */
function parseKnobValue(raw: string | undefined): number | null {
  if (raw === undefined || raw === '') return null;
  const num = Number(raw);
  if (!Number.isFinite(num)) return null;
  return num;
}

/** True when the draft value is a finite number inside [min, max]. */
function isKnobValid(raw: string | undefined, knob: Knob): boolean {
  const num = parseKnobValue(raw);
  if (num === null) return raw === '' || raw === undefined;
  return num >= knob.minimum && num <= knob.maximum;
}


function KnobNumberField({
  knob,
  value,
  onChange,
}: {
  knob: Knob;
  value: string;
  onChange: (next: string) => void;
}) {
  const step = knobStep(knob);
  const valid = isKnobValid(value, knob);
  const presets = KNOB_PRESETS[knob.key] ?? [];
  const current = Number(value);

  // Stepper: clamp to [min, max] and round to a stable decimal count so the
  // value never drifts (e.g. 0.30000000000004).
  const apply = (next: number) => {
    const clamped = Math.min(Math.max(roundValue(next, step), knob.minimum), knob.maximum);
    onChange(String(clamped));
  };

  return (
    <label className={`${styles.field} ${valid ? '' : styles.fieldInvalid}`}>
      <span>{knob.key}</span>
      <div className={styles.numberRow}>
        <button
          type="button"
          className={styles.stepBtn}
          aria-label={`Kurangi ${knob.key}`}
          onClick={() => apply((Number.isFinite(current) ? current : knob.minimum) - step)}
        >
          −
        </button>
        <input
          type="number"
          inputMode="decimal"
          min={knob.minimum}
          max={knob.maximum}
          step={step}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => {
            // Normalize only on blur (never mid-typing, so the caret is stable
            // and typing "0.5" is not fought by the input).
            const num = Number(value);
            if (Number.isFinite(num)) apply(num);
          }}
        />
        <button
          type="button"
          className={styles.stepBtn}
          aria-label={`Tambah ${knob.key}`}
          onClick={() => apply((Number.isFinite(current) ? current : knob.minimum) + step)}
        >
          +
        </button>
      </div>
      {presets.length > 0 && (
        <div className={styles.presets}>
          {presets.map((p) => (
            <button
              key={p}
              type="button"
              className={`${styles.presetBtn} ${Number(value) === p ? styles.presetActive : ''}`}
              onClick={() => apply(p)}
            >
              {p}
            </button>
          ))}
        </div>
      )}
      {!valid && (
        <small className={styles.invalidHint}>
          Nilai harus angka antara {knob.minimum} dan {knob.maximum}.
        </small>
      )}
      <small className={styles.fieldHint}>
        {knob.description} Rentang {knob.minimum}–{knob.maximum} · dipakai oleh{' '}
        <code>{knob.applied_to}</code>
      </small>
    </label>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState('Runtime');
  const [notice, setNotice] = useState<Notice>(null);
  const [modelsState, setModelsState] = useState<ModelsState>({ models: [], source: 'unavailable' });
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  // Track whether the operator has edited the form. Auto-refresh must NOT wipe
  // unsaved input — that was a real UX bug (every 10 s poll reset the draft).
  const [dirty, setDirty] = useState(false);
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'unauthorized' | 'unavailable'>('loading');
  const [saving, setSaving] = useState(false);
  const [modelPage, setModelPage] = useState(1);
  const [modelPageSize, setModelPageSize] = useState(10);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch(`/settings`);
      if (res.status === 401 || res.status === 403) {
        // Bedakan "belum masuk" dari "service mati": dulu keduanya tampil
        // sebagai 'layanan Python tidak menjawab' — pesan yang menyesatkan.
        setLoadState('unauthorized');
        return;
      }
      if (!res.ok) {
        setLoadState('unavailable');
        return;
      }
      const data: SettingsPayload = await res.json();
      setPayload(data);
      // Only seed the draft when the operator has not started editing; otherwise
      // a background refresh would discard unsaved changes.
      setDirty((isDirty) => {
        if (!isDirty) {
          setDraft(
            Object.fromEntries((data.writable ?? []).map((k) => [k.key, String(k.value)])),
          );
        }
        return isDirty;
      });
      setLoadState('ready');
    } catch {
      setLoadState('unavailable');
    }
  }, []);

  useAutoRefresh(load);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/ai/models`);
        if (!res.ok) {
          if (!cancelled) setModelsState({ models: [], source: 'unavailable' });
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        // `source` may be "live" (dynamic discovery) or "defaults" (gateway
        // unreachable but a built-in model list is served). "defaults" means
        // models ARE available — do not label it "gateway unavailable".
        const src = String(data.source ?? '');
        setModelsState({
          models: Array.isArray(data.models) ? data.models : [],
          source: src === 'live' ? 'live' : src === 'defaults' ? 'defaults' : 'unavailable',
        });
      } catch {
        if (!cancelled) setModelsState({ models: [], source: 'unavailable' });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Page resets whenever the model list identity changes (refresh/reconnect).
  useEffect(() => {
    setModelPage(1);
  }, [modelsState.models]);

  const modelPageCount = Math.max(1, Math.ceil(modelsState.models.length / modelPageSize));
  const safeModelPage = Math.min(modelPage, modelPageCount);
  const visibleModels = modelsState.models.slice(
    (safeModelPage - 1) * modelPageSize,
    safeModelPage * modelPageSize,
  );

  const save = async () => {
    if (!payload) return;
    setSaving(true);
    setNotice(null);
    try {
      // Kirim hanya knob yang berubah dan valid sebagai angka.
      const body: Record<string, number> = {};
      for (const knob of payload.writable) {
        const raw = draft[knob.key];
        if (raw === undefined || raw === '') continue;
        const num = Number(raw);
        if (!Number.isFinite(num)) {
          setNotice({ kind: 'error', text: `Nilai ${knob.key} bukan angka.` });
          setSaving(false);
          return;
        }
        if (num < knob.minimum || num > knob.maximum) {
          setNotice({
            kind: 'error',
            text: `Nilai ${knob.key} harus antara ${knob.minimum} dan ${knob.maximum}.`,
          });
          setSaving(false);
          return;
        }
        if (num !== knob.value) body[knob.key] = num;
      }
      if (Object.keys(body).length === 0) {
        setNotice({ kind: 'ok', text: 'Tidak ada perubahan.' });
        setSaving(false);
        return;
      }
      const res = await apiFetch(`/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data) {
        setNotice({ kind: 'error', text: 'Gagal menyimpan — layanan tidak menjawab.' });
        setSaving(false);
        return;
      }
      if (data.ok === false) {
        const msg = Array.isArray(data.errors) && data.errors.length ? data.errors.join(' · ') : 'Ditolak.';
        setNotice({ kind: 'error', text: msg });
        setSaving(false);
        return;
      }
      const applied = data.applied ?? {};
      const keys = Object.keys(applied);
      setNotice({
        kind: 'ok',
        text: keys.length
          ? `Tersimpan & diterapkan: ${keys.map((k) => `${k} = ${applied[k]}`).join(', ')}`
          : 'Tersimpan.',
      });
      setDirty(false);
      await load();
    } catch {
      setNotice({ kind: 'error', text: 'Gagal menyimpan — layanan tidak menjawab.' });
    } finally {
      setSaving(false);
    }
  };

  const tabs = ['Runtime', 'Batas risiko', 'Model registry'];

  return (
    <>
      <Head>
        <title>EA Bot — Pengaturan</title>
        <meta name="description" content="Pengaturan runtime EA Bot" />
      </Head>
      <AppShell activeKey="settings" eyebrow="Xynn / Settings" title="Pengaturan">
        {notice && (
          <div className={notice.kind === 'error' ? styles.noticeError : styles.notice}>{notice.text}</div>
        )}
        <div className={styles.pageBody}>
          <nav className={styles.tabs} aria-label="Bagian pengaturan">
            {tabs.map((item) => (
              <button key={item} className={tab === item ? styles.tabActive : ''} onClick={() => setTab(item)}>
                {item}
              </button>
            ))}
          </nav>

          {tab === 'Runtime' && (
            <section className={styles.formCard}>
              <div className={styles.formTitle}>
                <h2>Runtime tersambung</h2>
                <p>
                  Hanya knob yang benar-benar dipakai sistem. Setiap baris mencantumkan objek yang membacanya —
                  tidak ada field hiasan.
                </p>
              </div>

              {loadState === 'loading' && <p className={styles.mutedText}>Memuat pengaturan…</p>}

              {dirty && (
                <p className={styles.mutedText}>
                  Ada perubahan belum disimpan. Auto-refresh tidak akan menimpa input Anda —
                  klik Simpan untuk menerapkan.
                </p>
              )}

              {loadState === 'unauthorized' && (
                <p className={styles.mutedText}>
                  Belum masuk — token tidak ada atau kedaluwarsa. Buka{' '}
                  <a href="/login">halaman Masuk</a> lalu muat ulang.
                </p>
              )}

              {loadState === 'unavailable' && (
                <p className={styles.mutedText}>
                  Pengaturan tidak tersedia — layanan Python tidak menjawab.
                </p>
              )}

              {loadState === 'ready' && payload && (
                <>
                  <div className={styles.formGrid}>
                    {payload.writable.map((knob) =>
                      knob.kind === 'bool' ? (
                        <label className={styles.field} key={knob.key}>
                          <span>
                            <input
                              type="checkbox"
                              checked={(draft[knob.key] ?? String(knob.value)) === '1'}
                              onChange={(e) => {
                                setDirty(true);
                                setDraft((d) => ({ ...d, [knob.key]: e.target.checked ? '1' : '0' }));
                              }}
                            />{' '}
                            {knob.key}
                          </span>
                          <small className={styles.fieldHint}>
                            {knob.description} Default {knob.default === 1 ? 'AKTIF' : 'NONAKTIF'} · dibaca oleh{' '}
                            <code>{knob.applied_to}</code>
                          </small>
                        </label>
                      ) : (
                        <KnobNumberField
                          key={knob.key}
                          knob={knob}
                          value={draft[knob.key] ?? String(knob.value)}
                          onChange={(next) => {
                            setDirty(true);
                            setDraft((d) => ({ ...d, [knob.key]: next }));
                          }}
                        />
                      )
                    )}
                  </div>
                  <div className={styles.formFooter}>
                    <span>Disimpan ke layanan Python dan langsung diterapkan tanpa restart.</span>
                    <button className={styles.primary} type="button" onClick={save} disabled={saving}>
                      {saving ? 'Menyimpan…' : 'Simpan pengaturan'}
                    </button>
                  </div>
                </>
              )}
            </section>
          )}

          {tab === 'Batas risiko' && (
            <section className={styles.formCard}>
              <div className={styles.formTitle}>
                <h2>Batas risiko (read-only)</h2>
                <p>
                  Sumber: nilai efektif <code>RiskGate</code> / <code>RiskEngine</code> (kode-level).
                  Nilai nyata yang sedang dipakai, sengaja tidak dapat diubah dari dashboard — ini
                  logika safety dan hanya berubah lewat kode.
                </p>
                {payload && 'source' in payload && typeof (payload as { source?: unknown }).source === 'string' && (
                  <p className={styles.mutedText}>source: {(payload as { source: string }).source}</p>
                )}
              </div>

              {loadState === 'unavailable' && (
                <p className={styles.mutedText}>Tidak tersedia — layanan Python tidak menjawab.</p>
              )}

              {loadState === 'ready' && payload && (
                <div className={styles.registry}>
                  {Object.entries(payload.risk_limits?.limits ?? {}).length === 0 ? (
                    <div>
                      <strong>Tidak ada data</strong>
                      <span>Risk gate belum terbentuk pada runtime.</span>
                    </div>
                  ) : (
                    Object.entries(payload.risk_limits.limits).map(([key, value]) => (
                      <Fragment key={key}>
                        <div>
                          <strong>{RISK_LABELS[key] ?? key}</strong>
                          <span>
                            <code>{key}</code>
                          </span>
                        </div>
                        <span className={`${styles.badge} ${styles.muted}`}>
                          {typeof value === 'number' ? value : '—'}
                        </span>
                      </Fragment>
                    ))
                  )}
                </div>
              )}
            </section>
          )}

          {tab === 'Model registry' && (
            <section className={styles.formCard}>
              <div className={styles.formTitle}>
                <h2>Model registry</h2>
                <p>Model yang dilayani gateway LLM. Daftar ini informatif — pemilihan model ada di gateway.</p>
              </div>
              <div className={styles.registry}>
                {modelsState.models.length === 0 ? (
                  <div>
                    <strong>
                      {modelsState.source === 'live'
                        ? 'Tidak ada model'
                        : modelsState.source === 'defaults'
                          ? 'Model bawaan'
                          : 'Gateway tidak terhubung'}
                    </strong>
                    <span>
                      {modelsState.source === 'live'
                        ? 'Registry kosong — tambahkan model di gateway.'
                        : modelsState.source === 'defaults'
                          ? 'Menampilkan daftar model bawaan; gateway belum mengembalikan daftar live.'
                          : 'Buka halaman Masuk lalu muat ulang.'}
                    </span>
                  </div>
                ) : (
                  <>
                    {visibleModels.map((m) => (
                      <Fragment key={m.id}>
                        <div>
                          <strong>{m.id}</strong>
                          <span>
                            {m.provider}
                            {m.is_free ? ' · gratis' : ' · premium'}
                          </span>
                        </div>
                        <span className={`${styles.badge} ${m.is_free ? styles.success : styles.muted}`}>
                          {m.is_free ? 'Gratis' : 'Berbayar'}
                        </span>
                      </Fragment>
                    ))}
                    <Pagination
                      page={safeModelPage}
                      pageSize={modelPageSize}
                      total={modelsState.models.length}
                      onPageChange={setModelPage}
                      onPageSizeChange={setModelPageSize}
                      unitLabel="models"
                    />
                  </>
                )}
              </div>
            </section>
          )}
        </div>
      </AppShell>
    </>
  );
}
