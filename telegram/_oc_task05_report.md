# TASK 05 COMPLETION REPORT — COMPLETE SOURCE WIRING / ORPHAN AUDIT

```text
TASK: 05 — Complete source wiring / orphan audit
STATUS: PASS
```

## FILES CHANGED

- `docs/audit/PRODUCTION_WIRING_MAP.md` (new) — the TASK 05 deliverable: every
  module in `services/python/src` (+ worker entry points) classified with import
  path, owner, and grep evidence.
- `services/python/src/orchestration/runtime_identity.py` (new) — runtime
  identity (`process_id`, `runtime_instance_id`, `scheduler_instance_id`,
  `feed_instance_id`, + queue/supervisor/pipeline/position_monitor/
  reconciliation ids). Stdlib-only, fail-safe, diagnostic.
- `services/python/src/orchestration/runtime.py` — `OrchestrationRuntime` now
  creates `self.identity`, registers each owned component once (idempotent),
  and passes the identity to the scheduler.
- `services/python/src/trading/scheduler.py` — accepts an optional `identity`;
  every analysis log line and event-trace entry now carries the four identity
  fields (fail-safe fallback to `process_id` when absent).
- `services/python/src/trading/feed_loop.py` — accepts an optional `identity`,
  registers `feed_instance_id` at construction, logs it on start.
- `services/python/src/main.py` — passes `runtime.identity` to the feed loop.
- `services/python/src/orchestration/endpoints.py` — `GET /scheduler/status`
  now returns an `identity` block.
- `services/python/tests/test_runtime_identity.py` (new) — 14 tests proving the
  singleton rule + duplicate-worker detection + identity-in-log.

No code was deleted. Safety unchanged: execution DISARMED by default.

## ROOT CAUSE

- There was no way to *prove* at runtime that only one production instance of
  runtime/scheduler/event-queue/supervisor/pipeline/feed-loop/position-monitor/
  reconciliation-runner exists, and no artifact classifying which of the 238
  modules actually run in production. Several governance/learning/memory
  components were orphaned or test-only (master plan §1), but this had never
  been systematically evidenced.

## FIX

1. Produced a complete production wiring map (8 classes, evidence per module),
   including explicit verdicts for every "known candidate" in plan §7.
2. Verified the runtime singleton rule holds and documented the single
   ownership chain; flagged the only duplicate construction (a throwaway
   `SupervisorAgent()` certification probe in `system/certification.py:147`
   that is never wired to the pipeline).
3. Added runtime identity and stamp it on **every** analysis log line +
   event-trace entry, and exposed it via `GET /scheduler/status`.

## TESTS

```text
command: .venv/Scripts/python.exe -m pytest tests/test_runtime_identity.py -q
         -p no:cacheprovider -o addopts="" --basetemp=./temp_pytest_t05
result:  14 passed

command: .venv/Scripts/python.exe -m pytest tests/test_runtime_identity.py
         tests/test_runtime.py tests/test_scheduler.py
         tests/test_market_feed_loop.py tests/test_dead_endpoints.py -q
result:  51 passed

command: .venv/Scripts/python.exe -m pytest tests/ -q (full suite)
result:  2977 passed, 1 failed
         └─ FAILED tests/test_v2_endpoints.py::test_r_performance_endpoint_returns_buckets
            PRE-EXISTING, NOT caused by TASK 05: the test passes in isolation
            and fails identically on the base commit (git stash) — an
            order-dependent TASK 01 endpoint test-isolation bug, out of scope.

command: .venv/Scripts/python.exe -m flake8 --max-line-length=100 <changed files>
result:  clean (exit 0)
```

## RUNTIME VERIFICATION

- App lifespan (TestClient, `SCHEDULER_ENABLED=true`) → `GET /scheduler/status`
  returns `200` with an `identity` block:

```json
{ "process_id": 20808, "host": "Billy",
  "runtime_instance_id": "runtime-20808-45a7b9ba",
  "scheduler_instance_id": "scheduler-20808-41c31e0a",
  "feed_instance_id": null,
  "queue_instance_id": "queue-20808-63c447e3",
  "supervisor_instance_id": "supervisor-20808-ffd60003",
  "pipeline_instance_id": "pipeline-20808-14bb83a4",
  "position_monitor_instance_id": "position_monitor-20808-dea94aa6",
  "reconciliation_instance_id": "reconciliation-20808-4a3565ac" }
```

- Analysis log line carries the identity:

```text
INFO trading.scheduler Event analysis: XAUUSD BREAKOUT cause=qualifying:TRADE_TRIGGER
  decision=WAIT status=REJECTED dur=0.0ms process_id=9632
  runtime=runtime-9632-f6ff6e86 scheduler=scheduler-9632-ee4a317b feed=feed-9632-08d2c830
```

- Startup observed `EXECUTION IS DISARMED after startup` on every run.

### STOP GATE 05

```text
[x] Every production module has a known entry path
[x] Every background worker has one owner
[x] No duplicate scheduler/feed loops
[x] Orphans are documented (13 orphans, 3 dead-code, 2 legacy — NOT deleted)
[x] Legacy code is not accidentally imported (model_router wrapped
    deliberately; legacy market committee has 0 consumers)
[x] No hidden test-only component is assumed to be production
    (memory/*, paper/simulated_execution, ExecutionRecoveryEngine,
     learning/research_phase5, etc. classified TEST_ONLY)
```

## REMAINING ISSUES

- **Pre-existing unrelated failure:** `tests/test_v2_endpoints.py::
  test_r_performance_endpoint_returns_buckets` fails only in the full-suite run
  (order-dependent state leak). Proven present on the base commit; owned by
  TASK 01, not TASK 05.
- **Pre-existing supervisor bug found incidentally:** a live market feed event
  raises `AttributeError: 'DetectedEvent' object has no attribute 'get'` in
  `agents/supervisor.py:766` (`context.get("event")` when `event` is an object).
  Not in scope for TASK 05; recommend a follow-up (TASK 02/03 domain).
- **Orphan/dead modules** are documented but intentionally NOT removed
  (per TASK 05 rule). Removal is a candidate for a later cleanup task after
  confirming no external importer.
- The `db/*` SQLAlchemy scaffold and `demo/*` are not wired into production.

## NEXT TASK

NOT STARTED
