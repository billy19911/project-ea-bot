# TASK 02 — EVENT-DRIVEN SUPERVISOR / WAKE MODEL

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = 950e8a1 (TASK 01 done).
Master plan lengkap ada di: telegram/_MASTER_PLAN.md — BACA section 4 (TASK 02) + section 0 invariant 14-16 + section 15 protocol.
Safety: semua MT5 execution tetap DISARMED default. Dilarang enable LIVE. Dilarang ubah default arm.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 4 + invariant 14,15,16.
2. TRACE dulu: feed_loop.py → EventDetector → event cooldown → event fingerprint → EventQueue → scheduler.wake() → pipeline → Supervisor. Jangan asumsi.
3. Audit-first: SKIP yg sudah benar, PATCH yg rusak, ADD hanya yg hilang.
4. JANGAN kerjakan task lain. Hanya TASK 02.

## GOAL
Supervisor TIDAK wake tiap 1-2 menit hanya untuk minta analisis lagi. Desired:
NO EVENT → SUPERVISOR IDLE. QUALIFYING EVENT → wake scheduler immediately → supervisor → committee → decision.

Polling market (MT5 read bars) boleh periodik — itu BUKAN analisis. Analisis (supervisor → agents → committee) hanya setelah qualifying event.

## INVESTIGASI WAJIB
Kenapa user saat ini melihat analisis 1-2 menit? Trace & rekam untuk setiap analysis:
event_id, event_type, event_created_at, bar_time, feed_poll_time, queue_time, scheduler_wake_time, supervisor_start, supervisor_end.
Tentukan apakah cadence 1-2 menit disebabkan oleh:
1. actual event generation, 2. candle close cadence, 3. cooldown, 4. repeated event types,
5. manual polling endpoint, 6. UI auto-refresh mistaken for supervisor activity,
7. background worker invoking pipeline directly, 8. duplicate scheduler/runtime instances.

## EVENT CLASSES (pisahkan)
- TRADE_TRIGGER (BREAKOUT, BREAKDOWN, REVERSAL, STRUCTURE_SHIFT, MOMENTUM_CONFIRMATION, ZONE_ENTRY, VOLATILITY_EXPANSION) → boleh trigger committee analysis.
- CONTEXT_UPDATE (NEWS_UPDATE, ECONOMIC_EVENT, REGIME_CHANGE, VOLATILITY_CHANGE) → update context, tidak harus buat trade proposal baru.
- HOUSEKEEPING (RECONCILIATION, HEALTH_CHECK, METRICS) → TIDAK BOLEH buat trade signal.
- TRADE_CLOSE → review/learning, boleh minta evaluasi opportunity baru, tapi TIDAK blind repeat sinyal sebelumnya.

## REQUIRED BEHAVIOR
Satu opportunity: event A → committee → signal_id S1. Event A duplicate → TIDAK boleh buat S2/S3/S4 kecuali opportunity materially changed.

## STOP GATE 02
[ ] Supervisor tidak jalan pada fixed 1-2 menit decision timer
[ ] Qualifying event wakes scheduler immediately
[ ] Duplicate events tidak buat duplicate committee cycles
[ ] UI polling tidak bisa trigger analysis
[ ] Health/reconciliation tidak bisa trigger trade proposal
[ ] Event trace menunjukkan exact wake cause
[ ] Tests cover event/no-event/duplicate-event behavior

## COMPLETION REPORT (format section 15 plan)
TASK: 02 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
