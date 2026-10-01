# TASK 04 — AI CONTROL / 503 DIAGNOSTICS — COMPLETION REPORT (ATTEMPT 2)

TASK: 04
STATUS: PASS

## FILES CHANGED

Pre-existing (attempt 1, audited — NOT reverted):
- apps/api/src/errorTaxonomy.ts                (new) — 13-code taxonomy, canonical fields, retry policy
- apps/api/src/pythonClient.ts                 (mod) — attaches `taxonomy` to every proxy failure
- apps/api/src/metrics.ts                      (mod) — ErrorRecord carries code/layer/service/endpoint/retryable
- apps/api/src/index.ts                        (mod) — /ai-control/status emits classified errors + subsystem tiles
- apps/web/lib/errorTaxonomy.ts                (new) — UI codes/layers/CAUSE_LABEL + retry policy
- apps/web/lib/errorTaxonomy.test.mjs          (new)
- apps/web/app/ai-control/page.tsx             (mod) — per-agent cause/provider/model/retryable/trace; retry gating
- apps/web/app/ai-control/page.module.css      (mod)
- services/python/src/llm/errors.py            (new) — identical taxonomy on the Python side
- services/python/src/agents/activity.py       (mod) — `last_error` structured cause on AgentActivity
- services/python/src/agents/supervisor.py     (mod) — `_classify_agent_exception` records provider vs agent cause
- services/python/src/llm/advisor.py           (mod) — `classified_error` on refuse()
- services/python/src/llm/nine_router.py       (mod) — `last_classified_error` on provider failure
- services/python/src/llm/router.py            (mod) — `last_classified_error` on chain exhaustion
- services/python/src/main.py                  (mod) — /health agent entries default `last_error: null`
- apps/api/test/error-taxonomy.test.cjs        (new)
- services/python/tests/test_error_taxonomy.py (new)

Added in attempt 2:
- apps/api/test/task04-runtime-sim.cjs         (new) — bounded self-terminating runtime simulation (3 scenarios)
- logs/task04_runtime_sim_output.log           (new) — captured real runtime output (evidence)

## ROOT CAUSE

Invariants 18/19 (MASTER_PLAN §0): the Node proxy correctly returns
`503 python_service_unavailable` at the proxy boundary, but there was no shared
classification of WHICH layer failed. Consequences:
1. Every failure collapsed into an opaque shape; the UI could label a Python-down
   or LLM-503 failure as a generic "agent error".
2. The Python LLM client swallowed provider failures into the rule-based mock, so
   an upstream provider 503 never reached the UI at all — the real cause was lost.
3. Per-agent errors carried no code/provider/model/retryability, so the UI could
   not name the failing layer.
4. Attempt 1 also got stuck: it ran a stub/API server in the FOREGROUND and never
   exited (see logs/task04_attempt1_stuck.log). No runtime evidence was produced.

## FIX

1. Single taxonomy module on each side (Node `errorTaxonomy.ts`, Python
   `llm/errors.py`) with the exact 13 required codes and the canonical field set
   (trace_id, service, endpoint, status_code, agent, event_id, model, provider,
   timestamp, message, retryable). Unknown fields are `null` — never fabricated.
2. Retry policy is derived from the code (not caller input): only transient/infra
   errors are retryable. NOT retried: PYTHON_ENDPOINT_4XX, LLM_PROVIDER_4XX,
   MODEL_UNAVAILABLE, AUTH_FAILURE, DATA_GUARD_FAILURE.
3. `pythonClient` attaches a classified `taxonomy` to every failure; `index.ts`
   `/ai-control/status` returns a classified 503 (top-level `taxonomy`) when ALL
   probes fail (Python service down) and per-error, per-agent classified errors
   when degraded — so the page stays usable with partial subsystem failure.
4. Subsystem tiles (Supervisor / Python / LLM Gateway / 9Router) derive from REAL
   probes; unknown → UNAVAILABLE (never a fabricated HEALTHY).
5. Python agent runs record a structured `last_error` classified as LLM_PROVIDER_503
   / LLM_TIMEOUT / AGENT_EXCEPTION etc.; the advisor and both routers expose their
   classified last error. A 503 is attributed to `llm_provider`, never `agent`.
6. UI renders Cause / Layer / Provider / Model / HTTP / Retryable / Last event /
   Trace for each error and per agent, with a retry button gated to retryable
   errors only.
7. Runtime simulation (attempt 2 fix): a single spawn-based, self-terminating
   script with 20s readiness polling, per-call `AbortSignal.timeout(5000)`, a 90s
   in-process watchdog and a `taskkill /T /F` teardown in `finally`.

