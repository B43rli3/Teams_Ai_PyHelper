"""Sicherheitsrichtlinie für MCP-Tool-Aufrufe."""

from __future__ import annotations

from teams_ollama_bridge.exceptions import MCPToolNotAllowedError

DEFAULT_ALLOWED_TOOLS: frozenset[str] = frozenset(
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

DEFAULT_BLOCKED_TOOLS: frozenset[str] = frozenset(
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


class ToolPolicy:
    """Erzwingt Allowlist/Blocklist für MCP-Tools."""

    def __init__(self, allowed: set[str], blocked: set[str]) -> None:
        self._allowed = allowed
        self._blocked = blocked

    @classmethod
    def from_sets(cls, allowed: set[str], blocked: set[str]) -> ToolPolicy:
        return cls(allowed=allowed, blocked=blocked)

    def is_allowed(self, tool_name: str) -> bool:
        if tool_name in self._blocked:
            return False
        return tool_name in self._allowed

    def ensure_allowed(self, tool_name: str) -> None:
        if not self.is_allowed(tool_name):
            raise MCPToolNotAllowedError(tool_name)

    @property
    def allowed_tools(self) -> frozenset[str]:
        return frozenset(self._allowed - self._blocked)

    @property
    def blocked_tools(self) -> frozenset[str]:
        return frozenset(self._blocked)
