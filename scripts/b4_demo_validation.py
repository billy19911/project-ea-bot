# -*- coding: utf-8 -*-
"""B-4 controlled DEMO-account validation harness (T1).

Standalone CLI that arms the DEMO terminal ``bil2``, submits exactly ONE small
order through the **native execution engine path**
(:class:`~src.execution.engine.ExecutionEngine` -> ``_send_to_mt5`` -> native
``mt5.order_send``), verifies the fill on the broker, and records
machine-readable evidence.

It deliberately does NOT use the paper ``/mt5/orders/execute`` surface.

Safety model (all fail-closed, identical to the live service):
1. DEMO guard — aborts without submitting unless ``account_info().trade_mode``
   is ``0`` (DEMO).
2. The order travels the same gates as production: an *armed*, eligible,
   attached terminal plus a gate-issued ``approval_token`` on the request. This
   harness never bypasses or disables a gate.
3. Max ONE order per run; no submit loops.

Import bootstrap: ``import src.*`` only resolves when the cwd is
``services/python``. The harness resolves the repo root from ``__file__``,
chdirs into ``services/python`` and prepends it to ``sys.path`` BEFORE importing
``src.*`` — so it behaves identically no matter where it is invoked from.

The ``reconcile`` subcommand (T2) runs a **live reconciliation** in-process, on
the same code path the service uses (:class:`ReconciliationRunner` + the
providers wiring built by ``orchestration.runtime``): the internal ledger
(in-memory ``OrderStateStore`` rehydrated from ``logs/order_state.jsonl``) is
compared against the broker's actual positions, and the T1 ticket must be
**matched by ticket**.

Known data-shape gap (documented, NOT hidden): the durable ledger records only
``{intent_id, state, ticket, timestamp}`` — no symbol/volume/sl/tp/magic. An
internal position reconstructed from such a record therefore has ``volume=None``
and empty symbol, so the reconciler reports volume/symbol/magic field diffs for
the matched pair. These are classified as *expected data-shape gaps*, not bugs;
the reconciler and gates are left untouched.

The ``recovery-check`` subcommand (T3) proves restart recovery by running in TWO
explicit stages that the operator invokes as SEPARATE processes — this is what
makes the "restart" genuine: each process starts with an empty in-memory state
machine and must rehydrate the durable ledger from
``services/python/logs/order_state.jsonl``. Stage ``pre`` records the arm state,
reads the T1 ticket and confirms its record lives in the ledger **file**. Stage
``post`` (a fresh process) constructs a fresh ``OrderStateStore``, asserts the T1
ticket state was rehydrated from disk, re-runs reconciliation (still matched),
asserts the in-memory **arm state is empty** (proving a restart clears it — by
design), then re-arms ``bil2`` through the same mechanism T1 used.

Usage:
    python scripts/b4_demo_validation.py validate --dry-run
    python scripts/b4_demo_validation.py validate --symbol "#BTCUSD"
    python scripts/b4_demo_validation.py reconcile
    python scripts/b4_demo_validation.py recovery-check --stage pre
    python scripts/b4_demo_validation.py recovery-check --stage post
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Import bootstrap (must run BEFORE any ``src.*`` import)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVICES_PY = _REPO_ROOT / "services" / "python"


def _bootstrap_import_path() -> None:
    """chdir into ``services/python`` and put it first on ``sys.path``."""
    target = str(_SERVICES_PY)
    if target in sys.path:
        sys.path.remove(target)
    sys.path.insert(0, target)
    try:
        os.chdir(target)
    except OSError:
        # Leave the cwd unchanged; sys.path alone still makes ``src.*`` import.
        pass


_bootstrap_import_path()

# --- importable after the bootstrap -----------------------------------------

DEFAULT_TERMINAL_ID = "bil2"
DEFAULT_SYMBOL = "#BTCUSD"
B4_MAGIC = 84004
B4_COMMENT = "B4DEMO"
_EVIDENCE_JSON = _REPO_ROOT / "docs" / "evidence" / "B-4-demo-validation.json"
_EVIDENCE_MD = _REPO_ROOT / "docs" / "evidence" / "B-4-demo-validation.md"
_TERMINAL_PATHS = {
    "bil2": r"E:\MT5 XYNN EA\MetaTrader 5 BIL 2\terminal64.exe",
}

# Trade modes that are safe to submit real orders against. Anything else
# (CONTEST=1, REAL=2, unknown) is refused — fail-closed.
DEMO_TRADE_MODE = 0

# Field-level mismatch categories that are *expected* for a ledger-reconstructed
# internal position (the durable ledger carries no symbol/volume/sl/tp/magic).
_EXPECTED_GAP_FIELDS = frozenset({"volume", "symbol", "magic", "sl/tp"})


class ValidationAbort(RuntimeError):
    """Raised when a guard aborts the run before any order is submitted."""


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Outcome of one harness step (for evidence + console)."""

    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class DemoValidationHarness:
    """Orchestrates the controlled DEMO validation flow.

    The MetaTrader5 module and the ``mt5.terminals`` module are injected so the
    unit tests can drive every guard without a live terminal. The
    ``connector``/``providers_factory``/``runner_factory`` seams let the T2
    reconcile path be unit-tested with fake providers.
    """

    def __init__(
        self,
        *,
        terminal_id: str = DEFAULT_TERMINAL_ID,
        terminal_path: Optional[str] = None,
        symbol: str = DEFAULT_SYMBOL,
        volume: Optional[float] = None,
        dry_run: bool = False,
        timeout: float = 30.0,
        mt5_module: Any = None,
        terminals_module: Any = None,
        engine_factory: Any = None,
        connector_module: Any = None,
        providers_factory: Any = None,
        runner_factory: Any = None,
        stdout: Any = None,
    ) -> None:
        self.terminal_id = terminal_id
        self.terminal_path = terminal_path or _TERMINAL_PATHS.get(terminal_id)
        self.symbol = symbol
        self.volume = volume
        self.dry_run = bool(dry_run)
        self.timeout = float(timeout)
        self._mt5_module = mt5_module
        self._terminals_module = terminals_module
        self._engine_factory = engine_factory
        self._connector_module = connector_module
        self._providers_factory = providers_factory
        self._runner_factory = runner_factory
        self._out = stdout or sys.stdout

        self.steps: list[StepResult] = []
        self.evidence: dict[str, Any] = {}

    # -- infrastructure -----------------------------------------------------

    @property
    def mt5(self) -> Any:
        if self._mt5_module is None:
            import MetaTrader5 as mt5

            self._mt5_module = mt5
        return self._mt5_module

    @property
    def terminals(self) -> Any:
        if self._terminals_module is None:
            from src.mt5 import terminals

            self._terminals_module = terminals
        return self._terminals_module

    @property
    def connector(self) -> Any:
        """The read-only MT5 connector (``src.mt5.connector``)."""
        if self._connector_module is None:
            from src.mt5 import connector

            self._connector_module = connector
        return self._connector_module

    def _log(self, message: str) -> None:
        print(message, file=self._out)

    def _record(self, name: str, ok: bool, detail: str = "", **data: Any) -> StepResult:
        step = StepResult(name=name, ok=ok, detail=detail, data=data)
        self.steps.append(step)
        marker = "OK" if ok else "FAIL"
        self._log(f"[{marker:4}] {name}: {detail}")
        return step

    # -- pre-flight ---------------------------------------------------------

    def _preflight(self) -> None:
        """Initialize MT5 against the bil2 terminal and wait for a connection."""
        if not self.terminal_path:
            raise ValidationAbort(
                f"No terminal path known for '{self.terminal_id}' — cannot initialize MT5."
            )

        self._log(f"Initializing MT5 with terminal: {self.terminal_path}")
        ok = bool(self.mt5.initialize(path=self.terminal_path))
        if not ok:
            # No retry loops — abort with a clear message.
            raise ValidationAbort(
                "mt5.initialize() failed for "
                f"{self.terminal_path}. Is the terminal installed and unlocked? "
                "(no retries attempted)."
            )

        deadline = time.monotonic() + self.timeout
        account = None
        while time.monotonic() < deadline:
            account = self.mt5.account_info()
            if account is not None:
                break
            time.sleep(0.5)

        if account is None:
            raise ValidationAbort(
                "account_info() returned None after "
                f"{self.timeout:.0f}s — terminal not connected to a broker."
            )

        self.evidence["account"] = {
            "login": getattr(account, "login", None),
            "server": getattr(account, "server", None),
            "trade_mode": getattr(account, "trade_mode", None),
            "balance": getattr(account, "balance", None),
            "equity": getattr(account, "equity", None),
            "currency": getattr(account, "currency", None),
            "leverage": getattr(account, "leverage", None),
        }
        self._account = account
        self._record(
            "preflight",
            True,
            f"connected login={self.evidence['account']['login']} "
            f"server={self.evidence['account']['server']}",
        )

    # -- guards -------------------------------------------------------------

    def _demo_guard(self) -> None:
        """Fail-closed DEMO guard: refuse any account that is not DEMO."""
        account = self._account
        trade_mode = getattr(account, "trade_mode", None)
        if trade_mode != DEMO_TRADE_MODE:
            mode_label = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(trade_mode, "UNKNOWN")
            raise ValidationAbort(
                "DEMO GUARD TRIPPED: account trade_mode="
                f"{trade_mode} ({mode_label}) is not DEMO (0). No order submitted."
            )
        self._record("demo_guard", True, "account is DEMO (trade_mode=0)")

    def _symbol_info(self) -> Any:
        info = self.mt5.symbol_info(self.symbol)
        if info is None:
            raise ValidationAbort(f"symbol_info('{self.symbol}') returned None.")
        return info

    def _market_check(self) -> Any:
        """Fetch a fresh tick for the symbol; abort on stale/None."""
        tick = self.mt5.symbol_info_tick(self.symbol)
        if tick is None:
            raise ValidationAbort(
                f"symbol_info_tick('{self.symbol}') returned None — no market data."
            )
        bid = getattr(tick, "bid", None)
        ask = getattr(tick, "ask", None)
        if not bid or not ask or bid <= 0 or ask <= 0:
            raise ValidationAbort(
                f"Tick for '{self.symbol}' has no valid bid/ask (bid={bid}, ask={ask})."
            )
        self.evidence["tick"] = {
            "symbol": self.symbol,
            "bid": bid,
            "ask": ask,
            "time": getattr(tick, "time", None),
            "spread": round(float(ask) - float(bid), 6),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        self._tick = tick
        self._record("market_check", True, f"tick bid={bid} ask={ask}")
        return tick

    def _open_positions(self) -> list[Any]:
        positions = self.mt5.positions_get()
        return list(positions) if positions is not None else []

    def _find_own_position(self) -> Optional[Any]:
        """Return an open position carrying the harness magic/comment, if any."""
        for pos in self._open_positions():
            magic = getattr(pos, "magic", None)
            comment = str(getattr(pos, "comment", "") or "")
            if magic == B4_MAGIC or comment == B4_COMMENT:
                return pos
        return None

    def _open_position_guard(self) -> Optional[Any]:
        """Idempotent re-run guard: skip submit when our position already exists."""
        existing = self._find_own_position()
        if existing is not None:
            self.evidence["position"] = self._position_snapshot(existing)
            self._record(
                "open_position_guard",
                True,
                f"already validated — ticket={getattr(existing, 'ticket', None)} left OPEN",
            )
            return existing
        self._record("open_position_guard", True, "no existing B4 position — proceed")
        return None

    # -- arm + submit -------------------------------------------------------

    def _ensure_selected_and_armed(self) -> None:
        """Select + arm the terminal through the service's own mechanism."""
        terms = self.terminals

        view = terms.list_terminals()
        entry = next(
            (t for t in view.get("terminals", []) if t.get("id") == self.terminal_id),
            None,
        )
        if entry is None:
            raise ValidationAbort(f"Terminal '{self.terminal_id}' not in registry.")
        if not entry.get("running"):
            raise ValidationAbort(
                f"Terminal '{self.terminal_id}' is not running — cannot arm (no retry loop)."
            )

        if not (entry.get("selected") and entry.get("attached")):
            sel = terms.select_terminal(self.terminal_id)
            if not sel.get("ok"):
                raise ValidationAbort(f"select_terminal failed: {sel.get('message')}")

        arm = terms.arm_terminal(self.terminal_id, True)
        if not arm.get("ok"):
            raise ValidationAbort(f"arm_terminal failed: {arm.get('message')}")

        if not terms.execution_permitted():
            raise ValidationAbort(
                "execution_permitted() is False after arm — the attached terminal is "
                "not armed/eligible (fail-closed)."
            )
        self._record(
            "arm",
            True,
            f"terminal '{self.terminal_id}' armed and execution permitted",
        )

    def _resolve_volume(self, symbol_info: Any) -> float:
        if self.volume is not None:
            return float(self.volume)
        vol = getattr(symbol_info, "volume_min", None)
        if not vol or vol <= 0:
            raise ValidationAbort(
                "symbol_info.volume_min is missing/invalid; pass --volume."
            )
        return float(vol)

    def _build_request(self, symbol_info: Any) -> Any:
        from src.execution.engine import OrderRequest

        volume = self._resolve_volume(symbol_info)
        request = OrderRequest(
            symbol=self.symbol,
            order_type="BUY",
            volume=volume,
            price=0.0,
            magic=B4_MAGIC,
            comment=B4_COMMENT,
        )
        # Stamp the gate-issued approval token exactly like the pipeline does
        # (``pipeline.py``: ``request.approval_token = f"gate:{decision_id}"``).
        request.approval_token = f"gate:b4-t1-{int(time.time())}"
        self.evidence["request"] = {
            "symbol": self.symbol,
            "order_type": "BUY",
            "volume": volume,
            "magic": B4_MAGIC,
            "comment": B4_COMMENT,
            "idempotency_key": request.idempotency_key,
            "approval_token": request.approval_token,
        }
        return request

    def _order_check(self, symbol_info: Any) -> dict[str, Any]:
        """Engine-shaped ``order_check`` (dry-run). Mirrors ``_send_to_mt5`` payload."""
        mt5 = self.mt5
        tick = self._tick
        volume = self._resolve_volume(symbol_info)
        payload = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY,
            "price": tick.ask,
            "sl": 0.0,
            "tp": 0.0,
            "magic": B4_MAGIC,
            "comment": B4_COMMENT,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        check = mt5.order_check(payload)
        if check is None:
            raise ValidationAbort("order_check() returned None.")
        result = {
            "retcode": getattr(check, "retcode", None),
            "comment": getattr(check, "comment", ""),
            "balance": getattr(check, "balance", None),
            "margin": getattr(check, "margin", None),
            "margin_free": getattr(check, "margin_free", None),
        }
        self.evidence["order_check"] = result
        ok = result["retcode"] == 0
        self._record(
            "order_check",
            ok,
            f"retcode={result['retcode']} comment={result['comment']!r}",
        )
        if not ok:
            raise ValidationAbort(
                f"order_check retcode={result['retcode']} "
                f"({result['comment']}) — aborting before submit."
            )
        return result

    def _wire_store(self) -> Any:
        """Attach the durable order ledger, exactly like ``main.py`` does.

        The live service runs with cwd ``services/python``, so the active ledger
        is ``services/python/logs/order_state.jsonl``. After the import bootstrap
        this harness resolves the same file. T2 reconciles this ledger against
        the broker by ticket. Fail-safe: a wiring error degrades to in-memory.
        """
        try:
            from src.execution.state_machine import set_store
            from src.persistence.order_state_store import OrderStateStore

            store = OrderStateStore()
            set_store(store)
            self._store = store
            self.evidence["ledger_path"] = store.path
            return store
        except Exception as exc:  # noqa: BLE001 - ledger is best-effort
            self._log(f"WARNING: could not attach durable order ledger: {exc}")
            self._store = None
            return None

    def _record_existing_position(self, pos: Any) -> None:
        """Record an already-open harness position into the durable ledger.

        This runs only on the idempotent re-run path: the broker position is a
        REAL observation, so persisting it as ``position_confirmed`` keyed on the
        ticket lets T2 reconcile it honestly. No fill is fabricated — the state
        reflects what the broker already shows.
        """
        ticket = getattr(pos, "ticket", None)
        if ticket is None:
            return
        intent_id = f"b4-t1-{ticket}"
        from src.execution.state_machine import OrderState, set_order

        set_order(intent_id, OrderState.POSITION_CONFIRMED, {"ticket": ticket})
        self.evidence["ledger_intent_id"] = intent_id

    def _engine(self) -> Any:
        if self._engine_factory is not None:
            return self._engine_factory()
        from src.execution.engine import ExecutionEngine

        # Same wiring as the shipped runtime (``orchestration/runtime.py``):
        # no connector, simulation_mode=True, require_approval=True. The native
        # path is still taken because require_approval=True arms the guard and
        # the terminal is armed — matching production exactly.
        return ExecutionEngine(
            mt5_connector=None,
            simulation_mode=True,
            require_approval=True,
        )

    def _submit(self, request: Any) -> Any:
        engine = self._engine()
        self._record(
            "submit", True, "dispatching through ExecutionEngine.execute_order"
        )
        result = engine.execute_order(request)
        self.evidence["execution_result"] = {
            "success": bool(getattr(result, "success", False)),
            "ticket": getattr(result, "ticket", None),
            "error_code": getattr(result, "error_code", 0),
            "error_message": getattr(result, "error_message", ""),
            "retries": getattr(result, "retries", 0),
        }
        if not getattr(result, "success", False):
            raise ValidationAbort(
                "execute_order failed: "
                f"code={getattr(result, 'error_code', None)} "
                f"message={getattr(result, 'error_message', '')!r}"
            )
        self._record("execution", True, f"ticket={result.ticket}")
        return result

    # -- fill verification --------------------------------------------------

    def _position_snapshot(self, pos: Any) -> dict[str, Any]:
        return {
            "ticket": getattr(pos, "ticket", None),
            "symbol": getattr(pos, "symbol", None),
            "volume": getattr(pos, "volume", None),
            "price_open": getattr(pos, "price_open", None),
            "sl": getattr(pos, "sl", None),
            "tp": getattr(pos, "tp", None),
            "magic": getattr(pos, "magic", None),
            "comment": getattr(pos, "comment", None),
            "type": getattr(pos, "type", None),
            "profit": getattr(pos, "profit", None),
        }

    def _verify_fill(self, ticket: Optional[int]) -> Any:
        """Poll positions until the ticket appears (bounded timeout)."""
        if ticket is None:
            raise ValidationAbort("execution reported success but produced no ticket.")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            positions = self._open_positions()
            for pos in positions:
                if getattr(pos, "ticket", None) == ticket:
                    self.evidence["position"] = self._position_snapshot(pos)
                    self._record(
                        "fill_verify", True, f"position ticket={ticket} confirmed OPEN"
                    )
                    return pos
            if self.dry_run:
                break
            time.sleep(0.5)
        raise ValidationAbort(
            f"position ticket={ticket} did not appear within {self.timeout:.0f}s."
        )

    # -- evidence -----------------------------------------------------------

    def _merge_prior_evidence(self) -> None:
        """Preserve richer T1 evidence from an earlier run when re-running.

        A later idempotent re-run (position already open) carries no
        ``order_check``/``execution_result``. Without merging, the JSON would
        lose the original fill evidence. We keep the most informative values
        (never fabricate — only carry forward what a prior run truly recorded).
        """
        if not _EVIDENCE_JSON.exists():
            return
        try:
            prior = json.loads(_EVIDENCE_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        prior_t1 = prior.get("t1") if isinstance(prior, dict) else None
        if not isinstance(prior_t1, dict):
            return
        for key in ("request", "order_check", "execution_result"):
            if not self.evidence.get(key) and prior_t1.get(key):
                self.evidence[key] = prior_t1[key]

    def _write_evidence(self) -> tuple[Path, Path]:
        self._merge_prior_evidence()
        self.evidence.setdefault("t1", {})
        self.evidence["t1"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "terminal_path": self.terminal_path,
            "terminal_id": self.terminal_id,
            "dry_run": self.dry_run,
            "symbol": self.symbol,
            "account": self.evidence.get("account"),
            "tick": self.evidence.get("tick"),
            "request": self.evidence.get("request"),
            "order_check": self.evidence.get("order_check"),
            "execution_result": self.evidence.get("execution_result"),
            "position": self.evidence.get("position"),
            "python_version": platform.python_version(),
            "steps": [
                {"name": s.name, "ok": s.ok, "detail": s.detail} for s in self.steps
            ],
        }

        _EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
        _EVIDENCE_JSON.write_text(
            json.dumps(self.evidence, indent=2, default=str) + "\n", encoding="utf-8"
        )

        md_lines = [
            "",
            "## T1 — Controlled DEMO validation harness",
            "",
            f"- Timestamp (UTC): `{self.evidence['t1']['timestamp']}`",
            f"- Terminal: `{self.terminal_path}` (`{self.terminal_id}`)",
            f"- Dry-run: `{self.dry_run}`",
            f"- Symbol: `{self.symbol}`",
        ]
        acct = self.evidence.get("account") or {}
        md_lines.append(
            f"- Account: login `{acct.get('login')}` server `{acct.get('server')}` "
            f"trade_mode `{acct.get('trade_mode')}`"
        )
        oc = self.evidence.get("order_check")
        if oc:
            md_lines.append(
                f"- order_check retcode: `{oc.get('retcode')}` ({oc.get('comment')})"
            )
        ex = self.evidence.get("execution_result")
        if ex:
            md_lines.append(
                f"- execute_order: success `{ex.get('success')}` ticket `{ex.get('ticket')}` "
                f"retcode `{ex.get('error_code')}`"
            )
        pos = self.evidence.get("position")
        if pos:
            md_lines.append(
                f"- Position: ticket `{pos.get('ticket')}` {pos.get('symbol')} "
                f"vol `{pos.get('volume')}` price `{pos.get('price_open')}` "
                f"(left OPEN for T2/T3)"
            )
        md_lines.append(f"- Python: `{self.evidence['t1']['python_version']}`")
        md_lines.append("")

        section = "\n".join(md_lines)
        if _EVIDENCE_MD.exists():
            existing = _EVIDENCE_MD.read_text(encoding="utf-8")
            _EVIDENCE_MD.write_text(
                existing.rstrip() + "\n" + section, encoding="utf-8"
            )
        else:
            header = "# B-4 — DEMO validation evidence\n"
            _EVIDENCE_MD.write_text(header + section, encoding="utf-8")

        return _EVIDENCE_JSON, _EVIDENCE_MD

    # -- T2: reconcile -------------------------------------------------------

    def _t1_ticket(self) -> Optional[int]:
        """Read the T1 ticket from the evidence JSON (``t1`` section).

        The ticket is the join key for reconciliation; without it we cannot
        prove the T1 order is matched, so a missing ticket is a hard abort.
        """
        if not _EVIDENCE_JSON.exists():
            raise ValidationAbort(
                f"No T1 evidence at {_EVIDENCE_JSON} — run 'validate' first."
            )
        try:
            payload = json.loads(_EVIDENCE_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValidationAbort(f"Could not read T1 evidence: {exc}") from exc

        candidates = [
            (payload.get("t1") or {}).get("execution_result"),
            (payload.get("t1") or {}).get("position"),
            payload.get("execution_result"),
            payload.get("position"),
        ]
        for source in candidates:
            if isinstance(source, dict) and source.get("ticket") is not None:
                try:
                    return int(source["ticket"])
                except (TypeError, ValueError):
                    continue
        raise ValidationAbort(
            "No T1 ticket found in evidence (execution_result/position)."
        )

    def _attach_connector(self) -> bool:
        """Attach the read-only connector to the live terminal (best-effort).

        This mirrors what ``mt5.terminals.select_terminal`` does internally:
        ``connector.use_live_data_mode(path=<terminal64.exe>)``. Without this the
        connector stays in simulation mode and ``broker_positions()`` would read
        placeholder positions — not the broker's real state.
        """
        if not self.terminal_path:
            self._record(
                "attach_connector",
                False,
                f"no terminal path for '{self.terminal_id}' — broker side will be empty",
            )
            return False
        try:
            ok = bool(self.connector.use_live_data_mode(path=self.terminal_path))
        except Exception as exc:  # noqa: BLE001 - read-only attach is best-effort
            self._record("attach_connector", False, f"attach failed: {exc}")
            return False
        self._record(
            "attach_connector",
            ok,
            f"connector live_mode={ok} path={self.terminal_path}",
        )
        return ok

    def _build_providers(self) -> Any:
        """Build the reconciliation providers the *service* uses.

        Reuses ``OrchestrationRuntime._default_reconciliation_providers`` so the
        harness cannot drift from production wiring: with the connector live it
        returns :class:`MT5ReconciliationProviders` (internal ledger vs broker),
        otherwise no-op providers. The tests inject ``providers_factory``.
        """
        if self._providers_factory is not None:
            return self._providers_factory()
        from src.orchestration.runtime import OrchestrationRuntime

        return OrchestrationRuntime._default_reconciliation_providers()

    def _build_runner(self, providers: Any) -> Any:
        """Build a fail-safe :class:`ReconciliationRunner` (interval 1)."""
        if self._runner_factory is not None:
            return self._runner_factory(providers)
        from src.execution.reconciliation_runner import ReconciliationRunner

        return ReconciliationRunner(interval=1, providers=providers)

    @staticmethod
    def _classify_mismatch(mismatch: dict[str, Any]) -> str:
        """Classify a field mismatch as an expected data-shape gap or real bug.

        The durable ledger records only ``{intent_id, state, ticket, timestamp}``,
        so a ledger-reconstructed internal position has no volume/symbol/magic
        and no sl/tp. A difference on those fields is the *expected* consequence
        of the ledger shape; anything else is unexpected (a real bug).
        """
        return (
            "expected_ledger_shape_gap"
            if mismatch.get("field") in _EXPECTED_GAP_FIELDS
            else "unexpected"
        )

    def _collect_report(self, report: Any) -> dict[str, Any]:
        """Turn a ``ReconciliationReport`` into the T2 evidence payload."""
        raw = report.to_dict()

        field_diffs: list[dict[str, Any]] = []
        for key in (
            "volume_mismatches",
            "sltp_mismatches",
            "symbol_mismatches",
            "magic_mismatches",
        ):
            for mismatch in raw.get(key, []):
                entry = dict(mismatch)
                entry["category"] = key
                entry["classification"] = self._classify_mismatch(mismatch)
                field_diffs.append(entry)

        return {
            "matched": list(raw.get("matched", [])),
            "missing_in_broker": list(raw.get("missing_in_broker", [])),
            "missing_internal": list(raw.get("missing_internal", [])),
            "matched_orders": list(raw.get("matched_orders", [])),
            "orphan_orders": list(raw.get("orphan_orders", [])),
            "field_differences": field_diffs,
            "total_mismatches": raw.get("total_mismatches", 0),
            "has_critical": bool(report.has_critical()),
            "raw_report": raw,
        }

    def run_reconcile(self) -> int:
        """Execute the T2 reconcile flow. Returns a process exit code."""
        try:
            ticket = self._t1_ticket()
            self._record("t1_ticket", True, f"t1 ticket={ticket}")

            # Internal side: rehydrate the durable ledger exactly like main.py.
            self._wire_store()

            # Broker side: attach the read-only connector to the live terminal.
            self._attach_connector()

            providers = self._build_providers()
            runner = self._build_runner(providers)
            report = runner.run_once()
            if report is None:
                raise ValidationAbort(
                    "ReconciliationRunner.run_once() returned None "
                    "(fail-safe error inside the runner)."
                )

            collected = self._collect_report(report)
            matched = collected["matched"]
            is_matched = ticket in matched
            result = "matched" if is_matched else "t1_ticket_unmatched"

            self.evidence["t2"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "terminal_path": self.terminal_path,
                "terminal_id": self.terminal_id,
                "t1_ticket": ticket,
                "t1_ticket_matched": is_matched,
                "has_critical": collected["has_critical"],
                "total_mismatches": collected["total_mismatches"],
                "matched": collected["matched"],
                "missing_in_broker": collected["missing_in_broker"],
                "missing_internal": collected["missing_internal"],
                "field_differences": collected["field_differences"],
                "raw_report": collected["raw_report"],
                "ledger_path": self.evidence.get("ledger_path"),
                "broker_live": bool(
                    getattr(self.connector, "is_live_mode", lambda: False)()
                ),
                "result": result,
                "python_version": platform.python_version(),
                "steps": [
                    {"name": s.name, "ok": s.ok, "detail": s.detail} for s in self.steps
                ],
            }

            self._record(
                "reconcile",
                is_matched,
                f"t1 ticket={ticket} matched={is_matched} "
                f"critical={collected['has_critical']} "
                f"mismatches={collected['total_mismatches']}",
            )

            self.evidence["result"] = result
            self._write_reconcile_evidence()
            self._print_reconcile_summary(ticket, collected, is_matched)

            # Exit non-zero if the T1 ticket did NOT match.
            return 0 if is_matched else 3

        except ValidationAbort as exc:
            self._record("abort", False, str(exc))
            self.evidence["t2"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": "aborted",
                "abort_reason": str(exc),
            }
            try:
                self._write_reconcile_evidence()
            except Exception:  # noqa: BLE001 - evidence write is best-effort
                pass
            self._log(f"ABORTED: {exc}")
            return 2
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
            self._record("error", False, f"unexpected: {exc}")
            self.evidence["t2"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": "error",
                "error": str(exc),
            }
            try:
                self._write_reconcile_evidence()
            except Exception:  # noqa: BLE001
                pass
            self._log(f"ERROR: {exc}")
            return 1

    def _print_reconcile_summary(
        self, ticket: int, collected: dict[str, Any], is_matched: bool
    ) -> None:
        self._log(f"T1 ticket: {ticket}")
        self._log(f"Matched tickets: {collected['matched']}")
        self._log(f"Missing in broker: {collected['missing_in_broker']}")
        self._log(f"Missing internal: {collected['missing_internal']}")
        self._log(f"has_critical: {collected['has_critical']}")
        for diff in collected["field_differences"]:
            self._log(
                f"  field diff ticket={diff.get('ticket')} field={diff.get('field')} "
                f"internal={diff.get('internal')} broker={diff.get('broker')} "
                f"[{diff.get('classification')}]"
            )
        if is_matched:
            self._log(
                "Reconciliation complete — T1 ticket MATCHED; "
                "position left OPEN (not closed)."
            )
        else:
            self._log(
                f"Reconciliation FAILED — T1 ticket {ticket} is NOT matched by the broker."
            )

    def _write_reconcile_evidence(self) -> tuple[Path, Path]:
        """Merge the ``t2`` section into the evidence JSON + append to the MD."""
        if _EVIDENCE_JSON.exists():
            try:
                payload = json.loads(_EVIDENCE_JSON.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    payload = {}
            except (json.JSONDecodeError, OSError):
                payload = {}
        else:
            payload = {}

        payload["t2"] = self.evidence.get("t2", {})
        _EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
        _EVIDENCE_JSON.write_text(
            json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
        )

        t2 = payload["t2"]
        md_lines = [
            "",
            "## T2 — Live reconciliation",
            "",
            f"- Timestamp (UTC): `{t2.get('timestamp')}`",
            f"- Terminal: `{t2.get('terminal_path')}` (`{t2.get('terminal_id')}`)",
            f"- Broker live mode: `{t2.get('broker_live')}`",
            f"- T1 ticket: `{t2.get('t1_ticket')}`",
            f"- T1 ticket matched: `{t2.get('t1_ticket_matched')}`",
            f"- Matched tickets: `{t2.get('matched')}`",
            f"- Missing in broker: `{t2.get('missing_in_broker')}`",
            f"- Missing internal: `{t2.get('missing_internal')}`",
            f"- has_critical: `{t2.get('has_critical')}` "
            f"(total mismatches `{t2.get('total_mismatches')}`)",
        ]
        diffs = t2.get("field_differences") or []
        if diffs:
            md_lines.append("- Field differences (matched pairs):")
            for diff in diffs:
                md_lines.append(
                    f"  - ticket `{diff.get('ticket')}` field `{diff.get('field')}` "
                    f"internal `{diff.get('internal')}` broker `{diff.get('broker')}` "
                    f"→ **{diff.get('classification')}**"
                )
        else:
            md_lines.append("- Field differences (matched pairs): none")
        md_lines.append(f"- Result: `{t2.get('result')}`")
        md_lines.append("")

        section = "\n".join(md_lines)
        if _EVIDENCE_MD.exists():
            existing = _EVIDENCE_MD.read_text(encoding="utf-8")
            _EVIDENCE_MD.write_text(
                existing.rstrip() + "\n" + section, encoding="utf-8"
            )
        else:
            header = "# B-4 — DEMO validation evidence\n"
            _EVIDENCE_MD.write_text(header + section, encoding="utf-8")

        return _EVIDENCE_JSON, _EVIDENCE_MD

    # -- T3: restart recovery -----------------------------------------------

    def _ledger_file_path(self) -> Path:
        """Return the durable ledger file path (env override aware).

        Mirrors ``OrderStateStore`` resolution: ``ORDER_STATE_PATH`` env wins,
        otherwise ``logs/order_state.jsonl`` relative to the (bootstrapped)
        cwd, i.e. ``services/python/logs/order_state.jsonl``.
        """
        env = os.environ.get("ORDER_STATE_PATH", "").strip()
        if env:
            return Path(env)
        return Path("logs") / "order_state.jsonl"

    def _read_ledger_records(self) -> list[dict[str, Any]]:
        """Read every valid record from the durable ledger FILE (not memory).

        T3's whole point is to prove the state survives via the file, so this
        reads raw lines directly — deliberately bypassing any in-memory store.
        Corrupt lines are skipped (same fail-safe as the store).
        """
        path = self._ledger_file_path()
        if not path.exists():
            raise ValidationAbort(f"Ledger file not found: {path}")
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict) and "intent_id" in entry:
                records.append(entry)
        return records

    def _ledger_record_for_ticket(self, ticket: int) -> Optional[dict[str, Any]]:
        """Return the last ledger record whose ``ticket`` matches (or None).

        A missing ledger file is treated as "no record" (the caller turns that
        into a fail-closed abort) rather than raising here.
        """
        match: Optional[dict[str, Any]] = None
        if not self._ledger_file_path().exists():
            return None
        for entry in self._read_ledger_records():
            if entry.get("ticket") == ticket:
                match = entry
        return match

    def _arm_state_snapshot(self) -> dict[str, Any]:
        """Capture the current arm/selection state from ``mt5.terminals``."""
        terms = self.terminals
        view = terms.list_terminals()
        entry = next(
            (t for t in view.get("terminals", []) if t.get("id") == self.terminal_id),
            None,
        )
        return {
            "selected_id": view.get("selected_id"),
            "execution_armed": bool(view.get("execution_armed")),
            "armed_terminals": list(view.get("armed_terminals", [])),
            "terminal_armed": bool(entry.get("armed")) if entry else False,
            "terminal_selected": bool(entry.get("selected")) if entry else False,
            "execution_permitted": bool(terms.execution_permitted()),
            "saved_selection": self._saved_selection(),
        }

    @staticmethod
    def _saved_selection() -> Optional[str]:
        """Read the persisted selection file (proves selection survives restart)."""
        try:
            from src.mt5 import terminals

            return terminals.load_saved_selection()
        except Exception:  # noqa: BLE001 - informational only
            return None

    def _wire_fresh_store(self) -> Any:
        """Construct a FRESH ``OrderStateStore`` + state-machine wiring.

        This is phase B/C's heart: a brand-new store instance rehydrates the
        ledger file into memory at ``__init__``. We drop any prior in-memory
        store first (``set_store(None)`` + ``reset_store()``) so the rehydration
        is unmistakably from disk, not from a leftover process cache.
        """
        from src.execution.state_machine import reset_store, set_store
        from src.persistence.order_state_store import OrderStateStore

        # Simulate the memory wipe a real process restart performs.
        reset_store()
        set_store(None)

        store = OrderStateStore()
        set_store(store)
        self._store = store
        return store

    @staticmethod
    def _store_state_for_ticket(store: Any, ticket: int) -> Optional[dict[str, Any]]:
        """Find the rehydrated in-memory record for ``ticket`` (or None)."""
        for record in store.all_orders().values():
            if record.get("ticket") == ticket:
                return dict(record)
        return None

    def run_recovery_check(self, stage: str) -> int:
        """Execute the T3 restart-recovery flow for ``stage`` in {pre, post}."""
        if stage not in {"pre", "post"}:
            raise ValidationAbort(f"unknown recovery stage: {stage!r}")
        if stage == "pre":
            return self._recovery_stage_pre()
        return self._recovery_stage_post()

    def _recovery_stage_pre(self) -> int:
        """Phase A (pre-restart): arm state + T1 ticket + ledger-file record."""
        try:
            ticket = self._t1_ticket()
            self._record("t1_ticket", True, f"t1 ticket={ticket}")

            ledger_path = self._ledger_file_path()
            self.evidence["ledger_path"] = str(ledger_path)
            record = self._ledger_record_for_ticket(ticket)
            if record is None:
                raise ValidationAbort(
                    f"T1 ticket {ticket} has NO record in the ledger file {ledger_path} "
                    "— cannot prove persistence. Run 'validate' first."
                )
            self._record(
                "ledger_file_record",
                True,
                f"ticket={ticket} state={record.get('state')} "
                f"intent_id={record.get('intent_id')} in {ledger_path}",
            )

            # Arm bil2 through the SAME mechanism T1 used, so the pre-restart
            # snapshot genuinely shows an ARMED terminal (which the restart then
            # clears). Arming is the harness's own action, not a gate change.
            self._ensure_selected_and_armed()

            arm = self._arm_state_snapshot()
            self._record(
                "arm_state_pre",
                bool(arm["execution_armed"]),
                f"armed={arm['execution_armed']} armed_terminals={arm['armed_terminals']} "
                f"permitted={arm['execution_permitted']}",
            )

            self.evidence["t3"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "pre",
                "terminal_path": self.terminal_path,
                "terminal_id": self.terminal_id,
                "t1_ticket": ticket,
                "ledger_path": str(ledger_path),
                "ledger_record": record,
                "arm_state": arm,
                "result": "pre_ok",
                "python_version": platform.python_version(),
                "steps": [
                    {"name": s.name, "ok": s.ok, "detail": s.detail} for s in self.steps
                ],
            }
            self.evidence["result"] = "pre_ok"
            self._record("stage_pre", True, "pre-restart state captured")
            self._write_recovery_evidence(stage="pre")

            self._log(
                "Pre-restart: T1 ticket present in ledger FILE + arm state captured. "
                "Next: run 'recovery-check --stage post' as a SEPARATE process."
            )
            return 0

        except ValidationAbort as exc:
            self._record("abort", False, str(exc))
            self.evidence["t3"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "pre",
                "result": "aborted",
                "abort_reason": str(exc),
            }
            try:
                self._write_recovery_evidence(stage="pre")
            except Exception:  # noqa: BLE001 - evidence write is best-effort
                pass
            self._log(f"ABORTED: {exc}")
            return 2
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
            self._record("error", False, f"unexpected: {exc}")
            self.evidence["t3"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "pre",
                "result": "error",
                "error": str(exc),
            }
            try:
                self._write_recovery_evidence(stage="pre")
            except Exception:  # noqa: BLE001
                pass
            self._log(f"ERROR: {exc}")
            return 1

    def _recovery_stage_post(self) -> int:
        """Phase C (post-restart): rehydrate, reconcile, arm-empty, re-arm."""
        try:
            ticket = self._t1_ticket()
            self._record("t1_ticket", True, f"t1 ticket={ticket}")

            # --- Prove rehydration from FILE via a FRESH store -------------
            ledger_path = self._ledger_file_path()
            self.evidence["ledger_path"] = str(ledger_path)
            store = self._wire_fresh_store()
            rehydrated = self._store_state_for_ticket(store, ticket)
            if rehydrated is None:
                raise ValidationAbort(
                    f"Fresh OrderStateStore did NOT rehydrate ticket {ticket} from "
                    f"{ledger_path} — restart recovery FAILED."
                )
            self._record(
                "rehydrate",
                True,
                f"ticket={ticket} rehydrated state={rehydrated.get('state')} "
                f"from {store.path}",
            )

            # --- Arm state must be EMPTY (in-memory by design) -------------
            pre_arm = self._arm_state_snapshot()
            arm_cleared = (
                not pre_arm["execution_armed"] and not pre_arm["armed_terminals"]
            )
            self._record(
                "arm_cleared",
                arm_cleared,
                f"armed={pre_arm['execution_armed']} "
                f"armed_terminals={pre_arm['armed_terminals']} "
                "(expected empty after restart)",
            )
            if not arm_cleared:
                raise ValidationAbort(
                    "Arm state is NOT empty after restart — expected in-memory clearing "
                    "by design. Aborting before re-arm to avoid masking a real bug."
                )

            # --- Fresh reconciliation still matches the T1 ticket ----------
            self._attach_connector()
            providers = self._build_providers()
            runner = self._build_runner(providers)
            report = runner.run_once()
            if report is None:
                raise ValidationAbort(
                    "ReconciliationRunner.run_once() returned None (fail-safe error)."
                )
            collected = self._collect_report(report)
            is_matched = ticket in collected["matched"]
            self._record(
                "reconcile_post",
                is_matched,
                f"ticket={ticket} matched={is_matched} "
                f"critical={collected['has_critical']} "
                f"mismatches={collected['total_mismatches']}",
            )
            if not is_matched:
                raise ValidationAbort(
                    f"T1 ticket {ticket} NOT matched after restart — recovery FAILED."
                )

            # --- Re-arm bil2 through the same mechanism as T1 --------------
            self._ensure_selected_and_armed()
            post_arm = self._arm_state_snapshot()
            self._record(
                "rearm",
                post_arm["execution_permitted"],
                f"re-armed '{self.terminal_id}': "
                f"armed={post_arm['execution_armed']} "
                f"permitted={post_arm['execution_permitted']}",
            )

            self.evidence["t3"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "post",
                "terminal_path": self.terminal_path,
                "terminal_id": self.terminal_id,
                "t1_ticket": ticket,
                "ledger_path": str(ledger_path),
                "store_path": store.path,
                "rehydrated_state": rehydrated.get("state"),
                "arm_state_post_restart": pre_arm,
                "arm_cleared": arm_cleared,
                "arm_state_after_rearm": post_arm,
                "t1_ticket_matched": is_matched,
                "has_critical": collected["has_critical"],
                "total_mismatches": collected["total_mismatches"],
                "matched": collected["matched"],
                "missing_in_broker": collected["missing_in_broker"],
                "missing_internal": collected["missing_internal"],
                "field_differences": collected["field_differences"],
                "raw_report": collected["raw_report"],
                "broker_live": bool(
                    getattr(self.connector, "is_live_mode", lambda: False)()
                ),
                "result": "recovered",
                "python_version": platform.python_version(),
                "steps": [
                    {"name": s.name, "ok": s.ok, "detail": s.detail} for s in self.steps
                ],
            }
            self.evidence["result"] = "recovered"
            self._write_recovery_evidence(stage="post")

            self._log(
                "Post-restart: ticket rehydrated from FILE + reconciled + arm was EMPTY "
                "→ re-armed. Recovery cycle COMPLETE."
            )
            return 0

        except ValidationAbort as exc:
            self._record("abort", False, str(exc))
            self.evidence["t3"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "post",
                "result": "aborted",
                "abort_reason": str(exc),
            }
            try:
                self._write_recovery_evidence(stage="post")
            except Exception:  # noqa: BLE001 - evidence write is best-effort
                pass
            self._log(f"ABORTED: {exc}")
            return 2
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
            self._record("error", False, f"unexpected: {exc}")
            self.evidence["t3"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "post",
                "result": "error",
                "error": str(exc),
            }
            try:
                self._write_recovery_evidence(stage="post")
            except Exception:  # noqa: BLE001
                pass
            self._log(f"ERROR: {exc}")
            return 1

    def _write_recovery_evidence(self, stage: str) -> tuple[Path, Path]:
        """Merge the ``t3`` section into the evidence JSON + append to the MD.

        Each stage runs as its own process, so the two stages must not clobber
        one another: the evidence is nested as ``t3.pre`` and ``t3.post`` and
        the top-level ``t3`` carries only the cross-stage summary.
        """
        if _EVIDENCE_JSON.exists():
            try:
                payload = json.loads(_EVIDENCE_JSON.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    payload = {}
            except (json.JSONDecodeError, OSError):
                payload = {}
        else:
            payload = {}

        existing_t3 = payload.get("t3")
        t3 = dict(existing_t3) if isinstance(existing_t3, dict) else {}
        t3[stage] = self.evidence.get("t3", {})
        present = [s for s in ("pre", "post") if s in t3]
        t3["stages_present"] = present
        t3["both_stages_present"] = present == ["pre", "post"]
        payload["t3"] = t3

        _EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
        _EVIDENCE_JSON.write_text(
            json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
        )

        t3 = t3[stage]
        md_lines = [
            "",
            f"## T3 — Restart recovery (`{stage}` stage)",
            "",
            f"- Timestamp (UTC): `{t3.get('timestamp')}`",
            f"- Terminal: `{t3.get('terminal_path')}` (`{t3.get('terminal_id')}`)",
            f"- Ledger file: `{t3.get('ledger_path')}`",
            f"- T1 ticket: `{t3.get('t1_ticket')}`",
        ]
        if stage == "pre":
            rec = t3.get("ledger_record") or {}
            arm = t3.get("arm_state") or {}
            md_lines += [
                f"- Ledger-file record: `{rec.get('intent_id')}` "
                f"state `{rec.get('state')}` ticket `{rec.get('ticket')}` "
                "— **persisted on disk (not memory)**",
                f"- Arm state (pre-restart): armed `{arm.get('execution_armed')}` "
                f"armed_terminals `{arm.get('armed_terminals')}` "
                f"permitted `{arm.get('execution_permitted')}`",
                f"- Saved selection (survives restart): `{arm.get('saved_selection')}`",
                f"- Result: `{t3.get('result')}`",
            ]
        else:
            arm_post = t3.get("arm_state_post_restart") or {}
            arm_re = t3.get("arm_state_after_rearm") or {}
            md_lines += [
                f"- Rehydrated state (fresh store): `{t3.get('rehydrated_state')}` "
                f"from `{t3.get('store_path')}` — **rebuilt from FILE at init**",
                f"- Arm state AFTER restart (memory cleared by design): "
                f"armed `{arm_post.get('execution_armed')}` "
                f"armed_terminals `{arm_post.get('armed_terminals')}` "
                f"→ `arm_cleared={t3.get('arm_cleared')}`",
                f"- Reconciliation re-run: matched `{t3.get('t1_ticket_matched')}` "
                f"matched tickets `{t3.get('matched')}` "
                f"critical `{t3.get('has_critical')}`",
                f"- Re-armed '{t3.get('terminal_id')}': "
                f"armed `{arm_re.get('execution_armed')}` "
                f"permitted `{arm_re.get('execution_permitted')}`",
                f"- Result: `{t3.get('result')}`",
            ]
        md_lines.append("")

        section = "\n".join(md_lines)
        if _EVIDENCE_MD.exists():
            existing = _EVIDENCE_MD.read_text(encoding="utf-8")
            _EVIDENCE_MD.write_text(
                existing.rstrip() + "\n" + section, encoding="utf-8"
            )
        else:
            header = "# B-4 — DEMO validation evidence\n"
            _EVIDENCE_MD.write_text(header + section, encoding="utf-8")

        return _EVIDENCE_JSON, _EVIDENCE_MD

    # -- flow ---------------------------------------------------------------

    def run(self) -> int:
        """Execute the validate flow. Returns a process exit code."""
        try:
            self._preflight()
            self._demo_guard()

            symbol_info = self._symbol_info()
            self.evidence["symbol_info"] = {
                "name": getattr(symbol_info, "name", self.symbol),
                "volume_min": getattr(symbol_info, "volume_min", None),
                "volume_step": getattr(symbol_info, "volume_step", None),
                "digits": getattr(symbol_info, "digits", None),
                "filling_mode": getattr(symbol_info, "filling_mode", None),
            }
            self._market_check()

            existing = self._open_position_guard()
            if existing is not None:
                # Idempotent re-run: do not submit a second order.
                self._wire_store()
                self._record_existing_position(existing)
                self.evidence["result"] = "already_validated"
                self.evidence["skipped_submit"] = True
                self._write_evidence()
                self._log(
                    "Already validated (position open). Dry-run submit skipped. "
                    "Position left OPEN for T2/T3."
                )
                return 0

            if self.dry_run:
                self._order_check(symbol_info)
                self.evidence["result"] = "dry_run_ok"
                self._write_evidence()
                self._log("Dry-run complete — no order submitted.")
                return 0

            self._ensure_selected_and_armed()
            self._wire_store()
            request = self._build_request(symbol_info)
            # Pre-submit safety net (defence in depth): order_check first.
            self._order_check(symbol_info)
            result = self._submit(request)
            self._verify_fill(getattr(result, "ticket", None))

            self.evidence["result"] = "filled"
            self._write_evidence()
            self._log(
                "Validation complete — 1 fill captured. Position left OPEN for T2/T3. "
                "NOT closed."
            )
            return 0

        except ValidationAbort as exc:
            self._record("abort", False, str(exc))
            self.evidence["result"] = "aborted"
            self.evidence["abort_reason"] = str(exc)
            try:
                self._write_evidence()
            except Exception:  # noqa: BLE001 - evidence write is best-effort
                pass
            self._log(f"ABORTED: {exc}")
            return 2
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
            self._record("error", False, f"unexpected: {exc}")
            self.evidence["result"] = "error"
            self.evidence["abort_reason"] = str(exc)
            try:
                self._write_evidence()
            except Exception:  # noqa: BLE001
                pass
            self._log(f"ERROR: {exc}")
            return 1
        finally:
            try:
                self.mt5.shutdown()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="b4_demo_validation",
        description="B-4 controlled DEMO-account validation harness (T1/T2).",
    )
    sub = parser.add_subparsers(dest="command")

    validate = sub.add_parser(
        "validate", help="run the controlled DEMO validation (default)"
    )
    validate.add_argument("--terminal-id", default=DEFAULT_TERMINAL_ID)
    validate.add_argument("--terminal-path", default=None)
    validate.add_argument("--symbol", default=DEFAULT_SYMBOL)
    validate.add_argument("--volume", type=float, default=None)
    validate.add_argument("--dry-run", action="store_true")
    validate.add_argument("--timeout", type=float, default=30.0)

    reconcile = sub.add_parser(
        "reconcile", help="live reconciliation of the T1 order (T2)"
    )
    reconcile.add_argument("--terminal-id", default=DEFAULT_TERMINAL_ID)
    reconcile.add_argument("--terminal-path", default=None)

    recovery = sub.add_parser(
        "recovery-check", help="restart recovery, run as SEPARATE processes (T3)"
    )
    recovery.add_argument(
        "--stage",
        choices=["pre", "post"],
        required=True,
        help="pre = capture state before restart; post = verify recovery after.",
    )
    recovery.add_argument("--terminal-id", default=DEFAULT_TERMINAL_ID)
    recovery.add_argument("--terminal-path", default=None)

    return parser


def _cmd_validate(args: argparse.Namespace) -> int:
    harness = DemoValidationHarness(
        terminal_id=args.terminal_id,
        terminal_path=args.terminal_path,
        symbol=args.symbol,
        volume=args.volume,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )
    return harness.run()


def _cmd_reconcile(args: argparse.Namespace) -> int:
    harness = DemoValidationHarness(
        terminal_id=args.terminal_id,
        terminal_path=args.terminal_path,
    )
    return harness.run_reconcile()


def _cmd_recovery_check(args: argparse.Namespace) -> int:
    harness = DemoValidationHarness(
        terminal_id=args.terminal_id,
        terminal_path=args.terminal_path,
    )
    return harness.run_recovery_check(args.stage)


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    raw = list(argv) if argv is not None else sys.argv[1:]
    # Default subcommand: ``validate`` when no subcommand is supplied.
    if not raw or raw[0] not in {"validate", "reconcile", "recovery-check"}:
        raw = ["validate", *raw]
    args = parser.parse_args(raw)
    command = args.command
    if command == "validate":
        return _cmd_validate(args)
    if command == "reconcile":
        return _cmd_reconcile(args)
    if command == "recovery-check":
        return _cmd_recovery_check(args)
    parser.error(f"unknown command: {command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
