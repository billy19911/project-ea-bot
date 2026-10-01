# TASK 09 — MARKET FRESHNESS

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = a52ba0f (TASK 01-08 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 11 (TASK 09) + invariant 14-15 + section 15.
Safety: semua MT5 execution tetap DISARMED default. DILARANG enable LIVE / ubah default arm.

## ⚠ LESSON: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 11 + invariant 14-15.
2. TRACE dulu: feed loop → snapshot creation → snapshot consumption (committee/pipeline) → staleness check.
3. Audit-first: SKIP yg sudah benar, PATCH yg rusak, ADD hanya yg hilang. Hanya TASK 09.

## GOAL
Cegah data market BASI (stale) menghasilkan trade.

Setiap market snapshot WAJIB punya:
```
bar_timestamp, received_at, age_seconds, timeframe, symbol
```

Reject kalau:
```
age_seconds > max_allowed_age
```

## Timeframe-aware threshold
- M1: strict (mis. 90-120 detik)
- M5: lebih lebar
- H1: lebih lebar
- DILARANG hard-code satu nilai universal tanpa dokumentasi.
- Threshold harus terlihat/di-document (konstanta bernama + komentar, atau config).

## Clock anomaly
- Deteksi clock anomaly: `received_at < bar_timestamp` (clock mundur) atau timestamp masa depan → reject.
- age_seconds negatif → reject (bukan dianggap fresh).

## Stale state visible in UI
- Staleness harus terlihat di UI/dashboard (endpoint status / field yang ada).
- Cek apa yang sudah ada (mis. /market/status, snapshot meta) dan tambahkan bila hilang.

## Stale data TIDAK BOLEH sampai ke committee sebagai trade-ready context
- Snapshot stale harus di-reject SEBELUM committee/pipeline, bukan setelah.
- Pastikan gate ini fail-closed.

## STOP GATE 09
[ ] stale snapshot rejected
[ ] fresh snapshot accepted
[ ] clock anomaly rejected
[ ] stale state visible in UI
[ ] stale data cannot reach committee as trade-ready context

## COMPLETION REPORT (format section 15 plan)
TASK: 09 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
