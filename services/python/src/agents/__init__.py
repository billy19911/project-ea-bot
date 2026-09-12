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
from .supervisor import DEFAULT_ROUTING_TABLE, SupervisorAgent

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
]
