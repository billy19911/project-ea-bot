# -*- coding: utf-8 -*-
"""Permission enforcement helpers for EPIC 01.04.

These wrappers guard dangerous operations so that only agents with the
correct ``permissions`` may invoke them.  The enforcement is performed
by checking ``agent.permissions`` (list[str]) before the operation
executes, raising ``AgentPermissionError`` when the permission is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.base import BaseAgent

# ---------------------------------------------------------------------------
# Permission constants
# ---------------------------------------------------------------------------

PERM_SUBMIT_TO_RISK_GATE = "SUBMIT_TO_RISK_GATE"
PERM_PROPOSE_EXECUTION = "PROPOSE_EXECUTION"
PERM_SEND_TO_MT5 = "SEND_TO_MT5"


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class AgentPermissionError(RuntimeError):
    """Raised when an agent lacks a required permission."""

    def __init__(self, agent_name: str, permission: str) -> None:
        super().__init__(f"Agent '{agent_name}' lacks permission '{permission}'")
        self.agent_name = agent_name
        self.permission = permission


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def require_permission(agent: "BaseAgent", permission: str) -> None:
    """Raise ``AgentPermissionError`` if ``agent`` lacks ``permission``."""
    if permission not in getattr(agent, "permissions", []):
        raise AgentPermissionError(agent.name, permission)


def can_invoke(agent: "BaseAgent", permission: str) -> bool:
    """Return ``True`` if ``agent`` has ``permission``."""
    return permission in getattr(agent, "permissions", [])


# ---------------------------------------------------------------------------
# Guarded operations (stubs for now – real implementations will call Risk Gate,
# Execution Engine, and MT5 connector respectively)
# ---------------------------------------------------------------------------


def submit_to_risk_gate(
    agent: "BaseAgent",
    payload: dict[str, Any],
    risk_gate: Any = None,
    account_state: dict[str, Any] | None = None,
    current_positions: list[dict[str, Any]] | None = None,
    market_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a trade proposal to the deterministic Risk Gate.

    Only agents with ``SUBMIT_TO_RISK_GATE`` may call this.
    If ``risk_gate`` is provided, it runs full deterministic validation.
    """
    require_permission(agent, PERM_SUBMIT_TO_RISK_GATE)
    if risk_gate is not None:
        decision = risk_gate.validate_proposal(
            proposal=payload,
            account_state=account_state or {},
            current_positions=current_positions or [],
            market_info=market_info or {},
        )
        return {
            "accepted": decision.approved,
            "agent": agent.name,
            "reason": decision.reason,
            "checks_passed": decision.checks_passed,
            "metrics_snapshot": decision.metrics_snapshot,
        }
    return {"accepted": True, "agent": agent.name}


def propose_execution(agent: "BaseAgent", proposal: dict[str, Any]) -> dict[str, Any]:
    """Propose an order to the Execution Engine.

    Only agents with ``PROPOSE_EXECUTION`` may call this.
    """
    require_permission(agent, PERM_PROPOSE_EXECUTION)
    # Stub: in production this will enqueue the proposal for Risk Gate then
    # Execution
    return {"accepted": True, "proposer": agent.name, **proposal}


def send_to_mt5(agent: "BaseAgent", order: dict[str, Any]) -> dict[str, Any]:
    """Send a validated order to MT5.

    Only agents with ``SEND_TO_MT5`` may call this.  This permission is
    intentionally kept separate from ``PROPOSE_EXECUTION`` so that the
    Execution Engine can be the sole component with MT5 write access.
    """
    require_permission(agent, PERM_SEND_TO_MT5)
    # Use guarded_execute_order for safe MT5 writes
    from mt5.connector import guarded_execute_order

    result = guarded_execute_order(agent=agent, order=order)
    return result
