# Task B — Chart market "kedip-kedip": hilangkan flicker viewport & flash harga (FRONTEND)

## Tujuan
Halaman `/market` berhenti berkedip: SVG chart tidak re-render penuh tiap tick WebSocket (2,5 dtk), viewport + hover TIDAK reset saat auto-refresh (10 dtk), dan flash angka harga hanya muncul saat perubahan bermakna (bukan setiap delta kecil). Tidak ada perubahan backend.

## Akar masalah (SUDAH diverifikasi dari sumber asli — baca file, jangan asumsikan)
1. `apps/web/components/PriceChart.tsx` — komponen `export default function PriceChart` (~line 134) TIDAK dibungkus `React.memo`. Setiap re-render parent = render ulang seluruh SVG.
2. `apps/web/app/market/page.tsx` — `chartLevels` dibangun ulang setiap render (~line 243–259, BUKAN `useMemo`) dan diteruskan sebagai prop `levels` ke `<PriceChart>` (~line 384) → referensi array baru tiap render (memo pun akan tetap bocor bila ini tidak dibungkus `useMemo`).
3. `apps/web/components/PriceChart.tsx` — `useMemo` geometri (~line 299) memakai dep `visibleBars` yang dibuat ulang tiap render → memo internal invalid tiap render.
4. Tick WS 2,5 dtk: `apps/api/src/liveStream.ts` (`interval_ms: 2500`) → `useLiveQuotes` update state → halaman re-render → rantai (1)-(3) → seluruh SVG re-render + teks harga flash.
5. Auto-refresh 10 dtk: `apps/web/lib/useAutoRefresh.ts` (default `intervalMs = 10_000`, ~line 24; call-site `useAutoRefresh(load)` di `market/page.tsx` ~line 157) → efek viewport di `PriceChart.tsx` (~line 171–189) me-reset `setVisibleCount`/`setViewEnd`/`setHover(null)` saat `newestTime` berubah → viewport lompat + hover hilang.
6. Flash 900 ms: `LiveNumber` di `market/page.tsx` (~line 71–83) membandingkan `prev.current !== value` — delta sekecil apa pun memicu flash. Plus `livePulse` 1,6 dtk infinite di `apps/web/app/globals.css` (~line 539–568).

## Perubahan yang diminta (HANYA frontend)
### 1. `apps/web/components/PriceChart.tsx`
- Bungkus export dengan `React.memo` (mis. `export default memo(PriceChart)`), tanpa mengubah perilaku lain.
- Perbaiki deps `useMemo` geometri: JANGAN pakai array yang dibuat ulang tiap render sebagai dep (mis. `visibleBars`); gunakan nilai stabil (mis. `bars`, `visibleCount`, `viewEnd`, `newestTime` — pilih yang benar setelah membaca kode) atau bungkus `visibleBars` dengan `useMemo` internal dengan deps tepat.
- Efek viewport (~171–189): JANGAN reset `visibleCount`/`viewEnd`/`hover` saat hanya data baru datang (`newestTime` berubah karena refresh/tick). Reset HANYA saat identitas data berubah (mis. `symbol`/`timeframe` berganti). Saat bar baru di-append dan user sedang di ujung kanan ("follow latest"), geser viewport agar tetap di ujung; bila user sedang menelusuri historis, pertahankan posisinya.
- Bila butuh logika murni untuk viewport-on-append, taruh sebagai fungsi yang bisa diuji (mis. `apps/web/lib/viewport.ts`) dan TDD dengan `node --test`.

### 2. `apps/web/app/market/page.tsx`
- `chartLevels`: bungkus `useMemo` dengan deps tepat (mis. positions/symbol) sehingga referensi stabil antar tick.
- `LiveNumber`: flash hanya bila perubahan relatif >= ambang (mis. `shouldFlash(prev, next, 0.0005)`); ekstrak helper ke `apps/web/lib/liveFlash.ts` dan pakai. Pola harness TS-strip Node SUDAH TERBUKTI di repo: `_tf/liveFlash.ts` + `_tf/liveFlash.test.mjs` → 4/4 PASS dengan `node --test "_tf/liveFlash.test.mjs"`.

### 3. `apps/web/app/globals.css`
- `livePulse` 1,6 dtk infinite: hilangkan animasi infinite (pulsa satu kali atau tanpa animasi). Jangan ubah kelas/style lain.

## Tests (TDD — tulis test GAGAL dulu untuk logika murni, lalu implementasi)
Tidak ada infra unit test frontend standar di repo (tidak ada `apps/web/test`, `vitest.config.*`, `jest.config.*`). Jalur yang TERBUKTI: Node v26.7.0 mengimpor file `.ts` langsung dari test `.mjs`.
- Buat test logika murni: `apps/web/lib/liveFlash.test.mjs` (untuk `shouldFlash`) dan/atau `apps/web/lib/viewport.test.mjs` (untuk viewport-on-append).
- Jalankan dengan file EKSPLISIT: `node --test "apps/web/lib/liveFlash.test.mjs"` — JANGAN direktori (`node --test <dir>/` gagal di Node v26.7.0, terbukti).
- Contoh assertion TDD: `shouldFlash(100, 100.0001) === false`, `shouldFlash(100, 101) === true`; viewport: append bar saat user di historis → posisi tidak reset; saat di ujung kanan → ikut geser.
- `cd apps/web && npx tsc --noEmit` WAJIB 0 error (baseline hijau).

## Verifikasi (WAJIB jalankan, laporkan output ASLI — bukan simulasi)
```bash
node --test "apps/web/lib/liveFlash.test.mjs"
node --test "apps/web/lib/viewport.test.mjs"
cd apps/web
npx tsc --noEmit
```

## Batasan keras
- Perubahan HANYA di `apps/web/**` (+ file test `.mjs` baru di `apps/web/lib/`).
- JANGAN menyentuh `services/python/**` dan `apps/api/**`.
- JANGAN reformat massal; hanya baris/fungsi yang diubah (prettier boleh memformat file yang diubah saja bila perlu).
- JANGAN commit/push.
- JANGAN menjalankan `restart-py.ps1`, `restart-all.ps1`, `run_ops_drills.py`, atau perintah apa pun yang menunggu service hidup; JANGAN restart dev server web.
- JANGAN memakai `&` di perintah terminal.
- JANGAN menambah dependency baru.

## Output yang diharapkan
1. Diff final file yang diubah.
2. Log asli `node --test` + `npx tsc --noEmit`.
3. Ringkasan 3–6 baris: apa yang diubah dan kenapa flicker hilang.
