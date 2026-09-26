# LEDGER-SLTP T2 — Stale backfill + deploy + reconciliation clean

You are T2 of a 4-task chain. Prerequisite: T1 complete — read
`docs/tasks/LEDGER-SLTP-T1-report.md` first (closure lifecycle: `mark_closed`,
`get_positions_ex`, monitor hook, provider latest-state). Do ONLY T2 scope.
You run non-interactively: decide, document, continue.

## Environment
- Repo: C:/xampp/htdocs/project-ea-bot. **Never commit.** Never reformat.
- Python: services/python/.venv/Scripts/python.exe — `src.*` imports only with cwd=services/python.
- Tests (from services/python): `./.venv/Scripts/python.exe -m pytest -q`.
- Lint on touched files only (from services/python):
  `./.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 <files>`
  `./.venv/Scripts/python.exe -m black --check <files>` (check only — do NOT reformat).

## Goal
1) New script `scripts/ledger_close_stale.py` + unit tests
   `services/python/tests/test_ledger_backfill.py`.
2) Execute the backfill on the DEMO broker ledger, restart the service with T1 code, and
   prove reconciliation is clean and the guard unblocks.

## Script spec
- Standalone; repo-root path resolution derived from `__file__` (follow the sys.path pattern
  used by `scripts/b4_demo_validation.py` so `src.*` imports work).
- Ledger default `services/python/logs/order_state.jsonl` (`--ledger` override). Instantiate
  the store pointed at that same file (same code path the service uses).
- Broker positions via `connector.get_positions_ex()`; if ok=False ⇒ ABORT (non-zero exit,
  clear message). Never print secrets/credentials.
- Candidates: latest state per intent ∈ {`position_confirmed`, `filled`} AND ticket present
  AND ticket ∉ broker positions.
- Default dry-run: table (intent_id, ticket, state, timestamp, age) + summary counts.
- `--apply`: append `closed` (reason `stale_backfill`) via `OrderStateStore.mark_closed`.
- `--ticket N`: optional single-ticket filter. Re-runs idempotent. Records without a ticket
  are skipped (report count).

## Unit tests (tmp ledgers only)
Candidate selection (latest-state semantics; closed excluded), abort on unverified read,
idempotent apply, ticket filter, no-ticket records skipped. NEVER touch the real ledger in tests.

## Execution (ops — DEMO account; expected FLAT)
1) Verify broker: positions empty. If NOT empty ⇒ STOP, report, do not close anything.
2) Restart the service with T1 code: `powershell -File scripts/restart-py.ps1`
   (wrapper may exit 124 — expected, not an error). Health: `curl -s http://127.0.0.1:8787/health`
   (add auth header if required; the key lives in the service's `.env.runtime` — read it at
   runtime, NEVER print it).
3) BEFORE capture: `POST /reconciliation/run` then `GET /reconciliation/status` — expect
   `has_critical=True` / `missing_in_broker` for the stale records (proves the bug). Save raw JSON.
4) Dry-run the script; save output (expect all stale candidates listed).
5) `--apply`; verify ledger counts: stale open records == 0; `closed` count == backfilled count.
6) AFTER capture: `POST /reconciliation/run` → expect `has_critical=False`;
   `GET /reconciliation/status` → `last_ok=True`. Save raw JSON.
7) Dry-run again → 0 candidates.
Note: if the broker read fails during any step (terminal detached), fix terminal attachment
first (terminals manager, B-4 pattern) and document.

## Constraints
- Same as T1: never commit, never reformat, preserve user changes, no secrets, minimal diffs.
- Do NOT touch: `services/python/src/config.py`, `services/python/src/main.py`,
  `apps/api/src/index.ts`; no other docs than your report.
- If a T1 defect surfaces: fix minimally WITH a test, document in the report.

## Deliverable + report
- Script + tests green; full suite green; lint clean on touched files.
- `docs/tasks/LEDGER-SLTP-T2-report.md`: before/after counts, raw JSON snippets, commands,
  ledger counts, deviations. Honest — the supervisor will independently verify.
