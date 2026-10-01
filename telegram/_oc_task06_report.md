# TASK 06 COMPLETION REPORT — MULTI-MT5 / ONE SIGNAL → MANY ACCOUNTS

```text
TASK: 06 — One canonical signal → N MT5 accounts (per-account broker
            normalization + per-account Risk Gate)
STATUS: PASS
```

## FILES CHANGED

New:

- `services/python/src/trading/canonical_signal.py` (new) — the immutable
  `CanonicalSignal` model (`signal_id, opportunity_id, symbol, direction,
  entry_reference, initial_SL, initial_TP, planned_RR, risk_policy,
  strategy_version, created_at, evidence_hash`), deterministic
  `signal_id_for(...)`, the `SignalStatus` vocabulary
  (`CREATED, VALIDATED, PARTIALLY_EXECUTED, EXECUTED_ALL, REJECTED_ALL,
  EXPIRED`) and the per-account `AccountExecutionStatus` vocabulary
  (`PENDING, APPROVED, REJECTED, SUBMITTING, SUBMITTED, FILLED, FAILED,
  RECONCILED, CLOSED`). Frozen dataclass — the signal can never be mutated.
- `services/python/src/execution/fanout.py` (new) — the fan-out coordinator:
  `CanonicalFanout.fan_out(signal, ...)` builds per-account context, applies
  broker normalization, runs the account-specific Risk Gate on the *final*
  normalized order, dispatches per account, and records outcomes in a
  `FanoutLedger` keyed by `(signal_id, account_id)`. Also `AccountDispatch`
  (per-account status) and the process-wide ledger registry.
- `services/python/tests/test_task06_canonical_fanout.py` (new) — 17 tests, one
  per STOP GATE 06 criterion (list below).

Modified:

- `services/python/src/orchestration/pipeline.py` — new optional
  `fanout_coordinator`; when wired, an approved proposal becomes ONE canonical
  signal (`_build_canonical_signal`) and is fanned out
  (`_dispatch_canonical_fanout`) instead of the single-terminal dispatch. New
  `PipelineResult` fields `canonical_signal`, `signal_id`, `fanout` (serialised
  in `to_dict`). The "execution engine not configured" guard is relaxed only
  when a coordinator is present (the coordinator owns per-account execution).
- `services/python/src/orchestration/runtime.py` — new
  `_build_fanout_coordinator(...)` + `_canonical_fanout_enabled()` +
  `_default_single_terminal_sender()`. The coordinator reuses the shared
  deterministic `RiskGate` and the real `mt5.terminals.get_fanout_targets()`
  (armed + eligible + running). Gated by the `canonical_fanout_enabled` live
  toggle, default **OFF**.

No code was deleted. Safety unchanged: **every terminal stays DISARMED by
default**; `CANONICAL_FANOUT_ENABLED` defaults to `false`.

## ROOT CAUSE

The repo already had multi-terminal arm/disarm infrastructure and a *raw*
fan-out (`ExecutionEngine.execute_order_fanout`) that re-attached per terminal
and sized lots per account, but it did **not** implement the TASK 06 trading
model:

1. There was **no canonical signal object** — no single immutable
   `signal_id` shared across accounts, and no fan-out status vocabulary.
2. The raw fan-out sent to every armed terminal **without any per-account Risk
   Gate** — an account could be dispatched without its own deterministic risk
   validation.
3. There was **no per-account ledger** and no dedupe by
   `(signal_id, account_id)`; the engine's idempotency key was a single global
   value, so a multi-account fan-out either collided (only one account sent) or
   could not prove a duplicate fan-out would not double-send.
4. **No mechanism guaranteed** that a rejected account does not spawn a second
   signal, or that an account cannot reach execution without the canonical
   signal.

## FIX

1. **Canonical signal (immutable).** `trading/canonical_signal.py` defines a
   frozen dataclass with exactly the required fields plus a deterministic
   `signal_id_for()` and an `evidence_hash`. The same opportunity identity always
   produces the same `signal_id` (dedupe by construction).
2. **Fan-out coordinator.** `execution/fanout.py` implements the exact per-
   account pipeline: *canonical signal → account context → broker normalization
   → account Risk Gate → execution*. The signal is passed through untouched; only
   account-specific values (resolved symbol, normalized volume, absolute
   entry/SL/TP) differ.
3. **Per-account Risk Gate.** The coordinator calls
   `risk_gate.validate_proposal(proposal, <that account's state>, <that
   account's positions>, market_info)` on the **final normalized order** and
   fails **closed** on any error. A rejection is recorded as `REJECTED` for that
   account only — no new signal is requested.
4. **Ledger + duplicate prevention.** `FanoutLedger` keys records by
   `(signal_id, account_id)`. A `(signal, account)` already terminal is skipped
   as a duplicate, and the per-account idempotency key is
   `f"{signal_id}:{account_id}"` — distinct per account (all N can send), stable
   per pair (a duplicate fan-out cannot double-send). `REJECTED_ALL` /
   `PARTIALLY_EXECUTED` / `EXECUTED_ALL` are rolled up from the per-account
   statuses.
5. **No bypass.** Every order the coordinator emits carries the canonical
   `signal_id` (idempotency key prefix + order comment), so no account order can
   exist without its signal.
6. **Wiring + safety.** The pipeline uses the coordinator instead of the single-
   terminal path when it is configured; the runtime builds it behind a live
   toggle that defaults **OFF** and reuses the real armed/eligible terminal
   targets. Real dispatch still flows through the engine's
   `execution_permitted()` armed gate, so LIVE stays DISARMED by default.

