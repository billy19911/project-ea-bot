# -*- coding: utf-8 -*-
"""Tool permission registry — EPIC 17.06.

Maps tool names to the permission an agent must hold to invoke them.
"""

from typing import Dict, List


class ToolPermissionError(RuntimeError):
    """Raised when an agent tries to invoke a tool it is not allowed to use."""

    def __init__(self, agent_name: str, tool: str, required: str) -> None:
        super().__init__(
            f"Agent '{agent_name}' is not allowed to invoke tool '{tool}' "
            f"(requires permission '{required}')"
        )
        self.agent_name = agent_name
        self.tool = tool
        self.required = required


class ToolPermissionRegistry:
    """Registry of tools and the permissions they require.

    A wildcard permission ``*`` grants access to every registered tool.
    Unknown tools are always denied (fail-closed).
    """

    WILDCARD = "*"

    def __init__(self) -> None:
        self._tools: Dict[str, str] = {}

    def register_tool(self, tool: str, required_permission: str) -> None:
        if tool in self._tools:
            raise ValueError(f"Tool '{tool}' is already registered")
        self._tools[tool] = required_permission

    def check(self, agent_permissions: List[str], tool: str) -> bool:
        required = self._tools.get(tool)
        if required is None:
            return False
        if self.WILDCARD in agent_permissions:
            return True
        return required in agent_permissions

    def require(self, agent_name: str, agent_permissions: List[str], tool: str) -> None:
        if not self.check(agent_permissions=agent_permissions, tool=tool):
            required = self._tools.get(tool, "<unregistered>")
            raise ToolPermissionError(agent_name=agent_name, tool=tool, required=required)

    def list_tools(self, agent_permissions: List[str]) -> List[str]:
        return sorted(t for t in self._tools if self.check(agent_permissions, t))

    def registered_tools(self) -> Dict[str, str]:
        return dict(self._tools)
