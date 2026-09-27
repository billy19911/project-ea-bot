# TASK T5 — Market session awareness (detect closed/holiday markets) + crypto 24/7 support

## Problem (verified live on 2026-09-27, a Sunday)

1. **No market-session detection exists anywhere.** The feed loop keeps polling
   `XAUUSD` on weekends and analysing 33-hour-old bars as if they were fresh.
   Verified: XAUUSD last tick age = 1976 minutes, last M5 bar = Saturday 06:55;
   yet the pipeline still emits analysis/signals from that stale data.
2. **Crypto is tradable 24/7 but is never polled.** The broker
   (HFMarketsGlobal-Demo, 345 symbols) lists crypto as `#BTCUSD`, `#ETHUSD`
   (prefix `#`), both `trade_mode=4` (full). Verified: `#BTCUSD` has live bars
   right now (age ~0 min, price ~84.7k) while XAUUSD is closed.
   `resolve_symbol("BTCUSD")` already resolves to `#BTCUSD` correctly.
   But `.env.runtime` has `MARKET_FEED_SYMBOLS=XAUUSD` only, so BTC is never
   analysed — even though it can be traded on weekends.

## Goal

The system must:
- **A. Detect when a market is closed** (weekend/holiday/off-session) and SKIP
  polling/analysis for that symbol instead of analysing stale data.
- **B. Keep trading crypto 24/7** — crypto symbols are always "open"; when the
  feed is configured with both XAUUSD and BTCUSD, BTC keeps flowing on weekends
  while XAUUSD is skipped.

## Design (agreed — implement exactly this)

### 1. NEW module `services/python/src/market/sessions.py`

Pure, testable, fail-open. Public API:

```python
def classify_symbol(symbol: str) -> str:
    """Return "crypto" or "non_crypto" (asset-class guess)."""

def get_market_session(
    symbol: str,
    connector: Any = None,       # object exposing get_ohlc(symbol, tf, count) / get_tick(symbol)
    max_age_s: float = 1800.0,   # 30 minutes; data older than this => market closed
    now: Optional[datetime] = None,  # injectable for tests; default utcnow aware
) -> dict:
    """Return {"symbol", "asset_class", "open": bool, "reason": str,
               "bar_age_s": float|None, "tick_age_s": float|None,
               "checked_at": iso8601 str}"""
```

Rules (STRICT — these are the acceptance criteria):

1. **Crypto classification**: normalise the symbol (strip `#`, broker
   prefixes/suffixes, non-alphanumerics, uppercase) and check whether the
   *base* contains a known crypto token: BTC, ETH, XRP, SOL, ADA, DOGE, LTC,
   BCH, DOT, AVAX, LINK, MATIC, TRX, XLM, ATOM, NEO, EOS, XTZ, ETC, FIL,
   SHIB, PEPE, BNB. Examples that MUST classify as crypto:
   `BTCUSD`, `#BTCUSD`, `BTCEUR`, `BTCJPY`, `ETHBTC`, `SOLUSD`, `#ETHUSD`.
   Examples that MUST classify as non_crypto: `XAUUSD`, `XAGUSD`, `EURUSD`,
   `US500`, `#FirstSolar`.
2. **Crypto => always open**: `open=True`, `reason="crypto trades 24/7"`,
   regardless of bar/tick age (stale crypto feed is a FEED problem, not a
   closed market; do not hide it as "closed").
3. **Non-crypto => data-driven age check** (NO hardcoded session hours /
   timezones / DST / holiday tables — those are brittle):
   - Fetch `bars = connector.get_ohlc(symbol, "M5", 2)` and
     `tick = connector.get_tick(symbol)`.
   - Compute `bar_age_s` from the last bar's `time` and `tick_age_s` from the
     tick's `time` (handle naive datetimes: treat as UTC).
   - Use the **MINIMUM** of the available ages as the freshest evidence:
     `age = min(available ages)`. If ANY data source is fresh, the market is
     considered OPEN (fail-open friendly; a single stale source must not fake
     a closure).
   - `open = age <= max_age_s`. Reason strings:
     - open: `"market open (last data {age:.0f}s old)"`
     - closed: `"market closed (last data {age:.0f}s old > {max_age_s:.0f}s)"`
   - If no age can be computed (no bars AND no tick, or both `None`), return
     `open=True` with `reason="session check inconclusive (fail-open)"`.
   - Any exception => `open=True`, `reason="session check failed (fail-open)"`.
4. `connector=None` default => use the production module
   `from ..mt5 import connector` (read-only data functions only).
5. Never import execution/order code. Read-only module.

