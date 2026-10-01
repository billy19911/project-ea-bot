# TASK 06 — MULTI-MT5 / ONE SIGNAL → MANY ACCOUNTS

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = fc4c8e9 (TASK 01-05 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 8 (TASK 06) + invariant 1-4, 6-9 + section 15.
Safety: semua MT5 execution tetap DISARMED default. DILARANG enable LIVE / ubah default arm.

## ⚠ LESSON: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 8 + invariant 1-4, 6-9.
2. TRACE dulu: pipeline → signal creation → execution fan-out → per-terminal arm gate.
3. Audit-first: SKIP yg sudah benar, PATCH yg rusak, ADD hanya yg hilang. Hanya TASK 06.

## GOAL — model trading yang benar:
```
1 Supervisor → 1 Committee → 1 Canonical Signal → N MT5 Accounts
```

## Canonical signal (immutable)
signal_id, opportunity_id, symbol, direction, entry_reference, initial_SL, initial_TP,
planned_RR, risk_policy, strategy_version, created_at, evidence_hash.
signal_id SAMA untuk setiap account.

## Fan-out (per eligible terminal)
canonical signal → account-specific context → broker normalization → account-specific Risk Gate → execution.
Signal TIDAK BOLEH berubah. Hanya nilai account-specific yang boleh beda (volume, digits, point,
min/max/step, price normalization, margin, risk budget).

## Critical rule
A approved / B rejected / C approved → JANGAN minta Supervisor generate signal baru untuk B.
B cukup: signal_id S1, account B, status REJECTED, reason ...

## Fan-out status
signal_status: CREATED, VALIDATED, PARTIALLY_EXECUTED, EXECUTED_ALL, REJECTED_ALL, EXPIRED.
Per account: PENDING, APPROVED, REJECTED, SUBMITTING, SUBMITTED, FILLED, FAILED, RECONCILED, CLOSED.

## Demo/Live arming
Setiap terminal: execution_allowed (true/false), armed = false default SELALU, environment = DEMO/LIVE.
LIVE boleh dikonfigurasi eligible TAPI tetap DISARMED. Demo boleh di-arm eksplisit.
Terminal selection BUKAN satu-satunya cara kontrol eksekusi jika multi-terminal fan-out aktif.

## STOP GATE 06
[ ] One event creates one signal_id
[ ] One supervisor analysis only
[ ] 2+ demo terminals receive the same signal_id
[ ] Live terminal can be configured but starts disarmed
[ ] Arm is explicit
[ ] One account rejection does not create a second signal
[ ] Per-account risk is enforced
[ ] No account can bypass the canonical signal
[ ] Duplicate fan-out cannot duplicate orders

## COMPLETION REPORT (format section 15 plan)
TASK: 06 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
