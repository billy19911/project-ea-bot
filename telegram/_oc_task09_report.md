# TASK 09 — MARKET FRESHNESS — COMPLETION REPORT

TASK: 09
STATUS: PASS

## FILES CHANGED

- `services/python/src/trading/market_freshness.py` (NEW) — deterministic freshness authority: timeframe-aware thresholds + fail-closed verdict.
- `services/python/src/trading/feed_loop.py` — stamps `bar_timestamp` / `received_at` / `age_seconds` / `timeframe` / `symbol` into every snapshot; `_bar_timestamp()` normaliser.
- `services/python/src/orchestration/pipeline.py` — Step 0.5 market-freshness gate (fail-closed) BEFORE the committee; `freshness_gate_enabled` (default True); `STATUS_STALE_MARKET_DATA`; `_resolve_market_snapshot` / `_stale_snapshot_reason`.
- `services/python/src/ops/readmodels.py` — `market_snapshot()` now exposes a `snapshot` freshness block (FRESH/STALE/NO_DATA).
- `services/python/src/market/endpoints.py` — `GET /market/health` embeds `snapshot_freshness`; new `GET /market/snapshot-status`.
- `apps/api/src/index.ts` — `/market/snapshot-status` proxy.
- `apps/web/app/market/page.tsx` + `page.module.css` — staleness chip in the Market page meta row.
- `docs/audit/PRODUCTION_WIRING_MAP.md` — classify `trading/market_freshness.py` as LIVE_RUNTIME.
- `CHANGELOG.md` — TASK 09 entry.
- Tests: `services/python/tests/test_market_freshness.py` (NEW, 20 tests); `test_market_evidence.py` + `test_entry_completion.py` updated to carry freshness metadata (production snapshots always do).

## ROOT CAUSE

Before TASK 09 the market snapshot bridge (`feed_loop → market_snapshot cache → pipeline._merge_market_snapshot → committee`) carried **no freshness proof**. A snapshot had no `bar_timestamp`/`received_at`/`age_seconds`, so a stalled feed, a quiet terminal, or clock skew could hand arbitrarily old bars to the committee as trade-ready evidence. There was no timeframe-aware age limit, no clock-anomaly detection, and no visible staleness state.

## FIX

1. **Required fields** — the feed loop stamps `bar_timestamp` (newest bar close, normalised to aware UTC), `received_at` (receive instant captured once per poll), `age_seconds` (= received_at − bar_timestamp), `timeframe`, `symbol` on every snapshot. An unparseable bar time yields a null `bar_timestamp` (never a silent "fresh").
2. **Timeframe-aware threshold** — `TIMEFRAME_MAX_AGE_SECONDS = bar period + 60s grace`: M1=120s (strict), M5=360s, H1=3660s, H4=14460s, D1=86520s. Documented named constants; unknown/empty timeframe → documented `DEFAULT_MAX_AGE_SECONDS` (M5). Not one universal value.
3. **Clock anomalies (fail-closed)** — `received_at < bar_timestamp`, future timestamps beyond a 5s skew tolerance, and negative age are all rejected. A snapshot with missing/unparseable timestamps is rejected as `timestamp_unknown`.
4. **Gate before committee** — new pipeline Step 0.5 runs before `_build_analysis_context` merges the snapshot and before `supervisor.analyze()`. Stale/anomalous → `STALE_MARKET_DATA` (WAIT), no report emitted. Verified-bad data fails closed; only a genuinely snapshot-less manual cycle is unaffected (no stale evidence to leak).
5. **Visible staleness** — ops read model + `/market/health` + new `/market/snapshot-status` surface the FRESH/STALE/NO_DATA verdict; the Market page shows a freshness chip. Absent snapshot → `NO_DATA`, never a fake "fresh".
6. **Retained safety** — no LIVE/ARM default changed; all terminals remain DISARMED by default.

## TESTS

- Command: `./.venv/Scripts/python.exe -m pytest tests -q`
  - Result: **3059 passed, 1 warning** (includes 20 new TASK 09 tests).
- Command: `./.venv/Scripts/python.exe -m pytest tests/test_market_freshness.py -q`
  - Result: **20 passed**.
- Command: `./.venv/Scripts/python.exe -m pytest tests/test_market_evidence.py tests/test_market_feed_loop.py tests/test_market_health_endpoint.py tests/test_phase7_ops.py tests/test_phase7_ops_endpoints.py -q`
  - Result: **89 passed**.
- Command: `npx tsc --noEmit` (apps/web + apps/api)
  - Result: clean.
- Command: `npx eslint app/market/page.tsx`
  - Result: clean.

## RUNTIME VERIFICATION

- Feed loop → pipeline (real classes, offline fake connector):
  - FRESH (M5, newest bar 10s old) → `status=WAIT`, committee called = True, `age=10.0s`.
  - STALE (M1, newest bar 600s old) → `status=STALE_MARKET_DATA`, committee called = **False**, `age=600.0s`, reason `stale_market_data:age_exceeded`.
- API (TestClient, `.env.runtime` key):
  - `GET /market/snapshot-status` → `NO_DATA` / `FRESH` / `STALE` (reason `stale_market_data:age_exceeded`).
  - `GET /market/health` → embeds `snapshot_freshness.status`.
- Wiring: production feed loop (`main.py:538`, default connector) stamps freshness; production pipeline (`runtime.py:923`, `freshness_gate_enabled` default True) gates it.

## STOP GATE 09

- [x] stale snapshot rejected
- [x] fresh snapshot accepted
- [x] clock anomaly rejected
- [x] stale state visible in UI
- [x] stale data cannot reach committee as trade-ready context

## REMAINING ISSUES

- None blocking. The gate intentionally does not reject a snapshot-less cycle (historic manual-run behaviour preserved; there is no stale evidence to leak).

## NEXT TASK

NOT STARTED
