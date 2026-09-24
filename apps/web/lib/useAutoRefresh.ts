'use client';

import { useEffect, useRef } from 'react';

/**
 * useAutoRefresh — panggil `fn` sekali saat mount, lalu ulangi tiap `intervalMs`
 * sehingga data di halaman berganti otomatis tanpa refresh manual.
 *
 * Semantik sama dengan `useEffect(() => { fn(); }, [fn])` — bila identitas `fn`
 * berubah (mis. ganti symbol/timeframe), langsung fetch ulang dan interval
 * di-restart — TETAPI tanpa jeda, tick otomatis tetap berjalan.
 *
 * - Jeda saat tab tersembunyi (document.hidden) → hemat request di background.
 * - Tab kembali fokus → langsung refresh (data tidak basi).
 * - Cleanup aman: interval dibuang saat unmount / saat `fn` berubah identitas.
 *
 * Interval default 10 dtk — seirama polling observability, di bawah cadence
 * feed MARKET_FEED_INTERVAL_S (15 dtk) dan ringan untuk API lokal.
 *
 * Pola pemakaian (menggantikan `useEffect(() => { load(); }, [load])`):
 *   const load = useCallback(async () => { ... }, [deps]);
 *   useAutoRefresh(load);
 */
export function useAutoRefresh(fn: () => void | Promise<void>, intervalMs = 10_000): void {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;

    const run = () => {
      if (!cancelled) void fnRef.current();
    };
    const start = () => {
      if (cancelled || timer !== null) return;
      timer = setInterval(run, intervalMs);
    };
    const stop = () => {
      if (timer === null) return;
      clearInterval(timer);
      timer = null;
    };

    // Fetch pertama saat mount (tetap walau tab sedang hidden — user baru buka).
    run();
    if (!document.hidden) start();

    const onVisibility = () => {
      if (cancelled) return;
      if (document.hidden) {
        stop();
      } else {
        run(); // tab aktif kembali → data langsung segar
        start();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisibility);
      stop();
    };
  }, [fn, intervalMs]);
}
