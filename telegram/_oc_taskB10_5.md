# TASK B-10 #5 — UI control-plane: hapus badge eligible/data-only, Arm hanya butuh running

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. BACA dulu: `docs/tasks/B-10-auto-detect-active-terminals.md` section "TASK 5".
Prasyarat: TASK 1–4 SUDAH selesai. API `:8787` sekarang mengirim `armable` (bukan `execution_allowed`).

Safety: DISARMED by default; DILARANG `git commit`/`git push`; DILARANG menyentuh `services/python/**` (backend sudah selesai — HANYA file UI ini); jangan start/stop/restart server (web :4321 mode DEV hot-reload, perubahan langsung terlihat).

## GOAL
Control-plane (`apps/web/app/control-plane/page.tsx`) masih memakai field mati `execution_allowed` (5 lokasi) + badge `eligible`/`data-only`. B-10: satu-satunya syarat Arm = terminal running; badge cukup `ARMED` + tombol Arm/Disarm.

## PERUBAHAN (WAJIB — semua di `apps/web/app/control-plane/page.tsx`)

1. **Type `TerminalEntry` (line ~1177):** `execution_allowed?: boolean;` → `armable?: boolean;` (biarkan urutan field lain apa adanya).

2. **Kolom badge/arm (line ~1470–1501):**
   - Hapus SELURUH blok ternary badge `eligible`/`data-only`:
     ```
     {t.execution_allowed ? (<span className={`${s.badge} ${s.warning}`}>eligible</span>) : (<span className={`${s.badge} ${s.muted}`}>data-only</span>)}{' '}
     ```
     → hapus saja (kolom "Status" line ~1379 SUDAH punya badge `RUNNING`/`STOPPED` dengan `${t.running ? s.success : s.muted}` — tidak perlu badge pengganti). Sisakan `{t.armed && <span className={`${s.badge} ${s.danger}`}>ARMED</span>}{' '}`.
   - Tombol Arm:
     - `disabled={busy || !hasToken || !t.running || !t.execution_allowed}` → `disabled={busy || !hasToken || !t.running}`
     - title ternary: hapus cabang `!t.execution_allowed ? 'Terminal tidak diizinkan eksekusi (execution: false di mt5_terminals.json)' :` — sisa: `!hasToken ? ... : !t.running ? 'Terminal tidak berjalan' : t.armed ? \`Matikan arm untuk terminal ${t.id}\` : \`Izinkan eksekusi order nyata untuk terminal ${t.id}\``
   - Update komentar B-9 di atas tombol: `Nonaktif bila execution:false / tidak jalan.` → `B-10: nonaktif hanya bila terminal tidak berjalan (execution flag diabaikan).`

3. **Danger zone (line ~1551):** `{selected?.execution_allowed && (` → `{selected?.running && (`

4. Grep memastikan: `grep -n "execution_allowed" apps/web/app/control-plane/page.tsx` → **0**. Juga `grep -rn "eligible\|data-only" apps/web/app/control-plane/page.tsx` → 0 (badge lama hilang; kata lain yang mengandung "eligible" tidak boleh tersisa di file ini).

5. JANGAN ubah: fetch/`post`/`putConfig`/pagination/filter stopped/probe/select/editor lot-risk/fanout toggle/danger zone logic lainnya.

## VERIFIKASI (STOP GATE)
1. ESLint bersih:
```
cd apps/web && npx eslint app/control-plane/page.tsx
```
→ exit 0 (0 error; warning pra-eksisting boleh bila ada — laporkan).
2. TypeScript build check (lebih kuat dari eslint):
```
cd apps/web && npx tsc --noEmit -p tsconfig.json 2>&1 | tail -20
```
→ tidak ada error BARU yang menyebut `page.tsx` control-plane (bila ada error pra-eksisting file lain, laporkan dan buktikan dengan `git stash` BILA perlu — atau cukup bandingkan error sebelum/sesudah).
3. Runtime render (web DEV :4321 hot-reload — tunggu ~5 detik setelah edit):
```
curl -s http://localhost:4321/control-plane | grep -c "Arm" 
curl -s http://localhost:4321/control-plane | grep -c "eligible\|data-only" || true
```
→ "Arm" ≥ 1; "eligible|data-only" = 0. CATATAN: halaman Next.js mungkin merender konten via JS — bila grep 0 untuk keduanya, verifikasi via bundle: `curl -s "http://localhost:4321/_next/static/chunks/app/control-plane/page.js" 2>/dev/null | grep -c "armable"` atau cek log dev server. Laporkan hasil apa adanya.
4. Grep sumber: `grep -rn "execution_allowed" apps/web --include="*.tsx" --include="*.ts"` → 0 (abaikan `.next/` build cache).

## COMPLETION REPORT (Indonesia, format sama sebelumnya)
```
TASK: B-10 #5 / STATUS: PASS atau BLOCKED
FILES CHANGED / ROOT CAUSE / FIX / TESTS (lint+tsc+curl) / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
```
Jika ada acceptance gagal → BLOCKED dan STOP.
