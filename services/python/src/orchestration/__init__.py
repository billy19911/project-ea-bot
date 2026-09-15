# -*- coding: utf-8 -*-
"""Orchestration package — end-to-end decision pipeline wiring.

The orchestration layer is the *only* place allowed to connect the AI
Supervisor to the deterministic Risk Gate and the Execution Engine
(PRD_V2 §10.3, §32.1–.7, §32.17). It contains:

- :class:`~orchestration.pipeline.TradingPipeline` — runs one decision cycle.
- :mod:`orchestration.endpoints` — FastAPI router exposing pipeline/scheduler.
"""

from __future__ import annotations

from .context_builder import ContextBuilder
from .pipeline import PipelineResult, PipelineStage, TradingPipeline

__all__ = [
    "TradingPipeline",
    "PipelineResult",
    "PipelineStage",
    "ContextBuilder",
]
