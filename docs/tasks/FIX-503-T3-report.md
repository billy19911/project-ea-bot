# FIX-503 T3 — Laporan: Proxy route `GET /research/strategies` (perbaiki 404)

Status: **GREEN** (RED terbukti lebih dulu).
Tanggal: 2026-09-26
Scope: `apps/api` saja (Node/TypeScript). Tidak menyentuh `apps/web`, Python, `package.json`.
Tanpa dependency baru. Tanpa `git add`/`git commit`. Tidak start/stop service (unit test mandiri).

## Ringkasan

Halaman Backtest (`apps/web/app/backtest/page.tsx:129`) memuat daftar tipe strategi dari
`GET /ea-api/research/strategies` (`/ea-api` di-rewrite Next ke Node API). Python sudah
menyediakan route ini (`services/python/src/research/endpoints.py:239` -> 200), tetapi Node
API tidak punya route yang cocok -> jatuh ke 404 handler (4x di console). Route research lain
(`/research/overview`, `/research/experiments`, `/research/ranking`) sudah diproxy.

Perbaikan: tambah route `GET /research/strategies` yang memakai helper `sendProxy` yang sudah
ada (pola identik dengan route research lain), meneruskan query string apa adanya. `/risk`
**tidak** ditambahkan (tidak ada caller di web).

## Diff ringkas

Satu blok baru (~8 baris) di `apps/api/src/index.ts`, tepat setelah `/research/overview`
(baris 1025-1031), tanpa reformat/reorder baris lain:

```ts
app.get('/research/strategies', async (req, res) => {
  // FIX-503: Backtest page loads supported strategy types from here; the
  // Python service already serves it (200). Forward any query string verbatim.
  const qs = new URLSearchParams(req.query as Record<string, string>).toString();
  const path = qs ? `/research/strategies?${qs}` : '/research/strategies';
  await sendProxy(res, path, undefined, req);
});
```

File test baru: `apps/api/test/research-strategies-route.test.cjs` (2 test).
`git diff` `apps/api/src/index.ts` juga memuat hunk milik pekerjaan user lain
(import `./loadEnv`, `PORT` 3789, `POST /strategies`, `GET /research/data-info`) — itu
**bukan** perubahan saya dan dibiarkan utuh (tidak disentuh).

## RED -> GREEN

Test baru: `apps/api/test/research-strategies-route.test.cjs`

Pola mengikuti test yang sudah ada (`load-env.test.cjs`): menjalankan `dist/index.js` hasil
build di proses Node terpisah, `PYTHON_SERVICE_URL` diarahkan ke stub HTTP Python in-process,
lalu `GET /research/strategies` lewat HTTP nyata. Karena semua route non-publik dijaga
middleware auth global, test minta dev token via `POST /auth/token` (`DEV_AUTH_ENABLED=true`).

- **RED** (sebelum implementasi): `npm test` -> **53 pass, 2 fail**.
  `assert.notEqual(status, 404)` gagal (`actual: 404`) — membuktikan route memang belum
  terdaftar. Test kedua juga `404 !== 200`.
- **GREEN** (sesudah implementasi): `npm test` -> **55 pass, 0 fail**.

Test yang ditambahkan:
- `GET /research/strategies proxies to the Python service (not 404)` — status bukan 404,
  `200`, `source: 'live'`, payload stub (`strategies[0].id === 'ema_crossover'`) diteruskan,
  dan stub Python menerima request ke `/research/strategies`.
- `GET /research/strategies passes the query string through` — `?symbol=EURUSD&timeframe=M15`
  sampai utuh ke Python.

## Hasil verifikasi

1. `cd apps/api && npm test` (menjalankan `npm run build && node --test`):

        ℹ tests 55
        ℹ pass 55
        ℹ fail 0
        (baseline 53 + 2 test T3 baru; TIDAK ada regresi)

2. `npx tsc --noEmit` -> exit 0 (tanpa error).

3. `npm run lint` (`eslint src/`) -> exit 0, **0 error**, 6 warning.

   Keenam warning **PRE-EXISTING** dan tidak berada di baris yang saya tambah:
   `src/index.ts` (`AuthRequest`, `redactSecrets` unused), `src/logger.ts`
   (`pretty` unused), `src/metrics.ts` (`metricsText` unused),
   `src/middleware/websocket.ts` (`wsRateLimitCheck`, `data` unused).
   Lint hanya mencakup `src/`, jadi file test baru tidak masuk cakupan.

## Catatan implementasi

- Query string diteruskan **verbatim** (`new URLSearchParams(req.query)`), bukan allowlist,
  karena Python `GET /research/strategies` tidak mendefinisikan parameter wajib — sesuai
  instruksi "Query string pass-through". Ini satu-satunya penyimpangan kecil dari bentuk
  literal route research lain (yang sebagian memakai allowlist `symbol/timeframe`), namun
  helper proxy (`sendProxy`) dan pola respons (`source: 'live'`) tetap sama.
- API server dijalankan **di dalam test** sebagai child process dengan stub Python sebagai
  upstream — bukan service aplikasi nyata. Tidak ada service yang di-start/stop.

## Sisa risiko

- Test spawn proses Node (`dist/index.js`) + stub HTTP; port diambil ephemeral dan proses
  dibunuh di `finally`, jadi tidak bentrok dengan instance dev yang sedang berjalan.
- Route ikut dijaga auth global (seperti route research lain) — sesuai perilaku `sendProxy`
  yang ada; web sudah mengirim kredensial via `apiFetch`.
