# HERMES TELEGRAM MULTI-BOT — AUDIT FINDINGS (pre-change)

## Existing architecture: profile-based multiplexer (Hermes v0.21.4)

ONE host gateway (PID 24804) serves 3 profiles:
`served_profiles: ["default", "popoy", "xynnsignal"]`

| Bot | Profile | Bot username | Bot ID | Token location |
|---|---|---|---|---|
| Xynn | default | @xynn91_bot | 8624751102 | `<HERMES_HOME>/.env` |
| Popoy | popoy | @xynn_research_bot | 8485295307 | `profiles/popoy/.env` |
| XynnSignal | xynnsignal | @Xynn_signal_bot | 8851989993 | `profiles/xynnsignal/.env` |

All 3 verified LIVE via Telegram `getMe` — 3 distinct bot IDs (no duplicates).

## Trading system: C:\xampp\htdocs\project-ea-bot

- Python FastAPI on 127.0.0.1:8787, config from `.env.runtime` (gitignored, untracked)
- `TELEGRAM_BOT_TOKEN` = Xynn's token (862475…HPJc) → primary gateway
- `TELEGRAM_SIGNAL_BOT_TOKEN` = **COMMENTED OUT** → no signal bot
- `notifier.get_report_gateway()` prefers signal gateway, **falls back to primary**

### ⇒ THE MISROUTING
Trading cycle digests / market analysis currently deliver to **Xynn** because
the signal bot is unconfigured. The system already contains the correct hook
(`TELEGRAM_SIGNAL_BOT_TOKEN`) — designed for exactly this split. No code rewrite
needed; only the routing destination must be set.

- MT5 mode: `execution: disabled (read-only)`, `execution_armed: false` → SAFE
- Scheduler: running, 708 proposed / 708 blocked / 0 executed
- Open positions exist (XAUUSD SELL) but no execution possible
- Telegram inbound poller: disabled (avoids getUpdates conflict)

## Research system: profile `popoy`

- SOUL.md currently WRONG: "Coding — Vibe coding" (not a research identity)
- No cron jobs, no research agents, no research history storage
- Bundled skills present under `profiles/popoy/skills/`

## Native mechanisms available (to prefer over new implementation)

- `hermes send --to telegram` (bot-token platforms, no agent loop)
- `hermes cron create` with `--deliver`, `--skill`, `--no-agent`, monitor mode
- `quick_commands` in config.yaml: types `exec` | `alias` only
- Skills auto-register `/<name>` slash commands from frontmatter `name:`
- `hermes --profile <name>` selects profile (pre-parsed, sets HERMES_HOME)
- Gateway constraint: only ONE getUpdates consumer per bot token
