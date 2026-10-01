# TASK 11 — OPERATIONAL UI DATA INTEGRITY

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = 445d697 (TASK 01-10 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 13 (TASK 11) + invariant 22-23.
Safety: semua MT5 execution tetap DISARMED default. DILARANG enable LIVE / ubah default arm.

## ⚠ LESSON: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.
Web dev server SUDAH JALAN di :4321 — JANGAN start/stop/restart.
Python service jalan di :5302. Node API di :3789.

## GOAL
Audit SEMUA halaman operasional. Untuk setiap halaman, trace:
```
UI field → API endpoint → backend handler → Python source → actual data source
```

## Halaman yang WAJIB diaudit (18)
Overview, Market, Orders, Positions, Trade History, Decisions, Decision Replay,
Risk Center, Execution, AI Control, Agents, Performance, Learning, Accounts,
Certification, Observability, Reconciliation.

## Klasifikasi setiap field/data path
```
REAL       = data nyata dari broker/service
DERIVED    = dihitung dari data nyata
SIMULATED  = simulasi eksplisit (harus dilabeli di UI)
MOCK       = data karangan (DILARANG di halaman operasional)
UNAVAILABLE = tidak ada sumber (harus jujur ditampilkan)
```

## Aturan
- TIDAK BOLEH ada halaman operasional yang silently show mock data (invariant 23).
- Kalau ada MOCK → ganti dengan REAL/UNAVAILABLE atau labeli jelas; jangan hapus UI error demi dashboard terlihat sehat.
- Output: dokumen audit (mis. docs/audit/UI_DATA_INTEGRITY.md) berisi tabel lengkap 18 halaman × field × klasifikasi × source path.
- Kalau ada MOCK yang ditemukan → fix atau tandai BLOCKED di report dengan detail.

## Verifikasi
- Dokumen audit lengkap 18 halaman (setiap halaman punya minimal 1 baris trace).
- Grep tidak menemukan mock literal yang tidak dilabeli di page operasional (atau didokumentasikan sebagai temuan).
- tsc + lint web tetap pass.

## COMPLETION REPORT (format section 15 plan)
TASK: 11 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau ada halaman dengan MOCK tak ter-label → STATUS: BLOCKED dan STOP.