## TESTS

```text
command: .venv/Scripts/python.exe -m pytest tests/test_task06_canonical_fanout.py -v
         --basetemp="C:/Users/billy/AppData/Local/Temp/oc_t06_v" -p no:cacheprovider
result:  17 passed in 1.70s

  test_canonical_signal_is_immutable_and_has_all_fields ......... PASSED
  test_signal_id_is_deterministic_for_same_identity ............. PASSED
  test_two_demo_terminals_receive_same_signal_id ................ PASSED
  test_one_rejection_does_not_create_a_second_signal ............ PASSED
  test_one_event_creates_one_signal_id_duplicate_fanout_is_idempotent PASSED
  test_duplicate_fanout_cannot_duplicate_orders ................. PASSED
  test_per_account_risk_is_enforced_on_own_account_state ........ PASSED
  test_per_account_risk_gate_fails_closed_on_error .............. PASSED
  test_broker_normalization_is_per_account_signal_unchanged ..... PASSED
  test_no_account_can_bypass_the_canonical_signal ............... PASSED
  test_live_terminal_configurable_but_starts_disarmed ........... PASSED
  test_arm_is_explicit_and_required_for_fanout .................. PASSED
  test_pipeline_creates_one_signal_and_fans_out_to_accounts ..... PASSED
  test_pipeline_rejection_does_not_reanalyse .................... PASSED
  test_pipeline_without_coordinator_preserves_single_terminal_path PASSED
  test_all_rejected_rolls_up_to_rejected_all .................... PASSED
  test_real_engine_places_one_order_per_account_not_a_duplicate .. PASSED

command: .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
         --basetemp="C:/Users/billy/AppData/Local/Temp/oc_t06_full2"
result:  2997 passed, 1 warning in 69.11s

command: .venv/Scripts/black.exe --check <5 changed files>
result:  All done! 5 files would be left unchanged.

command: .venv/Scripts/flake8.exe --max-line-length=100 <5 changed files>
result:  (no output — clean)
```

## RUNTIME VERIFICATION

No blocking server was started (per the lesson). Verified by direct import and
process-state inspection (all commands < 60 s):

```text
$ .venv/Scripts/python.exe -c "import orchestration.runtime as rt; ..."
CANONICAL_FANOUT default: False
armed terminals default: []
fanout targets default: []
execution armed default: False
execution permitted default: False

$ CANONICAL_FANOUT_ENABLED=true python -c "_build_fanout_coordinator(...)"
env flag: True
coordinator built: CanonicalFanout
targets (no armed terminals): []      # fail-closed — nothing dispatched
no native order can be sent: targets empty = True
```

- The coordinator builds successfully and is OFF unless `CANONICAL_FANOUT_ENABLED`
  (or the `canonical_fanout_enabled` settings toggle) is explicitly enabled.
- With zero armed terminals it resolves **zero** targets → no dispatch (fail-
  closed), and `execution_permitted()` is `False`, so no native order can reach
  MT5 by default.
- The full suite (2996 pre-existing + 1 net new; 17 new TASK 06 tests) passes.

## STOP GATE 06

```text
[x] One event creates one signal_id
    → test_one_event_creates_one_signal_id_duplicate_fanout_is_idempotent:
      re-registering the same signal returns False; exactly one signal record.
[x] One supervisor analysis only
    → test_pipeline_creates_one_signal_and_fans_out_to_accounts /
      test_pipeline_rejection_does_not_reanalyse: supervisor.calls == 1.
[x] 2+ demo terminals receive the same signal_id
    → test_two_demo_terminals_receive_same_signal_id: both accounts' rows carry
      signal_id == "sig_S1".
[x] Live terminal can be configured but starts disarmed
    → test_live_terminal_configurable_but_starts_disarmed: execution_allowed
      True, armed False, no fan-out targets.
[x] Arm is explicit
    → test_arm_is_explicit_and_required_for_fanout: not a target until
      arm_terminal(id, True) is called.
[x] One account rejection does not create a second signal
    → test_one_rejection_does_not_create_a_second_signal: A/C executed, B
      REJECTED under the SAME signal_id; exactly one signal in the ledger.
[x] Per-account risk is enforced
    → test_per_account_risk_is_enforced_on_own_account_state (each account's own
      equity) + test_per_account_risk_gate_fails_closed_on_error (fail-closed).
[x] No account can bypass the canonical signal
    → test_no_account_can_bypass_the_canonical_signal: every emitted order key
      starts with "sig_S1:" and carries sig_S1 in its comment.
[x] Duplicate fan-out cannot duplicate orders
    → test_duplicate_fanout_cannot_duplicate_orders +
      test_real_engine_places_one_order_per_account_not_a_duplicate (real
      ExecutionEngine): second fan-out places 0 new orders.
```

## REMAINING ISSUES

- The coordinator's default execution sender is the shared `ExecutionEngine`
  (one armed+attached terminal per process, per the MT5 binding constraint).
  True simultaneous parallel submit across N live terminals (one binding per
  process) remains a later-phase concern; TASK 06 delivers the correct
  *model* (one signal, per-account normalization, per-account risk gate,
  dedupe, statuses) which is what the STOP GATE requires.
- `mt5_terminals.json` already ships `bil2` with `execution: true` and LIVE
  accounts (`vito1/vito2`) with `execution: false`; unchanged. LIVE accounts
  remain ineligible-by-config and, in any case, DISARMED by default.

## NEXT TASK

NOT STARTED (TASK 07 must not begin until this STOP GATE is accepted).
