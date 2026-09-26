# HERMES TELEGRAM MULTI-BOT SETUP

## BOT 1
Name: Xynn
Purpose: Main / Operational
Status: CONNECTED (live `getMe` + live send test)
Existing workflows: intact and untouched — default Hermes profile, all pre-existing
interaction, supplier/SJ, notifications, automations. Token and config never modified.

## BOT 2
Name: XynnSignal
Purpose: Trading Signal / Alert
Status: CONNECTED (live `getMe` + live send test)
Trading routing: `TELEGRAM_SIGNAL_BOT_TOKEN` in `project-ea-bot/.env.runtime` now set
to XynnSignal. Verified end-to-end through the real `notifier` code path:
`notify() returned: True`. Live API status reports
`signal_bot_configured: true`, `signal_bot_connected: true`.

## BOT 3
Name: Popoy
Purpose: Research Intelligence
Status: CONNECTED (live `getMe` + live send test)
Research routing: daily cron job `11c1fbc7c261` (08:00 Asia/Jakarta) delivered to
`telegram:926385109`; real run completed with 10 findings persisted to the ledger.

## INFRASTRUCTURE FIX (2026-09-25)
```
Symptom:  Every gateway agent turn failed:
          "No module named 'pydantic_core._pydantic_core'"
Root cause: gateway/run.py:422 shim (_ensure_windows_gateway_venv_imports)
          picks a venv via VIRTUAL_ENV, else falls back to project_root/venv,
          then injects its site-packages at sys.path[1]. Both spawn paths
          (desktop VIRTUAL_ENV=hermes-agent\venv; scheduled-task VBS
          VIRTUAL_ENV=tools -> fallback) hit the stale legacy
          hermes-agent/venv (Python 3.11.16 / cp311), whose site-packages
          shadowed the PM-managed cp314 environment.
Fix:      Legacy venv MOVED (not deleted) to backups/legacy-venv-20260925.
          No code changed. Gateway restarted via scheduled task -> PID 25388.
Verified: - exact production error reproduced in isolation pre-fix, gone post-fix
          - live agent turn output: GATEWAY-TURN-OK
          - post-restart: 0 pydantic errors; 4 platforms connected
```
Correct runtime: PM-managed env `installs/125698b26551e7f0/environments/
ea94f174.../venv` (cp314, `pydantic_core` + `openai 2.24.0`).

## FREE API MODEL RADAR (added 2026-09-25)
```
Command:   /freemodels — news scan for free-API models usable via 9Router
Sources:   provider blogs/promo pages (e.g. DeepSeek V4.1 Flash free promo),
           9Router live catalog http://localhost:20128/v1/models
Baseline:  profiles/popoy/research/9router-free-snapshot.json (49 free ids)
Diff:      NEW / GONE / ending-soon expiry tracking vs snapshot
Delivery:  compact Telegram format — sections: LIVE NOW (cap + "N more"),
           NEW, NO LONGER FREE, ENDING SOON, PROMO, one-line summary
           Verified live: job completed, output rendered, delivery_outcome
           'delivered' on Telegram (test run 2026-09-25 20:34 WIB)
Integrated: supervisor skill v1.1.0 — specialist #7 (Free API model scout),
           fan-out + fact-check + daily 08:00 job now include the free sweep
```

## SPLIT TELEGRAM DELIVERY (added 2026-09-26)
```
Goal:      Daily briefing split into separate Telegram messages, one per
           section (user request): e.g. msg 1 = free API models, msg 2 =
           global news, msg 3 = trends, ... one message per section.
Mechanism: Job deliver=local suppresses the automatic final-message delivery;
           the agent itself sends each section via the official `hermes send`
           CLI (designed for scripts/cron — no LLM, no gateway round-trip):
             bin\hermes.cmd --profile popoy send --to telegram:926385109
                            --json --file "<section>.txt"
           Job prompt explicitly overrides the default cron hint ("do NOT use
           send_message or try to deliver the output yourself") because this
           job's automatic delivery is suppressed. Skill phase 4b documents
           the per-section send order + failure retry.
Verified:  - cron-context test job (deliver=local): 3 sends, message_id 20-22,
             delivery_outcome 'suppressed' (no duplicate) — PASS
           - REAL daily job run 2026-09-26 00:16-00:29 WIB: 8 separate
             messages sent (message_id 24-31), all "success": true,
             delivery_outcome 'suppressed', no [CRON_FAILURE] — PASS
           - Sections in order: FREE API MODELS / NEWS / TRENDS /
             TOP DISCOVERIES / AI / OPPORTUNITIES / UNVERIFIED / CHANGED
Failure:   job --failure-deliver telegram:926385109 — if delivery is
           impossible the agent emits [CRON_FAILURE] and the failure notice
           still reaches the user (never silently lost).
Scope:     Only the daily cron briefing is split; interactive /discover,
           /research etc. still reply as a single normal report.
```

