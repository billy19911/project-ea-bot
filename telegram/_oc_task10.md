# TASK 10 — UI / HEADER / RESPONSIVE PROFESSIONAL PASS

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = d514971 (TASK 01-09 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 12 (TASK 10) + invariant 23-24 + section 15.
Safety: semua MT5 execution tetap DISARMED default. DILARANG enable LIVE / ubah default arm.

## ⚠ LESSON: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.
Web dev server SUDAH JALAN di :3000 (PID 33048) — JANGAN start/stop/restart server itu.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 12.
2. TRACE dulu: AppShell.tsx + AppShell.module.css → topbar/topbarText/actions → semua halaman yang pakai.
3. Audit-first: SKIP yg sudah benar, PATCH yg rusak, ADD hanya yg hilang. Hanya TASK 10.

## GOAL
Fix header widths/alignment TANPA redesign total aplikasi.

## Required changes (dari plan)
- Layout robust: `grid-template-columns: minmax(0, 1fr) auto;` (atau equivalent).
- `topbarText: min-width: 0` (WAJIB — supaya text bisa shrink, bukan overflow).
- `actions: flex-wrap: wrap` di breakpoint yang tepat.
- Buttons TIDAK PERNAH overflow viewport.
- Environment badge TIDAK PERNAH clip.
- Theme toggle TIDAK PERNAH clip.
- Page actions: move/wrap di breakpoint terdefinisi.
- DILARANG menyelesaikan dengan menyembunyikan status critical (invariant 23: no mock/hide; jangan hide UI errors).

## Responsive breakpoints yang harus benar
1920 / 1600 / 1440 / 1280 / 1100 / 1024 / 920 / 768 / 480 / 390

## Check list
- topbar border extends exactly to content width
- title aligns with page body
- right controls align consistently
- NO horizontal scrollbar di semua breakpoint
- sticky header tidak overlap content
- action controls tidak push title keluar viewport
- collapsed sidebar tetap align

## STOP GATE 10
[ ] no horizontal overflow
[ ] header aligned at all listed widths
[ ] title/action spacing consistent
[ ] sticky behavior correct
[ ] desktop/tablet/mobile screenshots visually inspected
[ ] tsc passes
[ ] lint passes

## CARA VERIFIKASI
- `npx tsc --noEmit` di apps/web → clean.
- `npm run lint` di apps/web → clean.
- Screenshot verification akan dilakukan ORCHESTRATOR dengan browser tool (JANGAN install playwright/puppeteer; JANGAN start server baru).
- Kamu WAJIB menulis test/logic verification yang bisa di-run tanpa browser bila memungkinkan (mis. CSS assertions via grep tidak cukup — pakai tsc+lint+manual review CSS).

## COMPLETION REPORT (format section 15 plan)
TASK: 10 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
