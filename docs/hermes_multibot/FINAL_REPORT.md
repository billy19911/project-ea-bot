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
2. `~/.hermes` is a stale legacy directory — safe to delete manually if desired.
3. Optional: the trading inbound poller is disabled by design (only one getUpdates
   consumer per bot token, which the Hermes gateway owns).