## ROUTING
```
Main       → Xynn
Trading    → XynnSignal
Research   → Popoy
```

## TESTS
```
Xynn:        PASS
XynnSignal:  PASS
Popoy:       PASS
```
Evidence — live `getMe` (three distinct bot IDs, no duplicates):

| Bot | Username | Name | Bot ID |
|---|---|---|---|
| Xynn | @xynn91_bot | Xynn | 8624751102 |
| XynnSignal | @Xynn_signal_bot | Xynn Signal Trading | 8851989993 |
| Popoy | @xynn_research_bot | xynn_research_bot | 8485295307 |

Evidence — live delivery (each bot sent via its own token; distinct `from` identities
prove isolation): Xynn `message_id 2687`, XynnSignal `message_id 80`, Popoy `message_id 10`.

## RESEARCH
```
Supervisor:   popoy-research/SKILL.md — reads the ledger, classifies
              NEW/DEVELOPING/REPEATED, fans out, then composes the briefing
Specialists:  3-4 parallel researchers (X/Twitter, AI, news/trends; developer/GitHub
              PAUSED). Observed in a real run: 4 specialist subagents spawned
Fact Checker: mandatory verification phase — every top discovery re-checked against
              its source; unconfirmed items are quarantined into "UNVERIFIED"
Storage:      profiles/popoy/research/ledger.jsonl (JSONL, one object per finding)
              + per-run summaries in profiles/popoy/research/runs/<date>.md
Scheduler:    cron job 11c1fbc7c261, "0 8 * * *", Asia/Jakarta, active,
              next run 2026-09-23T08:00:00+07:00
Commands:     /research  /discover  /xscan  /trends   (/github-research paused)
```

## CHANGES MADE
1. `project-ea-bot/.env.runtime` — set `TELEGRAM_SIGNAL_BOT_TOKEN` (written
   programmatically by `scripts/wire_signal_bot.py`; value never printed; file gitignored).
2. `profiles/popoy/SOUL.md` — research-intelligence persona (old backed up).
3. `profiles/popoy/skills/research/{popoy-research,discover,xscan,trends,github-research}/SKILL.md`
   — supervisor/specialist/fact-checker pipeline + command entry points.
4. `profiles/popoy/config.yaml` — `skills.disabled: [github-research]` (GitHub paused).
5. `profiles/popoy/cron` job `11c1fbc7c261` — daily briefing; prompt skips GitHub.
6. `project-ea-bot/scripts/` — `wire_signal_bot.py`, `verify_signal_routing.py`,
   `restart-py-signal.ps1`, `test_signal_delivery.py`.
7. `project-ea-bot/docs/hermes_multibot/AUDIT_FINDINGS.md` — audit + post-change record.

## FILES NOT MODIFIED
- Xynn's token, `.env`, telegram config and all existing workflows.
- Trading routing code (`orchestration/runtime.py`, `notifier.py`) — the pre-existing
  `TELEGRAM_SIGNAL_BOT_TOKEN` hook was used exactly as designed.
- Existing `github` skill (plain GitHub ops) — untouched.
- `restart-py.ps1` — left as-is (stale port 8000); dedicated `restart-py-signal.ps1` added.
- MT5 execution — still `disabled (read-only)`; no trading parameters changed.

## REMAINING ACTIONS
1. Re-enable the GitHub researcher when the daily API limit clears:
   `hermes --profile popoy config set skills.disabled '[]'`
   and restore the DEVELOPER / GITHUB section in the supervisor skill.
2. `~/.hermes` is a legacy directory (1.7 MB) — NOT deleted: it still holds a
   standalone config.yaml pointing at the 9Router endpoint
   (`codebuddy-deepseekv4.1flashfree`). Left untouched; safe to delete manually
   only if that config is no longer wanted.
3. Optional: the trading inbound poller is disabled by design (only one getUpdates
   consumer per bot token, which the Hermes gateway owns).
