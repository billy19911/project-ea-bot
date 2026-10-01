# TASK 05 — COMPLETE SOURCE WIRING / ORPHAN AUDIT

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = 2e38d19 (TASK 01-04 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 7 (TASK 05) + invariant 20,21 + section 15.
Safety: semua MT5 execution tetap DISARMED default.

## ⚠ LESSON FROM TASK 04: JANGAN jalankan server blocking di foreground. Semua command harus selesai < 60 detik.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 7 + invariant 20,21.
2. Hanya TASK 05.
3. Do NOT delete code automatically. First classify and document.

## GOAL
Determine exactly what runs in production. Create: docs/audit/PRODUCTION_WIRING_MAP.md

## WAJIB: klasifikasikan SETIAP modul di services/python/src (dan worker entry points lain) ke salah satu:
LIVE_RUNTIME, BACKGROUND_WORKER, API_ENDPOINT, UI_ONLY, TEST_ONLY, LEGACY, ORPHANED, DEAD_CODE.
Untuk setiap modul: import path dari entry point (atau "none" jika orphan), siapa yang meng-import,
dan bukti (grep command yang kamu jalankan).

## Known candidates requiring explicit classification (dari audit sebelumnya):
llm/model_router.py, learning/engine_v2.py, learning/*, execution/order_builder.py / ExecutionRecoveryEngine,
paper/simulated_execution.py, memory/*, agents/task.py, orchestration/context_builder.py, agents/evidence.py,
agents/decision_state.py, agents/permissions.py, risk/MultiLevelBreaker, risk/CapitalAllocator,
trading/EventDeduplicator, research/*, strategy/LifecycleGovernor, market/intelligence legacy committee.

## Runtime singleton rule
Harus ada tepat SATU production instance dari: runtime, scheduler, event queue, supervisor, pipeline,
market feed loop, position monitor, reconciliation runner — kecuali komponen di-scope per account/terminal
secara eksplisit (catat yang mana).

## Detect duplicate workers
Tambah runtime identity: process_id, runtime_instance_id, scheduler_instance_id, feed_instance_id.
Setiap analysis log harus memuatnya. Implementasi + buktikan dengan test/runtime output.

## STOP GATE 05
[ ] Every production module has a known entry path
[ ] Every background worker has one owner
[ ] No duplicate scheduler/feed loops
[ ] Orphans are documented
[ ] Legacy code is not accidentally imported
[ ] No hidden test-only component is assumed to be production

## COMPLETION REPORT (format section 15 plan)
TASK: 05 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) /
RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