## TESTS

All commands bounded (< 60s each) with a hard outer timeout.

1) Node API build + full test suite
   - command: `cd apps/api && npm run build && node --test`
   - result: `tests 82 / pass 82 / fail 0` (includes new error-taxonomy + runtime-sim)

2) Node taxonomy unit tests
   - command: `cd apps/api && node --test test/error-taxonomy.test.cjs`
   - result: `tests 20 / pass 20 / fail 0`

3) Web taxonomy unit tests
   - command: `cd apps/web && node --test lib/errorTaxonomy.test.mjs`
   - result: `tests 5 / pass 5 / fail 0`

4) Web typecheck + lint
   - command: `cd apps/web && npx tsc --noEmit` → exit 0
   - command: `cd apps/web && npx eslint app/ai-control/page.tsx lib/errorTaxonomy.ts` → exit 0

5) Python taxonomy + touched-module tests
   - command: `cd services/python && .venv/Scripts/python.exe -m pytest tests/test_error_taxonomy.py tests/test_agent_activity.py tests/test_llm_advisor.py tests/test_supervisor.py tests/test_model_router.py -q --basetemp=<scratch>`
   - result: `72 passed`

6) Python real-path smoke (agent 503 → activity snapshot)
   - command: `.venv/Scripts/python.exe -c "... raise HttpErr(503) ... _classify_agent_exception ... tracker.record(...) ..."`
   - result: `classified: LLM_PROVIDER_503 llm_provider technical_analyst True` /
     `snapshot last_error code: LLM_PROVIDER_503 | status: active`

## RUNTIME VERIFICATION

Command (hard timeout 120s):
```
timeout 120 node apps/api/test/task04-runtime-sim.cjs
```
Result: `EXIT: 0` — `RUNTIME SIMULATION: PASS` — 24 `[PASS]` / 0 `[FAIL]`.
Full captured output: `logs/task04_runtime_sim_output.log`.

Spawned a stub Python + the REAL compiled Node API (dist/index.js) pointed at it,
minted a dev token, and hit `/ai-control/status` in three scenarios:

- SCENARIO 1 — Python unavailable (unreachable upstream):
  HTTP 503; top-level `taxonomy.code = PYTHON_SERVICE_UNAVAILABLE` (layer
  `python_service`); tiles all UNAVAILABLE; trace_id visible; retryable=true.
  NOT labelled as an agent error.

- SCENARIO 2 — LLM provider 503 (Python up; agent last_error):
  HTTP 200 (page usable); classified cause `LLM_PROVIDER_503`, layer
  `llm_provider`, provider `9router`, model `codebuddy-deepseekv4.1flashfree`,
  agent `technical_analyst`, status_code 503, retryable YES, trace_id visible;
  Python tile HEALTHY (partial failure).

- SCENARIO 3 — Agent exception (Python up; authentic agent-layer failure):
  HTTP 200; classified cause `AGENT_EXCEPTION`, layer `agent`, agent
  `structure_analyst`, retryable YES, trace_id visible.

Teardown: all children killed via `taskkill /T /F`; `netstat -ano | grep 5399`
→ EMPTY (port free). No orphan processes.

## STOP GATE 04

- [x] Simulate Python unavailable → UI says Python unavailable (S1: PYTHON_SERVICE_UNAVAILABLE)
- [x] Simulate LLM 503 → UI says LLM provider 503 (S2: LLM_PROVIDER_503, layer llm_provider)
- [x] Simulate agent exception → UI says agent exception (S3: AGENT_EXCEPTION, layer agent)
- [x] Trace ID visible (trace_id present in all 3 scenarios, shown in UI trace bar + per error)
- [x] Retryability visible (retryable=true/false rendered per error + policy-gated retry button)
- [x] No generic misleading 503 label (503 → PYTHON_SERVICE_UNAVAILABLE / PYTHON_ENDPOINT_5XX, never "agent error")
- [x] AI Control remains usable with partial subsystem failure (S2/S3 HTTP 200 with agents + tiles)
- [x] Runtime simulation output nyata dilampirkan (command + result) untuk 3 skenario

## REMAINING ISSUES

- None blocking TASK 04. The pre-existing `services/python/temp_pytest` directory
  is locked by another process (unrelated to this task) and could not be removed;
  tests were run with an explicit `--basetemp` scratch directory to avoid it.
- MT5 execution paths remain DISARMED by default; no execution code was touched.

NEXT TASK:
NOT STARTED
