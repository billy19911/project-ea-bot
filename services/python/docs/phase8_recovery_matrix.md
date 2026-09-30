# Phase 8 — Recovery Matrix

| Failure | Detection | Recovery | Safety Outcome |
|---|---|---|---|
| Process crash after broker submit | durable ledger UNKNOWN/SUBMITTING at boot (`run_execution_recovery`) | locator adopt on next pass; never blind-retry | one broker position |
| MT5 disconnect | health probe DEGRADED; data_source≠LIVE | reconnect → refresh spec/bid/ask/positions/account → reconcile; critical mismatch blocks new orders | safe |
| Provider outage | provider health errors; bounded fallback chain | fallback → UNKNOWN/WAIT; trading safety unaffected | safe |
| Storage corruption (partial/truncated JSONL) | JSONDecodeError skip per line | corrupt lines skipped, valid kept; partial last record never fabricated | safe |
| Duplicate event (close/review/trigger) | identity-keyed stores + claim_entry | idempotent ignore (exactly-once) | safe |
| Queue failure (research worker crash) | errors counter; drain isolation | restart/retry; poison swallowed; trading unaffected | safe |
| Stale/inverted market data | spread_known=False; freshness envelope | WAIT/BLOCK (never treated as fresh) | safe |
| Alert storm (1000 identical) | cooldown + suppressed_counts | history bounded; firing value refreshed | safe |
| Terminal setup after restart | lifecycle evaluate (INVALID/EXPIRED sticky) | no resurrection (safe discard) | safe |
| Budget exhaustion + outage | ledger reserve fails | optional AI stopped; deterministic safety intact | safe |
