# -*- coding: utf-8 -*-
"""Canonical-signal fan-out coordinator (TASK 06).

The coordinator takes ONE immutable :class:`~trading.canonical_signal.CanonicalSignal`
and fans it out to N eligible MT5 accounts. For every eligible terminal it:

1. builds the **account-specific context** (that account's equity / positions),
2. performs **broker normalization** (symbol resolution, digits/point, min/max/
   step, price normalization) — producing an account-specific absolute order,
3. runs an **account-specific Risk Gate** on the *final* normalized order,
4. dispatches to that terminal (only when armed) and records the outcome.

The signal itself is NEVER modified. Only account-specific values differ.

Critical guarantees proven by the tests:

- one event → one ``signal_id`` (dedupe by id),
- one supervisor/analysis only — a rejected account does NOT ask for a new
  signal; it is simply recorded as ``REJECTED`` under the same ``signal_id``,
- the ledger is keyed by ``(signal_id, account_id)`` so a *duplicate* fan-out of
  the same signal can never place a second order on the same account,
- an account can never bypass the canonical signal — the coordinator is the
  only path that emits account orders and it always carries the ``signal_id``.

The module is stdlib-only in its data structures and takes its collaborators
(risk gate, execution engine, terminal resolver, account reader) by injection so
it is fully unit-testable without a real MT5 terminal.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from trading.canonical_signal import (
    ACCOUNT_STATUSES,
    TERMINAL_STATUSES,
    AccountExecutionStatus,
    CanonicalSignal,
    SignalStatus,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AccountDispatch",
    "FanoutLedger",
    "CanonicalFanout",
    "get_fanout_ledger",
    "set_fanout_ledger",
    "reset_fanout_ledger",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AccountDispatch:
    """Mutable per-account dispatch record for ONE canonical signal.

    ``signal_id`` is copied verbatim from the canonical signal — it is never
    re-derived per account.
    """

    signal_id: str
    account_id: str
    terminal_id: str
    environment: str = "DEMO"  # DEMO | LIVE
    status: str = AccountExecutionStatus.PENDING
    reason: str = ""
    symbol: str = ""
    volume: float = 0.0
    price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    ticket: Any = None
    normalized: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=_now_iso)

    def set_status(self, status: str, reason: str = "") -> None:
        if status not in ACCOUNT_STATUSES:
            raise ValueError(f"Unknown account status: {status}")
        self.status = status
        if reason:
            self.reason = reason
        self.updated_at = _now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "account_id": self.account_id,
            "terminal_id": self.terminal_id,
            "environment": self.environment,
            "status": self.status,
            "reason": self.reason,
            "symbol": self.symbol,
            "volume": self.volume,
            "price": self.price,
            "sl": self.sl,
            "tp": self.tp,
            "ticket": self.ticket,
            "normalized": dict(self.normalized),
            "updated_at": self.updated_at,
        }


class FanoutLedger:
    """In-memory, thread-safe ledger of canonical signals + account dispatches.

    Keyed by ``signal_id`` → ``account_id`` so a signal's fan-out across accounts
    is queryable and a repeated fan-out cannot create a duplicate order for an
    already-terminal ``(signal_id, account_id)`` pair.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # signal_id -> {"signal": CanonicalSignal, "signal_status": str,
        #               "accounts": {account_id: AccountDispatch}}
        self._signals: dict[str, dict[str, Any]] = {}

    # -- signal registration ------------------------------------------------
    def register_signal(self, signal: CanonicalSignal) -> bool:
        """Register a canonical signal. Idempotent by ``signal_id``.

        Returns True when newly created, False when the id already exists (a
        duplicate event must NOT create a second signal record).
        """
        with self._lock:
            if signal.signal_id in self._signals:
                return False
            self._signals[signal.signal_id] = {
                "signal": signal,
                "signal_status": SignalStatus.CREATED,
                "accounts": {},
            }
            return True

    def has_signal(self, signal_id: str) -> bool:
        with self._lock:
            return signal_id in self._signals

    def get_signal(self, signal_id: str) -> Optional[CanonicalSignal]:
        with self._lock:
            entry = self._signals.get(signal_id)
            return entry["signal"] if entry else None

    # -- account dispatch ---------------------------------------------------
    def get_account_dispatch(self, signal_id: str, account_id: str) -> Optional[AccountDispatch]:
        with self._lock:
            entry = self._signals.get(signal_id)
            if not entry:
                return None
            return entry["accounts"].get(account_id)

    def upsert_account_dispatch(self, dispatch: AccountDispatch) -> AccountDispatch:
        with self._lock:
            entry = self._signals.get(dispatch.signal_id)
            if entry is None:
                raise KeyError(f"signal_id not registered: {dispatch.signal_id}")
            entry["accounts"][dispatch.account_id] = dispatch
            self._rollup_status_locked(dispatch.signal_id)
            return dispatch

    def is_terminal(self, signal_id: str, account_id: str) -> bool:
        """True when this (signal, account) already reached a terminal state.

        A duplicate fan-out must not re-dispatch a terminal account.
        """
        d = self.get_account_dispatch(signal_id, account_id)
        return bool(d and d.status in TERMINAL_STATUSES)

    # -- aggregate rollup ---------------------------------------------------
    def _rollup_status_locked(self, signal_id: str) -> str:
        entry = self._signals[signal_id]
        accounts = entry["accounts"]
        if not accounts:
            entry["signal_status"] = SignalStatus.VALIDATED
            return entry["signal_status"]
        executed = [d for d in accounts.values() if d.status in _EXECUTED_STATUSES]
        rejected = [d for d in accounts.values() if d.status == AccountExecutionStatus.REJECTED]
        failed = [d for d in accounts.values() if d.status == AccountExecutionStatus.FAILED]
        if executed and len(executed) == len(accounts):
            entry["signal_status"] = SignalStatus.EXECUTED_ALL
        elif executed:
            entry["signal_status"] = SignalStatus.PARTIALLY_EXECUTED
        elif rejected or failed:
            if len(rejected) + len(failed) == len(accounts):
                entry["signal_status"] = SignalStatus.REJECTED_ALL
            else:
                entry["signal_status"] = SignalStatus.PARTIALLY_EXECUTED
        else:
            entry["signal_status"] = SignalStatus.VALIDATED
        return entry["signal_status"]

    def signal_status(self, signal_id: str) -> Optional[str]:
        with self._lock:
            entry = self._signals.get(signal_id)
            return entry["signal_status"] if entry else None

    def set_signal_status(self, signal_id: str, status: str) -> None:
        if status not in (SignalStatus.CREATED, SignalStatus.EXPIRED):
            raise ValueError(f"Only CREATED/EXPIRED may be set directly: {status}")
        with self._lock:
            entry = self._signals.get(signal_id)
            if entry is not None:
                entry["signal_status"] = status

    def snapshot(self, signal_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            entry = self._signals.get(signal_id)
            if entry is None:
                return None
            return {
                "signal": entry["signal"].to_dict(),
                "signal_status": entry["signal_status"],
                "accounts": {aid: d.to_dict() for aid, d in entry["accounts"].items()},
            }

    def all_signals(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "signal_id": sid,
                    "signal_status": entry["signal_status"],
                    "account_count": len(entry["accounts"]),
                }
                for sid, entry in self._signals.items()
            ]

    def reset(self) -> None:
        with self._lock:
            self._signals.clear()


