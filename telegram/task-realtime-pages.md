# Task: 3 halaman web realtime (positions, orders, risk)

Repo: C:/xampp/htdocs/project-ea-bot (monorepo: apps/web Next.js :3000, apps/api Node :3789,
services/python FastAPI :8000). Semua service sudah berjalan — edit file saja, JANGAN restart service.

## Goal

Data di 3 halaman ini harus berganti otomatis tiap 10 detik (polling), tanpa user refresh browser,
dan tanpa flicker (jangan pernah `setLoading(true)` di cycle polling berikutnya — hanya flag
`loaded` initial).

## Pola WAJIB (tiru persis)

Baca `apps/web/app/trade-history/page.tsx` sebagai referensi:
- `const load = useCallback(async () => {...}, []); useAutoRefresh(load);`
- hook ada di `apps/web/lib/useAutoRefresh.ts` (sudah final, JANGAN diubah, jangan tambah library).
- fetch via `apiFetch` dari `apps/lib/api.ts` → `apps/web/lib/api.ts` (sudah handle Bearer token +
  X-Trace-Id). Path relatif: `apiFetch('/positions')`.
- error state: tampilkan inline merah, JANGAN pernah blocking overlay.
- hanya render `Loading…` saat `!loaded` (initial), bukan tiap poll.

## 1. Node API: tambah route GET /orders

File `apps/api/src/index.ts` — BELUM ada route `/orders`. Tiru pola `/positions` yang ada di
sekitar baris 832:

```ts
app.get('/positions', async (req, res) => {
  const log = (req as any).log;
  log.info('positions.list');
  await sendProxy(res, '/mt5/positions', undefined, req);
});
```

Tambahkan (letakkan dekat `/positions`):

```ts
app.get('/orders', async (req, res) => {
  const log = (req as any).log;
  log.info('orders.list');
  await sendProxy(res, '/mt5/orders', undefined, req);
});
```

Python endpoint `GET /mt5/orders` sudah ada (`services/python/src/mt5/endpoints.py` baris ~48/59),
verified response: `{"orders":[],"count":0}`. `sendProxy` (baris 168) menambahkan `source:'live'`.

## 2. apps/web/app/positions/page.tsx — ganti dummy dengan data asli

Sekarang pakai array dummy hardcode. Ganti dengan:
- `apiFetch('/positions')` → response `{ positions: Position[], count, source }`.
- Schema Position di `services/python/src/mt5/schemas.py` `class Position` — FIELD PASTI:
  `ticket:int, symbol:str, side:str (BUY/SELL), quantity:float, price_open:float,
  price_current:float, swap:float, profit:float, unrealized_pnl:float, margin:float,
  sl:float|null, tp:float|null, entry:str, status:str, time:datetime, time_update:datetime`.
- Columns: Ticket, Time, Symbol, Side, Qty, Open, Current, PnL, SL, TP, Status
  (format datetime ke locale string).
- `unitLabel="positions"` di DataTable, empty state: tabel kosong + label 0 positions itu sudah
  cukup (DataTable handle), jangan tampilkan dummy palsu lagi.
- Tetap bungkus `Card title="Open Positions"` boleh dipertahankan.
- AppShell `activeKey="positions"` pertahankan.

## 3. apps/web/app/orders/page.tsx — ganti dummy dengan data asli

- `apiFetch('/orders')` → `{ orders: Order[], count, source }`.
- Schema Order di `services/python/src/mt5/schemas.py` `class Order` — FIELD PASTI:
  `ticket:int, symbol:str, side:str, order_type:str, price:float, stop_price:float|null,
  quantity:float, filled_qty:float, status:str, time_setup:datetime, time_expiration:datetime|null`.
- Columns: Ticket, Time setup, Symbol, Side, Type, Price, Qty, Filled, Status.
- Pola sama: useCallback + useAutoRefresh, error inline, loaded flag.
- AppShell `activeKey="orders"` pertahankan.

## 4. apps/web/app/risk/page.tsx — dua endpoint realtime

Sekarang statis `RiskBadge level="UNKNOWN"` hardcode. Ganti jadi polling dua endpoint:

a) Circuit breaker: `apiFetch('/v2/circuit-breaker')`.
   Node route sudah ada (`apps/api/src/index.ts` baris ~630, proxy via sendProxy).
   Response envelope Python (`services/python/src/system/v2_endpoints.py` baris ~220):
   `{ value: <MultiLevelBreaker.to_dict()>, source, status }` — `to_dict` PASTI:
   `{ level, latched, trigger, reason, ... }` (baca `MultiLevelBreaker.to_dict` di
   `services/python/src/risk/multi_level_breaker.py` baris ~279 untuk key tambahan seperti
   `since`/`history`). Handle defensif: `const v = data?.value ?? data;`.
   Level enum PASTI (`class BreakerLevel`, file sama baris ~36): `normal`, `caution`,
   `risk_reduced`, `entry_blocked`, `emergency_flatten`, `halted`.

b) Reconciliation: `apiFetch('/reconciliation/status')`.
   Node route sudah ada (`index.ts` baris ~344).
   Response PASTI (`services/python/src/orchestration/endpoints.py` baris ~102):
   `{ last_report: ReconciliationReport.to_dict() | null, history_count, source }`.
   `to_dict` PASTI (`services/python/src/execution/reconciliation.py` baris ~101):
   `matched:int[], missing_in_broker:int[], missing_internal:int[], volume_mismatches[],
   sltp_mismatches[], symbol_mismatches[], magic_mismatches[], matched_orders:int[],
   orphan_orders:int[], total_mismatches:int, critical:bool`.

Mapping ke RiskBadge (`apps/web/components/ui/risk-badge.tsx`, level valid PASTI:
`'OK' | 'WARN' | 'BLOCK' | 'UNKNOWN'`):
- Circuit breaker: `normal` → OK; `caution`/`risk_reduced` → WARN; `entry_blocked`,
  `emergency_flatten`, `halted` → BLOCK; level tak dikenal / fetch gagal → UNKNOWN.
- Reconciliation: `last_report === null` → UNKNOWN (belum pernah jalan, jangan mengarang);
  `critical === true` → BLOCK; `total_mismatches > 0` → WARN; selain itu → OK.

Tampilkan detail teks (bukan cuma badge):
- Section Circuit Breaker: badge + `level` name + `reason` + flag `latched` /
  `trigger` bila ada.
- Section Reconciliation: badge + `matched.length` + `total_mismatches` + `critical` +
  `orphan_orders.length` + `history_count`.
- Badge di header AppShell `actions=` = level circuit breaker terkini.
- Kedua fetch dalam SATU `load` (Promise.all, tangani masing-masing gagal terpisah — satu endpoint
  error tidak boleh menghapus data endpoint lain).
- `useAutoRefresh(load)` 10 dtk. Pertahankan layout grid section yang ada, ganti isi statisnya.

## Larangan

- Tanpa dependency baru (React hook biasa saja).
- Jangan ubah file lain di luar 4 file di atas (1 halaman Node + 3 page).
- Jangan sentuh `gate.py`, `engine.py`, `useAutoRefresh.ts`, `lib/api.ts`.
- Jangan hapus/ubah trade history atau risk policy backend.
- 15 page placeholder "Page under construction" (agents, audit, backtest, dst) → SKIP, jangan disentuh.
- Jangan restart service apapun.

## Verifikasi setelah edit

1. `cd apps/api && npx tsc --noEmit` → harus 0 error.
2. `cd apps/web && npm run build` → Next.js build harus lulus.
3. Lapor file apa saja yang diubah + ringkasan perubahan per file.
