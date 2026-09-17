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
import AppShell from '../../components/AppShell';

type SourceState = 'live' | 'unavailable';

type AiModel = { id: string; provider: string; context: number; is_free: boolean; capabilities?: string[] };
type ModelsState = { models: AiModel[]; source: SourceState };

type Knob = {
  key: string;
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

export default function SettingsPage() {
  const [tab, setTab] = useState('Runtime');
  const [notice, setNotice] = useState<Notice>(null);
  const [modelsState, setModelsState] = useState<ModelsState>({ models: [], source: 'unavailable' });
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'unauthorized' | 'unavailable'>('loading');
  const [saving, setSaving] = useState(false);

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
      setDraft(
        Object.fromEntries((data.writable ?? []).map((k) => [k.key, String(k.value)])),
      );
      setLoadState('ready');
    } catch {
      setLoadState('unavailable');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
        setModelsState({
          models: Array.isArray(data.models) ? data.models : [],
          source: data.source === 'live' ? 'live' : 'unavailable',
        });
      } catch {
        if (!cancelled) setModelsState({ models: [], source: 'unavailable' });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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
      await load();
    } catch {
      setNotice({ kind: 'error', text: 'Gagal menyimpan — kesalahan jaringan.' });
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
      <AppShell activeKey="settings" eyebrow="EA BOT / PENGATURAN" title="Pengaturan">
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
                    {payload.writable.map((knob) => (
                      <label className={styles.field} key={knob.key}>
                        <span>{knob.key}</span>
                        <input
                          type="number"
                          min={knob.minimum}
                          max={knob.maximum}
                          step={knob.key.includes('interval') ? '0.1' : '1'}
                          value={draft[knob.key] ?? String(knob.value)}
                          onChange={(e) => setDraft((d) => ({ ...d, [knob.key]: e.target.value }))}
                        />
                        <small className={styles.fieldHint}>
                          {knob.description} Rentang {knob.minimum}–{knob.maximum} · dipakai oleh{' '}
                          <code>{knob.applied_to}</code>
                        </small>
                      </label>
                    ))}
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
                  Nilai nyata yang sedang dipakai <code>RiskEngine</code> / <code>RiskGate</code>. Sengaja tidak
                  dapat diubah dari dashboard: ini logika safety dan hanya berubah lewat kode.
                </p>
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
                    <strong>{modelsState.source === 'live' ? 'Tidak ada model' : 'Gateway tidak terhubung'}</strong>
                    <span>
                      {modelsState.source === 'live'
                        ? 'Registry kosong — tambahkan model di gateway.'
                        : 'Buka halaman Masuk lalu muat ulang.'}
                    </span>
                  </div>
                ) : (
                  modelsState.models.map((m) => (
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
                  ))
                )}
              </div>
            </section>
          )}
        </div>
      </AppShell>
    </>
  );
}