#: Per-account statuses that count as executed for the rollup.
_EXECUTED_STATUSES = frozenset(
    {
        AccountExecutionStatus.FILLED,
        AccountExecutionStatus.SUBMITTED,
        AccountExecutionStatus.RECONCILED,
        AccountExecutionStatus.CLOSED,
    }
)

# -- process-wide ledger registry --------------------------------------------
_LEDGER: Optional[FanoutLedger] = None
_LEDGER_LOCK = threading.Lock()


def get_fanout_ledger() -> FanoutLedger:
    """Return the process-wide fan-out ledger (creating it on demand)."""
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            _LEDGER = FanoutLedger()
        return _LEDGER


def set_fanout_ledger(ledger: Optional[FanoutLedger]) -> None:
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = ledger


def reset_fanout_ledger() -> None:
    """Clear the process-wide ledger (used by tests / restarts)."""
    set_fanout_ledger(FanoutLedger())


@dataclass
class _AccountContext:
    """Account-specific context resolved before normalization."""

    account_id: str
    terminal_id: str
    environment: str
    equity: float
    position_count: int
    account_state: dict[str, Any]


class CanonicalFanout:
    """Fan ONE canonical signal out to N eligible accounts.

    Collaborators (all injectable for tests; sensible production defaults):

    Args:
        execution_engine: Engine exposing ``execute_order(request)`` (single
            terminal send). Used to actually place each account's order.
        risk_gate: Object exposing ``validate_proposal(proposal, account_state,
            current_positions, market_info) -> GateDecision``. When None, the
            per-account risk gate is a no-op *approve* (callers that need risk
            enforcement MUST inject one).
        targets_provider: Zero-arg callable returning the eligible terminal
            entries (``mt5.terminals.get_fanout_targets``). Each entry must carry
            ``id`` + ``account`` (``{login, mode, equity}``).
        order_builder: Object exposing ``build_order_request(proposal, quote)``.
        account_state_provider: ``(terminal_entry) -> dict`` returning the
            account_state for the risk gate (equity/balance/used_margin/...).
        positions_provider: ``(terminal_entry) -> list`` of open positions.
        market_info_provider: ``(symbol, terminal_entry) -> dict`` with
            ``spread_pips`` / ``point_value`` / ``contract_size``.
        symbol_resolver: ``(symbol, terminal_entry) -> normalized symbol``.
        ledger: The :class:`FanoutLedger` (defaults to the process-wide one).
    """

    def __init__(
        self,
        execution_engine: Any = None,
        risk_gate: Any = None,
        targets_provider: Optional[Callable[[], list[dict[str, Any]]]] = None,
        order_builder: Any = None,
        account_state_provider: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
        positions_provider: Optional[Callable[[dict[str, Any]], list[dict[str, Any]]]] = None,
        market_info_provider: Optional[Callable[[str, dict[str, Any]], dict[str, Any]]] = None,
        symbol_resolver: Optional[Callable[[str, dict[str, Any]], str]] = None,
        ledger: Optional[FanoutLedger] = None,
    ) -> None:
        self.execution_engine = execution_engine
        self.risk_gate = risk_gate
        self.targets_provider = targets_provider
        self.order_builder = order_builder
        self.account_state_provider = account_state_provider
        self.positions_provider = positions_provider
        self.market_info_provider = market_info_provider
        self.symbol_resolver = symbol_resolver
        self.ledger = ledger or get_fanout_ledger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fan_out(
        self,
        signal: CanonicalSignal,
        *,
        targets: Optional[list[dict[str, Any]]] = None,
        raw_proposal: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Fan ``signal`` out to every eligible target account.

        Returns a summary dict::

            {"signal_id", "signal_status", "accounts": [<dispatch dicts>],
             "target_count", "executed", "rejected", "failed", "duplicates"}

        Guarantees:
        - ``signal`` is registered once (idempotent by ``signal_id``); a second
          call with the same signal does not create a second signal record.
        - a ``(signal_id, account_id)`` already in a terminal state is skipped as
          a *duplicate* — no second order is placed.
        - a rejection on one account is recorded as REJECTED for that account
          only; it never triggers a new signal.
        """
        self.ledger.register_signal(signal)

        if targets is None:
            targets = self._resolve_targets()

        executed = rejected = failed = duplicates = 0
        rows: list[dict[str, Any]] = []

        for target in targets or []:
            account_id = self._account_id_for(target)
            if not account_id:
                # Cannot attribute a per-account decision → skip (fail-closed).
                continue

            # Duplicate fan-out guard: a terminal (signal, account) never re-sends.
            if self.ledger.is_terminal(signal.signal_id, account_id):
                duplicates += 1
                existing = self.ledger.get_account_dispatch(signal.signal_id, account_id)
                rows.append(
                    existing.to_dict()
                    if existing
                    else {"account_id": account_id, "duplicate": True}
                )
                continue

            dispatch = AccountDispatch(
                signal_id=signal.signal_id,
                account_id=account_id,
                terminal_id=str(target.get("id") or ""),
                environment=str(self._account_mode(target)),
            )
            self.ledger.upsert_account_dispatch(dispatch)

            try:
                self._process_account(signal, target, dispatch, raw_proposal)
            except Exception as exc:  # noqa: BLE001 - one account must not abort others
                logger.warning("Fan-out account %s failed: %s", account_id, exc)
                dispatch.set_status(AccountExecutionStatus.FAILED, str(exc)[:200])

            # Re-upsert so the aggregate signal_status reflects the FINAL
            # per-account status (REJECTED/FILLED/FAILED), not the PENDING
            # placeholder registered before processing.
            self.ledger.upsert_account_dispatch(dispatch)

            if dispatch.status in _EXECUTED_STATUSES:
                executed += 1
            elif dispatch.status == AccountExecutionStatus.REJECTED:
                rejected += 1
            elif dispatch.status == AccountExecutionStatus.FAILED:
                failed += 1
            rows.append(dispatch.to_dict())

        signal_status = self.ledger.signal_status(signal.signal_id) or SignalStatus.VALIDATED
        return {
            "signal_id": signal.signal_id,
            "signal_status": signal_status,
            "accounts": rows,
            "target_count": len(rows),
            "executed": executed,
            "rejected": rejected,
            "failed": failed,
            "duplicates": duplicates,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _resolve_targets(self) -> list[dict[str, Any]]:
        if self.targets_provider is None:
            return []
        try:
            return list(self.targets_provider() or [])
        except Exception as exc:  # noqa: BLE001 - fail-closed to no targets
            logger.warning("Fan-out target resolution failed: %s", exc)
            return []

    @staticmethod
    def _account_id_for(target: dict[str, Any]) -> str:
        """Resolve a stable account id for a terminal target.

        Prefers the broker login (``account.login``), falling back to the
        terminal id so the (signal, account) ledger key is always populated.
        """
        account = target.get("account") or {}
        login = account.get("login") if isinstance(account, dict) else None
        if login not in (None, ""):
            return str(login)
        tid = target.get("id")
        return str(tid) if tid else ""

    @staticmethod
    def _account_mode(target: dict[str, Any]) -> str:
        account = target.get("account") or {}
        mode = account.get("mode") if isinstance(account, dict) else None
        return str(mode).upper() if mode else "DEMO"

    def _account_context(self, target: dict[str, Any]) -> _AccountContext:
        account = target.get("account") or {}
        account_id = self._account_id_for(target)
        equity = 0.0
        if isinstance(account, dict):
            try:
                equity = float(account.get("equity") or 0.0)
            except (TypeError, ValueError):
                equity = 0.0
        positions: list[dict[str, Any]] = []
        if self.positions_provider is not None:
            try:
                positions = list(self.positions_provider(target) or [])
            except Exception:  # noqa: BLE001
                positions = []
        account_state: dict[str, Any] = {}
        if self.account_state_provider is not None:
            try:
                account_state = dict(self.account_state_provider(target) or {})
            except Exception:  # noqa: BLE001
                account_state = {}
        # Always surface the account's own identity/balance snapshot so the
        # per-account Risk Gate can see which account it is validating (and can
        # never accidentally validate against another account's numbers).
        if isinstance(account, dict):
            for key in ("login", "mode", "balance", "currency", "server"):
                account_state.setdefault(key, account.get(key))
        account_state.setdefault("equity", equity)
        return _AccountContext(
            account_id=account_id,
            terminal_id=str(target.get("id") or ""),
            environment=self._account_mode(target),
            equity=equity,
            position_count=len(positions),
            account_state=account_state,
        )

    def _normalize(
        self,
        signal: CanonicalSignal,
        target: dict[str, Any],
        raw_proposal: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Broker-normalize the account-specific order (never the signal).

        Returns a proposal dict carrying the account's resolved symbol, its
        normalized volume and absolute entry/SL/TP. Numbers that cannot be
        resolved degrade to the signal's own reference values.
        """
        symbol = signal.symbol
        if self.symbol_resolver is not None:
            try:
                symbol = self.symbol_resolver(signal.symbol, target) or signal.symbol
            except Exception:  # noqa: BLE001 - fall back to the base symbol
                symbol = signal.symbol

        base = dict(raw_proposal or {})
        proposal = {
            "symbol": symbol,
            "order_type": signal.direction,
            "direction": signal.direction,
            "volume": float(base.get("volume") or 0.0),
            "price": float(signal.entry_reference or 0.0),
            "stop_loss": float(signal.initial_SL or 0.0),
            "take_profit": float(signal.initial_TP or 0.0),
            "magic": base.get("magic", 70000),
            "comment": base.get("comment") or f"EA-Bot-{signal.direction}",
        }

        normalized: dict[str, Any] = {}
        if self.order_builder is not None:
            try:
                quote = base.get("market_quote") or {}
                request = self.order_builder.build_order_request(proposal, quote)
                proposal["volume"] = float(getattr(request, "volume", proposal["volume"]) or 0.0)
                proposal["price"] = float(getattr(request, "price", proposal["price"]) or 0.0)
                proposal["stop_loss"] = float(
                    getattr(request, "sl", proposal["stop_loss"]) or proposal["stop_loss"]
                )
                proposal["take_profit"] = float(
                    getattr(request, "tp", proposal["take_profit"]) or proposal["take_profit"]
                )
                normalized = {
                    "client_order_id": getattr(request, "client_order_id", None),
                    "digits": getattr(request, "digits", None),
                }
            except Exception as exc:  # noqa: BLE001 - normalization is best-effort
                logger.debug("Order normalization skipped: %s", exc)
        return {"proposal": proposal, "normalized": normalized}

    def _risk_gate_account(
        self,
        proposal: dict[str, Any],
        ctx: _AccountContext,
        target: dict[str, Any],
    ) -> tuple[bool, str]:
        """Run the account-specific Risk Gate on the normalized order.

        Fail-closed: when a gate is configured and raises, the account is
        REJECTED. When no gate is configured, the account is approved (the
        caller opted out of per-account risk).
        """
        if self.risk_gate is None:
            return True, "no per-account risk gate configured"
        market_info: dict[str, Any] = {}
        if self.market_info_provider is not None:
            try:
                market_info = dict(
                    self.market_info_provider(proposal.get("symbol", ""), target) or {}
                )
            except Exception:  # noqa: BLE001
                market_info = {}
        positions: list[dict[str, Any]] = []
        if self.positions_provider is not None:
            try:
                positions = list(self.positions_provider(target) or [])
            except Exception:  # noqa: BLE001
                positions = []
        try:
            decision = self.risk_gate.validate_proposal(
                proposal, ctx.account_state, positions, market_info
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed
            return False, f"risk gate error: {exc}"
        approved = bool(getattr(decision, "approved", False))
        reason = str(getattr(decision, "reason", "") or "")
        return approved, reason

    def _process_account(
        self,
        signal: CanonicalSignal,
        target: dict[str, Any],
        dispatch: AccountDispatch,
        raw_proposal: Optional[dict[str, Any]],
    ) -> None:
        ctx = self._account_context(target)

        # 1) Broker normalization — account-specific values only.
        norm = self._normalize(signal, target, raw_proposal)
        proposal = norm["proposal"]
        dispatch.symbol = proposal["symbol"]
        dispatch.volume = proposal["volume"]
        dispatch.price = proposal["price"]
        dispatch.sl = proposal["stop_loss"]
        dispatch.tp = proposal["take_profit"]
        dispatch.normalized = dict(norm["normalized"])

        # 2) Per-account Risk Gate on the normalized order.
        approved, reason = self._risk_gate_account(proposal, ctx, target)
        if not approved:
            # CRITICAL: a rejection is recorded here ONLY. The canonical signal
            # is untouched and NO second signal is requested.
            dispatch.set_status(AccountExecutionStatus.REJECTED, reason or "risk ditolak")
            return
        dispatch.set_status(AccountExecutionStatus.APPROVED, reason or "risk approved")

        # 3) Execution — only via the engine, always carrying the signal_id.
        if self.execution_engine is None:
            dispatch.set_status(AccountExecutionStatus.REJECTED, "no execution engine configured")
            return

        dispatch.set_status(AccountExecutionStatus.SUBMITTING, "mengirim order")
        request = self._build_request(proposal, signal, ctx.account_id)
        if request is None:
            dispatch.set_status(AccountExecutionStatus.FAILED, "urutan tidak dapat dibangun")
            return

        result = self.execution_engine.execute_order(request)
        success = bool(getattr(result, "success", False))
        dispatch.ticket = getattr(result, "ticket", None)
        if success:
            dispatch.set_status(AccountExecutionStatus.FILLED, "order terisi")
        else:
            dispatch.set_status(
                AccountExecutionStatus.FAILED,
                str(getattr(result, "error_message", "execution failed") or "execution failed"),
            )

    def _build_request(
        self, proposal: dict[str, Any], signal: CanonicalSignal, account_id: str
    ) -> Any:
        """Build the final OrderRequest, stamping the canonical signal_id.

        The idempotency key is derived from ``(signal_id, account_id)`` so it is
        UNIQUE per account (two accounts may each send) but STABLE for the same
        signal/account pair — a *duplicate* fan-out of the same signal therefore
        cannot double-send. The canonical ``signal_id`` is also stamped into the
        order comment so no account order can exist without its signal.
        """
        if self.order_builder is None:
            # Fall back to a minimal OrderRequest-shaped object only when the
            # engine can accept a proposal dict (test doubles).
            return _proposal_request(proposal, signal, account_id)
        try:
            build = dict(proposal)
            build["client_order_id"] = f"{signal.signal_id}:{account_id}"
            build["comment"] = f"{build.get('comment') or 'EA-Bot'} {signal.signal_id}"
            request = self.order_builder.build_order_request(
                build, proposal.get("market_quote") or {}
            )
            return request
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fan-out request build failed: %s", exc)
            return None


def _proposal_request(proposal: dict[str, Any], signal: CanonicalSignal, account_id: str) -> Any:
    """Minimal request object used when no OrderBuilder is injected.

    Carries the canonical ``signal_id`` (in both the idempotency key and the
    comment) so an account can never reach execution without it.
    """
    try:
        from execution.engine import OrderRequest

        return OrderRequest(
            symbol=str(proposal.get("symbol") or signal.symbol),
            order_type=str(proposal.get("order_type") or signal.direction),
            volume=float(proposal.get("volume") or 0.0),
            price=float(proposal.get("price") or signal.entry_reference or 0.0),
            sl=float(proposal.get("stop_loss") or signal.initial_SL or 0.0),
            tp=float(proposal.get("take_profit") or signal.initial_TP or 0.0),
            magic=int(proposal.get("magic") or 70000),
            comment=f"{proposal.get('comment') or 'EA-Bot'} {signal.signal_id}",
            idempotency_key=f"{signal.signal_id}:{account_id}",
        )
    except Exception:  # noqa: BLE001
        return proposal
