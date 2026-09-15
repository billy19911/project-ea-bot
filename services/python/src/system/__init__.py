# -*- coding: utf-8 -*-
"""System status/control module.

Exposes read-only, honest status endpoints for the Node API control plane:

* models served by the LLM registry (gateway discovery or defaults),
* Telegram gateway configuration state,
* audit events (in-process),
* recent pipeline decisions,
* recent supervisor tasks,
* learning-loop analytics,
* the in-process metrics registry snapshot.

Nothing here fabricates data: when a subsystem has no in-process state the
endpoint returns an empty/``unavailable`` payload rather than demo numbers
(PRD_V2 §25/§26/§27).
"""

from .endpoints import router

__all__ = ["router"]
