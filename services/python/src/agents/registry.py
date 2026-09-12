# -*- coding: utf-8 -*-
"""Agent registry singleton — imported by main.py for health check & startup."""

from .base import AgentRegistry

agent_registry = AgentRegistry()
