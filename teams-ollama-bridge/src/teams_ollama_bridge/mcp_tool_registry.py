"""Tool-Discovery und Ollama-Tool-Schema-Konvertierung."""

from __future__ import annotations

from typing import Any

from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.mcp_client import MCPClient
from teams_ollama_bridge.mcp_models import DiscoveredMcpTool
from teams_ollama_bridge.tool_policy import ToolPolicy

logger = get_logger(__name__)


def _is_valid_input_schema(schema: dict[str, Any]) -> bool:
    if not schema:
        return True
    schema_type = schema.get("type")
    return schema_type in (None, "object")


def to_ollama_tool_definition(tool: DiscoveredMcpTool) -> dict[str, Any] | None:
    if not _is_valid_input_schema(tool.input_schema):
        logger.warning(
            "MCP-Tool %s hat kein gültiges inputSchema und wird nicht angeboten.",
            tool.name,
        )
        return None
    parameters: dict[str, Any] = tool.input_schema or {"type": "object", "properties": {}}
    if "type" not in parameters:
        parameters = {"type": "object", "properties": parameters.get("properties", {})}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or tool.name,
            "parameters": parameters,
        },
    }


class McpToolRegistry:
    """Filtert und konvertiert MCP-Tools für Ollama."""

    def __init__(self, client: MCPClient, policy: ToolPolicy) -> None:
        self._client = client
        self._policy = policy

    def discover_allowed_tools(self) -> list[DiscoveredMcpTool]:
        all_tools = self._client.list_tools()
        allowed: list[DiscoveredMcpTool] = []
        for tool in all_tools:
            if self._policy.is_allowed(tool.name):
                allowed.append(tool)
            else:
                logger.debug("MCP-Tool blockiert: %s", tool.name)
        logger.info(
            "MCP Tools: %d gefunden, %d erlaubt",
            len(all_tools),
            len(allowed),
        )
        return allowed

    def to_ollama_tools(self, tools: list[DiscoveredMcpTool]) -> list[dict[str, Any]]:
        ollama_tools: list[dict[str, Any]] = []
        for tool in tools:
            definition = to_ollama_tool_definition(tool)
            if definition is not None:
                ollama_tools.append(definition)
        return ollama_tools

    def discover_ollama_tools(self) -> list[dict[str, Any]]:
        return self.to_ollama_tools(self.discover_allowed_tools())