### 2. MODIFY `services/python/src/trading/feed_loop.py`

- Add constructor params:
  - `session_max_age_s: float = 1800.0`
  - `session_provider: Optional[Callable[[str], dict]] = None` (test seam;
    when None use `market.sessions.get_market_session` with
    `connector=self._connector, max_age_s=self.session_max_age_s`).
- In `_poll_symbol(symbol)`, BEFORE fetching OHLC:
  ```python
  try:
      session = self._session_status(symbol)
      if not session.get("open", True):
          logger.info("Market feed: %s market closed (%s) — skipping",
                      symbol, session.get("reason"))
          return 0
  except Exception as exc:  # noqa: BLE001 — fail-open, never block on session check
      logger.debug("Market feed session check skipped: %s", exc)
  ```
- After building the snapshot, attach the session dict when available:
  `snapshot["session"] = session` (best-effort; wrap so it can never kill the loop).
- The module MUST remain free of execution/order imports (existing guard test
  `test_market_feed_loop.py::test_module_has_no_execution_imports` must still pass).

### 3. MODIFY `services/python/src/market/endpoints.py`

Add read-only endpoint:

```python
@router.get("/session")
async def market_session(
    symbol: str = Query(default="XAUUSD", description="Symbol to check"),
) -> dict:
    """Return live market-session status for *symbol* (open/closed + reason)."""
    from .sessions import get_market_session
    return {"status": "ok", **get_market_session(symbol)}
```

### 4. NEW test file `services/python/tests/test_market_sessions.py`

TDD: write tests FIRST, run serial, then implement. Required coverage
(fake connectors only — NO real MT5, NO network):

- `classify_symbol`: `BTCUSD`, `#BTCUSD`, `BTCEUR`, `ETHBTC`, `SOLUSD`,
  `#ETHUSD` => crypto; `XAUUSD`, `XAGUSD`, `EURUSD`, `US500`, `#FirstSolar`
  => non_crypto.
- crypto weekend: bars 33h old + tick 33h old => `open=True`,
  `asset_class="crypto"`.
- non-crypto closed: bars 33h old + tick 33h old => `open=False`.
- non-crypto open: bars 2min old + tick 5s old => `open=True`.
- min-age semantics: bar 33h old but tick 5s old => `open=True`.
- fail-open: connector raising on both calls => `open=True`.
- fail-open: connector returning `None`/`[]` => `open=True`.
- naive datetimes are treated as UTC (no crash, sensible ages).
- feed loop integration: with a `session_provider` returning `{"open": False}`
  for XAUUSD and `{"open": True}` for BTCUSD, `poll_once()`:
  - enqueues ZERO events for XAUUSD and never calls `get_ohlc` for it,
  - still processes BTCUSD normally (events flow),
  - a raising `session_provider` must NOT stop the symbol from being polled
    (fail-open).
- existing feed-loop invariants still hold (dedup, cooldown, no execution imports).

### 5. Do NOT touch

- `services/python/src/config.py` (user-owned changes; off-limits).
- `services/python/src/main.py` (user-owned hunk; off-limits for this task).
- `.env.runtime` (the orchestrator updates `MARKET_FEED_SYMBOLS` itself).
- Any other file not listed above.

## Hard constraints

- Python: `services/python/.venv/Scripts/python.exe` for ALL python commands.
- Run pytest from cwd `services/python`, serial (`-p no:cacheprovider` not needed;
  just do NOT run pytest in parallel with other pytest processes).
- Lint your files before finishing:
  `services/python/.venv/Scripts/python.exe -m flake8 --max-line-length=100 --extend-ignore=E203,W503 <files>`
  and black `--line-length 100` on the same files.
- `&` is FORBIDDEN in shell commands. Do NOT run restart scripts
  (`restart-py.ps1`, `restart-all.ps1`). Do NOT wait for services.
- Do NOT commit. Do NOT push. Leave the working tree dirty for orchestrator review.
- The full existing suite must stay green: run
  `.venv/Scripts/python.exe -m pytest tests/test_market_feed_loop.py tests/test_market_sessions.py -q`
  and also `tests/test_runtime.py tests/test_market_evidence.py` after your change.

## Definition of done

- [ ] `market/sessions.py` implemented exactly as specified above.
- [ ] `feed_loop.py` integrates session check (skip closed, fail-open, snapshot session).
- [ ] `/market/session` endpoint added.
- [ ] `tests/test_market_sessions.py` written and passing; existing feed tests green.
- [ ] flake8 + black clean on touched files.
- [ ] Report: files changed, exact test command + result counts, any deviation from spec.
