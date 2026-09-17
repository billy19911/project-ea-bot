'use client';

// Halaman Masuk (UI/UX ide #3).
//
// Menggantikan alur lama: jalankan token.bat → buka DevTools → tempel
// localStorage.setItem(...). Di sini token diverifikasi dulu ke endpoint
// terproteksi (/mt5/terminals) sebelum disimpan — token yang salah tidak
// pernah masuk localStorage. Backend auth tidak diubah sama sekali.
//
// Dua jalur masuk:
//   1. Tempel token yang sudah ada (mis. dari token.bat).
//   2. Mint token dev sekali klik lewat POST /auth/token (endpoint publik
//      khusus development, sama yang dipakai token.bat).

import { useRouter } from 'next/navigation';
import { FormEvent, useEffect, useState } from 'react';
import { API_BASE, getAuthToken } from '../../lib/api';
import styles from './login.module.css';

export default function LoginPage() {
  const router = useRouter();
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [alreadyIn, setAlreadyIn] = useState(false);

  useEffect(() => {
    setAlreadyIn(Boolean(getAuthToken()));
  }, []);

  // Verifikasi sebelum simpan: kalau 401, token tidak ditulis ke localStorage.
  const verifyAndStore = async (candidate: string) => {
    let res: Response;
    try {
      res = await fetch(API_BASE + '/mt5/terminals', {
        headers: { Authorization: `Bearer ${candidate}` },
      });
    } catch {
      throw new Error(`Tidak dapat menghubungi API (${API_BASE}).`);
    }
    if (res.status === 401) throw new Error('Token ditolak (401). Periksa kembali token Anda.');
    if (!res.ok) throw new Error(`Verifikasi gagal (HTTP ${res.status}).`);
    localStorage.setItem('ea-bot-token', candidate);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = token.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await verifyAndStore(trimmed);
      router.replace('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Terjadi kesalahan.');
    } finally {
      setBusy(false);
    }
  };

  const mint = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      let res: Response;
      try {
        res = await fetch(API_BASE + '/auth/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId: 'operator', role: 'admin' }),
        });
      } catch {
        throw new Error(`Tidak dapat menghubungi API (${API_BASE}).`);
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data?.token) {
        throw new Error(
          data?.message || `Gagal membuat token (HTTP ${res.status}). Coba lagi beberapa saat.`,
        );
      }
      await verifyAndStore(data.token);
      router.replace('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Terjadi kesalahan.');
    } finally {
      setBusy(false);
    }
  };

  const logout = () => {
    localStorage.removeItem('ea-bot-token');
    setAlreadyIn(false);
    setToken('');
    setError(null);
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>EA</span>
          <div>
            <strong>EA BOT</strong>
            <small>TRADING CONTROL</small>
          </div>
        </div>

        {alreadyIn ? (
          <>
            <h1 className={styles.title}>Sudah masuk</h1>
            <p className={styles.sub}>
              Sesi token aktif di browser ini. Lanjutkan ke dashboard, atau keluar untuk memakai
              token lain.
            </p>
            <div className={styles.row}>
              <button className={styles.primary} onClick={() => router.replace('/')}>
                Lanjut ke dashboard
              </button>
              <button className={styles.secondary} onClick={logout} disabled={busy}>
                Keluar
              </button>
            </div>
          </>
        ) : (
          <>
            <h1 className={styles.title}>Masuk</h1>
            <p className={styles.sub}>
              Dashboard memakai Bearer token. Tempel token yang sudah ada, atau buat token dev
              sekali klik.
            </p>

            <form onSubmit={submit} className={styles.form}>
              <label className={styles.label} htmlFor="token">
                Token
              </label>
              <input
                id="token"
                className={styles.input}
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Tempel token di sini"
                autoComplete="off"
                spellCheck={false}
              />
              <button className={styles.primary} type="submit" disabled={busy || !token.trim()}>
                {busy ? 'Memeriksa…' : 'Masuk'}
              </button>
            </form>

            <div className={styles.divider}>
              <span>atau</span>
            </div>

            <button className={styles.secondary} onClick={mint} disabled={busy}>
              {busy ? 'Memproses…' : 'Buat token dev (sekali klik)'}
            </button>

            <p className={styles.hint}>
              Tombol di atas memanggil <code>POST /auth/token</code> — sama seperti{' '}
              <code>token.bat</code>. Token diverifikasi sebelum disimpan; yang salah tidak
              pernah tersimpan.
            </p>
          </>
        )}

        {error && <div className={styles.error}>{error}</div>}
      </div>
    </div>
  );
}
