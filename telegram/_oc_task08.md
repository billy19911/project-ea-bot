# TASK 08 — RECONCILIATION + RESTART RECOVERY

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = 5323295 (TASK 01-07 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 10 (TASK 08) + invariant 12 + section 15.
Safety: semua MT5 execution tetap DISARMED default. DILARANG enable LIVE / ubah default arm.

## ⚠ LESSON: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 10.
2. TRACE dulu: intent persistence → restart load → MT5 connect → positions read → reconcile → state rebuild → execution permit.
3. Audit-first: SKIP yg sudah benar, PATCH yg rusak, ADD hanya yg hilang. Hanya TASK 08.

## GOAL
Broker state dan internal state HARUS konvergen dengan aman.

## Durable order identity (WAJIB dipersist)
```
intent_id, signal_id, account_id, terminal_id,
broker_order_ticket, broker_deal_ticket, broker_position_ticket
```

## Restart sequence (WAJIB urut)
```
load durable intents → connect MT5 → read open positions → read recent orders/deals
→ reconcile → rebuild internal state → ONLY THEN permit new execution
```

## Fail-closed rule
- Kalau state TIDAK PASTI (uncertain) → **BLOCK NEW ORDERS**.
- DILARANG mengartikan `internal = empty` sebagai `broker = empty`.
- Orphan broker position (ada di broker, tidak ada di internal) → blokir entry baru.
- Duplicate recovery TIDAK BOLEH membuat order duplikat (idempotency by intent_id).

## STOP GATE 08
[ ] Restart with open trade → state restored
[ ] Restart with closed trade → review still possible
[ ] Orphan broker position blocks new entries
[ ] Unknown reconciliation state blocks new entries
[ ] Duplicate recovery does not create duplicate order

## COMPLETION REPORT (format section 15 plan)
TASK: 08 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
