# TASK 07 — RISK / FINAL ORDER INVARIANT

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = bded560 (TASK 01-06 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 9 (TASK 07) + invariant 8, 9 + section 15.
Safety: semua MT5 execution tetap DISARMED default. DILARANG enable LIVE / ubah default arm.

## ⚠ LESSON: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 9 + invariant 8-9.
2. TRACE dulu: proposal → completion → normalization → order → risk gate → execution. Identifikasi urutan aktual di src/.
3. Audit-first: SKIP yg sudah benar, PATCH yg salah urutan, ADD hanya yg hilang. Hanya TASK 07.

## GOAL
Risk validation HARUS memvalidasi order FINAL yang benar-benar dikirim.

Urutan BENAR:
```
AI proposal → deterministic completion → broker normalization → final order
→ projected exposure calculation → final Risk Gate → execution
```

Urutan SALAH (dilarang):
```
Risk Gate → normalize → execute
```

## Projected exposure
Validasi:
```
existing exposure + proposed trade exposure <= exposure limit
```
Bukan hanya current exposure.

## Monetary risk (XAU/CFD)
```
risk_money = abs(entry - initial_SL) × contract_size × volume
```
- Gunakan spesifikasi simbol broker AKTUAL (symbol_info).
- DILARANG fallback contract size karangan.
- Kalau symbol spec tidak tersedia → FAIL CLOSED (reject), jangan pakai angka asumsi.

## Lot rounding
- Volume final setelah rounding lot broker (step/min/max) yang di-risk-check.
- Test naik DAN turun (round up/down).

## Invariant 8-9
- 8: Tidak ada order ke native MT5 tanpa approval deterministik.
- 9: Order final ke broker = order lolos validasi risiko FINAL.
- **final order sent == final order approved** — byte-for-byte sama (volume, SL, TP, price).

## STOP GATE 07
[ ] final normalized volume is risk-checked
[ ] proposed exposure is included
[ ] monetary SL risk is correct
[ ] broker contract specification is used (actual symbol_info, no invented fallback)
[ ] final order sent == final order approved
[ ] tests cover lot rounding upward/downward

## COMPLETION REPORT (format section 15 plan)
TASK: 07 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
