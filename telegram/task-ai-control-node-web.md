# Task C2 — AI Control (sisi Node + Web): wiring supervisor nyata, label error, tombol "Minta analisis", timeout chart

## Tujuan
UI AI Control + Penasihat LLM berhenti menampilkan "—"/kosong karena wiring salah:
1. `/ai-control/status.supervisor` mengambil `token_budget`/`token_used`/`max_concurrency` dari sumber NYATA (endpoint Python `/supervisor/status` dari Task C1).
2. Label "Error agent" tidak kosong (map field `source` → `agent`).
3. Tombol "Minta analisis" mengirim harga NYATA (dari tick MT5), bukan field yang tidak ada.
4. Timeout proxy chart dinaikkan agar pagination lambat (BTCUSD D1 ~5 dtk) tidak jadi 503.

## Akar masalah (SUDAH diverifikasi — jangan diragukan)
1. `apps/api/src/supervisorStatus.js` `buildSupervisorStatus` (~line 82-98): `token_budget: null, token_used: null` HARDCODED dengan komentar "No runtime source exists" — komentar itu SALAH. Bukti: `runtime.pipeline.supervisor` nyata punya `max_concurrency=3, token_budget=8000, token_used=0` (probe langsung). Endpoint `/supervisor/status` disediakan Task C1 (pastikan sudah ada; kalau belum, LAPORKAN dan berhenti — jangan mengarang).
   Catatan: `max_concurrency` saat ini dibaca dari `scheduler.stats.max_concurrency` yang TIDAK punya field itu → selalu null.
2. `apps/api/src/index.ts` `/ai-control/status` (~line 430-470): `errors: getRecentErrors(10)` mengembalikan `ErrorRecord` dengan field `source` (`apps/api/src/metrics.ts:96`), tapi UI `apps/web/app/ai-control/page.tsx` membaca `err.agent` (~line 34-40, 352) → label kosong.
3. `apps/web/app/ai-control/page.tsx` (~line 234-241): tombol "Minta analisis" fetch `/market/overview` lalu mengisi `bid: row.bid, ask: row.ask, trend: row.trend` — padahal row `/market/overview` hanya `{symbol, price, spread}` (lihat `apps/api/src/overviewMapping.js`) → semua `undefined` → advisor menolak "Tidak ada data pasar nyata". Harga tick NYATA tersedia di `GET /mt5/market/tick?symbol=X` → `{data: {symbol, bid, ask, last, volume, time}, source}` (probe live terbukti).
4. `apps/api/src/pythonClient.ts:23` `DEFAULT_TIMEOUT_MS = 5000`; route `/chart/candles` di `index.ts` memanggil `sendProxy(...)` tanpa timeout override → pagination BTCUSD D1 (5004 ms) melewati batas → `503 python_service_unavailable` (ditemukan di node.log).

## Perubahan yang diminta (HANYA apps/api + apps/web/app/ai-control)

### 1. `apps/api/src/supervisorStatus.js` — `buildSupervisorStatus`
- Terima input ke-4: `supervisor` (objek dari `/supervisor/status` Task C1, boleh undefined).
- `max_concurrency`: pakai `supervisor.max_concurrency` bila finite; FALLBACK ke `scheduler.stats.max_concurrency` (perilaku lama dipertahankan); else `null`.
- `token_budget`/`token_used`: pakai `supervisor.token_budget`/`supervisor.token_used` bila finite; else `null` (jangan 0).
- Update komentar header JSDoc (buang klaim "No runtime source exists").
- JANGAN ubah `buildUsageRows` / `mapModels`.

### 2. `apps/api/src/index.ts` — dua titik
- `/ai-control/status` (~line 430-447): tambah `getJson<any>('/supervisor/status')` ke `Promise.all` (6 hasil), masukkan ke `relevant`/`degraded` sebagai `'supervisor'`, dan teruskan `supervisor: supervisorResult.ok ? supervisorResult.data.supervisor : undefined` ke `buildSupervisorStatus`.
- `errors` (~line 467): map ke bentuk UI: `errors: getRecentErrors(10).map((e) => ({ id: e.id, timestamp: e.timestamp, agent: e.source, message: e.message, severity: e.severity }))`.
- Route `/chart/candles` dan `/chart/analysis`: tambah konstanta `const CHART_PROXY_TIMEOUT_MS = 15000;` (dekat `sendProxy`) dan panggil `sendProxy(res, path, undefined, req, CHART_PROXY_TIMEOUT_MS)`.

### 3. `apps/web/app/ai-control/page.tsx` — tombol "Minta analisis"
- Ganti blok `/market/overview` (~234-241) dengan `GET /mt5/market/tick?symbol=<SYMBOL>`:
  - `const d = data?.data` → bila `typeof d.bid === 'number' && typeof d.ask === 'number'` → `market = { symbol, bid: d.bid, ask: d.ask, timeframe: 'H1' }`.
  - JANGAN kirim `trend`/`spread_pips` palsu. `symbol` selalu dikirim.
- Update tipe `AgentError.severity` (~34-40) agar mencakup `'critical'`, dan badge logic (~204-209): `err.severity === 'high' || err.severity === 'critical' ? danger : ...`.
- JANGAN menyentuh bagian lain halaman.

## Tests (TDD)
1. `apps/api/test/supervisor-status.test.cjs` — UPDATE test "token_budget and token_used are always null..." (ganti nama + isi):
   - Null tetap bila `supervisor` absen: `buildSupervisorStatus({...})` → `token_budget === null`, `token_used === null`.
   - Nilai NYATA bila diberi: `buildSupervisorStatus({ supervisor: { max_concurrency: 3, token_budget: 8000, token_used: 3800 } })` → `8000/3800/3`.
   - Fallback lama tetap: `buildSupervisorStatus({ scheduler: { stats: { max_concurrency: 3 } } }).max_concurrency === 3`.
   - Nilai non-finite (`'x'`, NaN) → null.
2. Jalankan SELURUH suite Node: `cd apps/api && npm test` (build dist + semua test — test membaca `../dist/`).
3. `npx tsc --noEmit` di root DAN `cd apps/web && npx tsc --noEmit` — keduanya 0 error.

## Verifikasi (WAJIB jalankan, laporkan output ASLI — bukan simulasi)
```bash
cd apps/api && npm test
cd ../.. && npx tsc --noEmit
cd apps/web && npx tsc --noEmit
```

## Batasan keras
- JANGAN menyentuh `services/python/**`, `apps/web/app/market/**`, `apps/web/components/**`, `apps/web/lib/**` (task lain memegang file itu), atau file web lain selain `apps/web/app/ai-control/page.tsx`.
- JANGAN reformat massal; hanya baris/fungsi yang diubah.
- JANGAN commit/push.
- JANGAN menjalankan `restart-py.ps1`, `restart-all.ps1`, `run_ops_drills.py`, restart dev server, atau perintah apa pun yang menunggu service hidup.
- JANGAN memakai `&` di perintah terminal.
- JANGAN menambah dependency baru.

## Output yang diharapkan
1. Diff final file yang diubah.
2. Log verifikasi asli (npm test, 2× tsc).
3. Ringkasan 3-6 baris: apa yang diubah dan kenapa UI terisi.
