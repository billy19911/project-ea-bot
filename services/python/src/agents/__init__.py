# -*- coding: utf-8 -*-
"""EA Bot AI Agent Framework.

Provides a plugin-style agent registry, base agent ABC, concrete agent
implementations, and a supervisor for event-driven orchestration.
"""

from .base import (
    AgentCapability,
    AgentPriority,
    AgentRegistry,
    BaseAgent,
    FundamentalAnalystAgent,
    SentimentAnalystAgent,
    TechnicalAnalystAgent,
)
from .decision_state import ActionType, DecisionState, MarketBias, SetupType
from .evidence import EvidenceBundle, EvidenceItem, EvidenceKind, Freshness
from .supervisor import DEFAULT_ROUTING_TABLE, SupervisorAgent
from .synthesis import AgentSynthesizer, SynthesisResult, TradeProposal
from .task import TERMINAL_STATUSES as TASK_TERMINAL_STATUSES
from .task import IllegalTaskTransitionError, Task, TaskPriority, TaskStatus

__all__ = [
    "AgentRegistry",
    "AgentPriority",
    "AgentCapability",
    "BaseAgent",
    "TechnicalAnalystAgent",
    "FundamentalAnalystAgent",
    "SentimentAnalystAgent",
    "SupervisorAgent",
    "DEFAULT_ROUTING_TABLE",
    "TradeProposal",
    "SynthesisResult",
    "AgentSynthesizer",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "IllegalTaskTransitionError",
    "TASK_TERMINAL_STATUSES",
    "EvidenceItem",
    "EvidenceBundle",
    "EvidenceKind",
    "Freshness",
    "DecisionState",
    "MarketBias",
    "SetupType",
    "ActionType",
]
