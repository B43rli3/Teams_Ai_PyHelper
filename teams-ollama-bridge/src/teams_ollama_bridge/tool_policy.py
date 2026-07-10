"""Client-seitige Filterung von MCP-Tools (unabhängig vom CPD-Server-Katalog)."""

from __future__ import annotations

from typing import Literal

from teams_ollama_bridge.exceptions import MCPToolNotAllowedError

McpToolPolicyMode = Literal["full", "read_only"]

READ_ONLY_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "get_state",
        "list_annotations",
        "list_catalog_fields",
        "describe_catalog",
        "get_group_template",
        "get_annotation_values",
        "query_elements",
        "field_values",
        "get_elements",
        "get_run_status",
    }
)

READ_ONLY_BLOCKED_TOOLS: frozenset[str] = frozenset(
    {
        "screenshot",
        "set_active_stage",
        "select_storey",
        "set_storey_cut",
        "set_below_lines",
        "set_storey_scope",
        "set_rotation",
        "reset_rotation_auto",
        "set_drawing_scale",
        "set_source_storey",
        "set_visibility_filter",
        "add_fill",
        "update_fill",
        "reorder_fill",
        "add_poche_preset",
        "set_element_fill",
        "clear_element_fill",
        "delete_fill",
        "create_group",
        "create_action_point_group",
        "duplicate_group",
        "update_group",
        "set_group_filter",
        "set_group_template",
        "set_group_fields",
        "reorder_group",
        "delete_group",
        "regenerate_group",
        "reset_group",
        "reset_all_annotations",
        "select_elements",
        "clear_selection",
        "pin_annotation",
        "move_annotation",
        "release_annotation",
        "delete_annotation",
        "update_cell_value",
        "clear_cell_override",
        "update_sheet",
        "start_run",
        "cancel_run",
    }
)

# Rückwärtskompatibilität für Importe/Tests
DEFAULT_ALLOWED_TOOLS = READ_ONLY_ALLOWED_TOOLS
DEFAULT_BLOCKED_TOOLS = READ_ONLY_BLOCKED_TOOLS


class ToolPolicy:
    """Optionaler Client-Filter auf den vom MCP-Server gemeldeten Tool-Katalog."""

    def __init__(
        self,
        allowed: set[str],
        blocked: set[str],
        *,
        allow_all: bool = False,
    ) -> None:
        self._allowed = allowed
        self._blocked = blocked
        self._allow_all = allow_all

    @classmethod
    def from_sets(
        cls,
        allowed: set[str],
        blocked: set[str],
        *,
        allow_all: bool = False,
    ) -> ToolPolicy:
        return cls(allowed=allowed, blocked=blocked, allow_all=allow_all)

    @classmethod
    def from_settings(
        cls,
        mode: McpToolPolicyMode,
        allowed: set[str],
        blocked: set[str],
    ) -> ToolPolicy:
        """Policy aus .env ableiten.

        full: alle vom Server gemeldeten Tools, optional minus MCP_BLOCKED_TOOLS.
        read_only: nur MCP_ALLOWED_TOOLS (Preset: 10 Lesetools), minus Blocklist.
        """
        if mode == "read_only":
            effective_allowed = allowed or set(READ_ONLY_ALLOWED_TOOLS)
            effective_blocked = blocked or set(READ_ONLY_BLOCKED_TOOLS)
            return cls(allowed=effective_allowed, blocked=effective_blocked, allow_all=False)
        return cls(allowed=set(), blocked=blocked, allow_all=True)

    @property
    def mode(self) -> McpToolPolicyMode:
        return "full" if self._allow_all else "read_only"

    @property
    def uses_full_server_catalog(self) -> bool:
        return self._allow_all

    def is_allowed(self, tool_name: str) -> bool:
        if tool_name in self._blocked:
            return False
        if self._allow_all:
            return True
        return tool_name in self._allowed

    def ensure_allowed(self, tool_name: str) -> None:
        if not self.is_allowed(tool_name):
            raise MCPToolNotAllowedError(tool_name)

    @property
    def allowed_tools(self) -> frozenset[str]:
        if self._allow_all:
            return frozenset()
        return frozenset(self._allowed - self._blocked)

    @property
    def blocked_tools(self) -> frozenset[str]:
        return frozenset(self._blocked)
