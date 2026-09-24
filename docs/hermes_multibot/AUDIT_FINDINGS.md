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
- `skills.disabled: [...]` in a profile's `config.yaml` disables skills
  (honoured by the skill loader; also removes their slash commands)

---

# POST-CHANGE STATE (final verification)

## Routing (all three legs live-tested)

| Leg | Mechanism | Test | Result |
|---|---|---|---|
| Main → Xynn | default profile | `hermes send --to telegram` | PASS (message_id 2683) |
| Trading → XynnSignal | `TELEGRAM_SIGNAL_BOT_TOKEN` in `.env.runtime` | `scripts/test_signal_delivery.py` via real `notify()` | PASS (`notify() returned: True`, token fp `885198…p4w0` = XynnSignal) |
| Research → Popoy | cron job `11c1fbc7c261` deliver telegram | real daily run | PASS (`delivered to telegram:926385109`, 10 findings) |

## Changes made

1. `/c/xampp/htdocs/project-ea-bot/.env.runtime` — set `TELEGRAM_SIGNAL_BOT_TOKEN`
   to XynnSignal's token (written programmatically by `scripts/wire_signal_bot.py`;
   never printed; file is gitignored).
2. `profiles/popoy/SOUL.md` — replaced coding persona with research-intelligence
   persona (old file backed up as `SOUL.md.bak-<ts>`).
3. `profiles/popoy/skills/research/{popoy-research,discover,xscan,trends,github-research}/SKILL.md`
   — new supervisor/specialist/fact-checker pipeline + command entry points.
4. `profiles/popoy/config.yaml` — added `skills.disabled: [github-research]`
   (GitHub researcher paused; backup `config.yaml.bak-<ts>`).
5. `profiles/popoy/cron` job `11c1fbc7c261` — daily 08:00 Asia/Jakarta briefing,
   prompt updated to skip the paused GitHub specialist.
6. `/c/xampp/htdocs/project-ea-bot/scripts/` — `wire_signal_bot.py`,
   `verify_signal_routing.py`, `restart-py-signal.ps1`, `test_signal_delivery.py`.

## Files NOT modified

- Xynn's token/config/workflows (`.env`, `config.yaml` telegram block) — untouched.
- Trading routing code (`orchestration/runtime.py`, `notifier.py`) — untouched;
  the pre-existing `TELEGRAM_SIGNAL_BOT_TOKEN` hook was used as designed.
- Existing `github` skill in Popoy — untouched; research command is
  `/github-research` to avoid the name clash.
- `restart-py.ps1` — left as-is (stale port 8000); a dedicated
  `restart-py-signal.ps1` was added instead.
- MT5 execution mode — still `disabled (read-only)`; no trading config changed.

## Known issue (historical, not reproduced)

`logs/python-8787.log:100` had one `Failed to send Telegram alert to 926385109:
Telegram sendMessage failed (ConnectError)` before the service restart
(21:19). After the restart the same code path succeeds live
(`test_signal_delivery.py` → DELIVERED). Treated as a transient network error.

