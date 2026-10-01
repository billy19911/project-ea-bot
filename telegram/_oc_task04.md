# TASK 04 — AI CONTROL / 503 DIAGNOSTICS (ATTEMPT 2)

Repo: C:\xampp\htdocs\project-ea-bot. Branch main. HEAD = d859e91 (TASK 01-03 done).
Master plan: telegram/_MASTER_PLAN.md — BACA section 6 (TASK 04) + invariant 18,19 + section 15.
Safety: semua MT5 execution tetap DISARMED default.

## ⚠ ATTEMPT 1 SUDAH STUCK DI RUNTIME SIMULATION — JANGAN ULANGI KESALAHANNYA
Attempt 1 hang karena menjalankan server (stub Python / Node API) di FOREGROUND (command
blocking, tidak pernah exit). Log attempt 1: logs/task04_attempt1_stuck.log
Code changes attempt 1 SUDAH ADA di working tree (uncommitted) — AUDIT dulu, JANGAN revert:
- apps/api/src/errorTaxonomy.ts (baru), pythonClient.ts, metrics.ts, index.ts
- apps/web/app/ai-control/page.tsx + page.module.css, apps/web/lib/errorTaxonomy.test.mjs (baru)
- services/python/src: agents/activity.py, agents/supervisor.py, llm/advisor.py, llm/nine_router.py, llm/router.py, main.py
- tests: apps/api/test/error-taxonomy.test.cjs (baru)
Tugasmu: (1) audit implementasi existing vs requirement di bawah — patch gap; (2) SELESAIKAN
runtime simulation 3 skenario dengan pola bounded di bawah; (3) completion report.

## ATURAN RUNTIME SIMULATION (WAJIB — INI YANG BIKIN ATTEMPT 1 STUCK)
1. JANGAN jalankan server blocking di foreground. Tulis SATU script self-terminating
   (contoh: apps/api/test/task04-runtime-sim.cjs) yang:
   spawn stub-python + Node API (child_process.spawn, cwd benar, env: PYTHON_SERVICE_URL ke stub,
   PORT scratch mis. 5399) → tunggu ready dengan fetch + AbortSignal.timeout(5000) (poll max 20x)
   → jalankan 3 skenario → kill semua child di finally → process.exit(0).
2. Jalankan dengan hard timeout: timeout 120s node apps/api/test/task04-runtime-sim.cjs
3. Setiap command WAJIB selesai < 60 detik. Kalau hang → kill → ganti pendekatan.
4. Fallback (kalau spawn-server tetap bermasalah): integration test in-process
   (node:test) yang boot handler langsung / mock python client, TAPI tetap harus
   membuktikan klasifikasi 3 skenario dengan output nyata. Dokumentasikan pendekatan.
5. Bersihkan semua proses orphan di akhir (stub/API). Verifikasi: netstat -ano | grep 5399 kosong.

Catatan dari attempt 1 (breadcrumbs): /ai-control/status TIDAK auth-guarded; API tidak
export app (server.listen di bawah index.ts); apps/api `npm run build` OK.

## ATURAN EKSEKUSI
1. READ: telegram/_MASTER_PLAN.md section 6.
2. TRACE dulu: Node proxy error path → Python endpoints → agent error handling → LLM provider calls → AI Control UI page.
3. Audit-first. Hanya TASK 04.

## GOAL
AI Control page: 503 errors harus mengidentifikasi failing layer yang sebenarnya.

Node proxy saat ini return `503 python_service_unavailable` saat Python unreachable — itu benar di proxy boundary, TAPI UI tidak boleh menyebut semua 503 sebagai "agent error".

## REQUIRED ERROR TAXONOMY (implementasi lengkap)
NODE_API_UNAVAILABLE, PYTHON_SERVICE_UNAVAILABLE, PYTHON_ENDPOINT_4XX, PYTHON_ENDPOINT_5XX, AGENT_TIMEOUT, AGENT_EXCEPTION, LLM_PROVIDER_4XX, LLM_PROVIDER_5XX, LLM_PROVIDER_503, LLM_TIMEOUT, MODEL_UNAVAILABLE, AUTH_FAILURE, DATA_GUARD_FAILURE.

Setiap error harus carry: trace_id, service, endpoint, status_code, agent, event_id, model, provider, timestamp, message, retryable.

## AI CONTROL UI
Tampilkan:
```
Supervisor: ACTIVE
Python: HEALTHY
LLM Gateway: HEALTHY
9Router: HEALTHY
Agents: 7 active / 1 error
```
Jika agent error, tampilkan detail:
```
TREND-SCAN
Status: ERROR
Cause: LLM_PROVIDER_503
Provider: ...
Model: ...
Retryable: YES
Last event: ...
Trace: ...
```
Bukan hanya "agent error".

## RETRY POLICY
Hanya retry error yang retryable. Jangan retry: invalid schema, risk rejection, auth failure, missing data.

## STOP GATE 04
[ ] Simulate Python unavailable → UI says Python unavailable
[ ] Simulate LLM 503 → UI says LLM provider 503
[ ] Simulate agent exception → UI says agent exception
[ ] Trace ID visible
[ ] Retryability visible
[ ] No generic misleading 503 label
[ ] AI Control remains usable with partial subsystem failure
[ ] Runtime simulation output nyata dilampirkan (command + result) untuk 3 skenario

## COMPLETION REPORT (format section 15 plan)
TASK: 04 / STATUS: PASS atau BLOCKED / FILES CHANGED / ROOT CAUSE / FIX / TESTS (command+result) / RUNTIME VERIFICATION / REMAINING ISSUES / NEXT TASK: NOT STARTED
Kalau satu kriteria gagal: STATUS: BLOCKED dan STOP.
