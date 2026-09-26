# LEDGER-SLTP T4 — Evidence consolidation + docs + final verification

You are T4 (final) of the chain. Prerequisites: T1–T3 complete — read all three reports.
You run non-interactively: decide, document, continue.

## Environment
- Repo: C:/xampp/htdocs/project-ea-bot. **Never commit.** Never reformat.
- Python: services/python/.venv/Scripts/python.exe — `src.*` imports only with cwd=services/python.
- Tests (from services/python): `./.venv/Scripts/python.exe -m pytest -q`.
- Lint: `./.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 <files>`
  + `black --check` (check only).

## Goal
1) Consolidate `docs/evidence/LEDGER-SLTP-validation.{md,json}` — the single authoritative
   record: ledger before (stale count, `has_critical=True`) → after (0 stale,
   `has_critical=False`); SL/TP live validation (requested vs broker sl/tp, close, ledger
   `closed` record); links to raw artifacts; no secrets.
2) Update `docs/audit/RELEASE_BLOCKERS.md` B-4 residual note (~line 78): ledger closure
   lifecycle → FIXED (evidence link); live SL/TP attach → exercised (evidence link). Keep
   wording honest; #3/#4/#5 remain open items — do not overstate.
3) Final verification:
   - full suite from services/python (baseline 2242 + new tests, all green);
   - lint clean on ALL files touched in T1–T4;
   - ledger invariants: 0 stale open records; `closed` count consistent with evidence;
   - `GET /reconciliation/status` → `last_ok=True` still;
   - `git status` — confirm no commit happened; only expected uncommitted files.
4) Write `docs/tasks/LEDGER-SLTP-T4-report.md` with the final checklist + evidence paths.

## Constraints
- Same as T1–T3: no commit, no reformat, preserve user changes, no secrets, minimal diffs.
- Do NOT touch: `services/python/src/config.py`, `services/python/src/main.py`,
  `apps/api/src/index.ts`.
- Honest reporting only — no invented results. The supervisor will independently verify.
