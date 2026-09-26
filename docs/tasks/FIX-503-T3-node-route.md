# T3 — FIX-503: Node API proxy route GET /research/strategies (perbaiki 404)

Repo: C:/xampp/htdocs/project-ea-bot (Windows; shell Git Bash).
Konteks: docs/plans/FIX-503-404-LATENCY.md (bagian T3). Baca dulu.
Scope: apps/api saja (Node/TypeScript). Task independen dari T1/T2 (Python).

## Masalah
Web memanggil `GET /ea-api/research/strategies` (halaman Backtest, apps/web/app/backtest/page.tsx).
`/ea-api` adalah rewrite Next ke Node API. Node API (apps/api/src/index.ts) TIDAK punya route itu
-> 404 (4x di log). Python sudah punya route ini (200). Route research lain sudah diproxy — cari
dengan grep "research" di apps/api/src/index.ts dan ikuti pola yang sama (helper proxy yang ada).

## Target
- Tambah route `GET /research/strategies` di apps/api/src/index.ts dengan pola proxy yang SAMA
  seperti route research lain (helper/sendProxy yang sudah ada). Query string pass-through.
- JANGAN tambah route /risk (tidak ada caller di web saat ini).
- File index.ts punya perubahan user lain -> PATCH minimal; jangan reformat / reorder baris lain.

## TDD
1. RED dulu: tambah test mengikuti pola test route proxy yang sudah ada di apps/api (temukan lewat
   grep "research" di apps/api dan file test yang dipakai oleh `npm test`). Test membuktikan route
   terdaftar dan mem-proxy (mock/pola yang sudah dipakai test lain).
2. Implementasi -> GREEN.
3. Verifikasi: cd apps/api && npm test (baseline 53 passed) && npx tsc --noEmit && npm run lint
   (jika script ada di package.json).

## Larangan
- JANGAN git commit / git add. JANGAN reformat file lain. Tanpa dependency baru. Jangan sentuh apps/web.
- Jangan start/stop service apa pun; cukup unit test.

## Laporan
Tulis docs/tasks/FIX-503-T3-report.md: status RED->GREEN, diff ringkas, hasil test + tsc + lint.
