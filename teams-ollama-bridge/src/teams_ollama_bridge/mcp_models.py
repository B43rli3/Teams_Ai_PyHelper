"""Datenmodelle für MCP-Integration (intern)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiscoveredMcpTool:
    """Vom Server gemeldetes Tool nach Policy-Filter."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class NormalizedToolResult:
    """Normalisiertes MCP-Toolergebnis für Ollama."""

    text: str
    ok: bool
    reason: str | None = None
    truncated: bool = False


@dataclass
class McpCallRecord:
    """Interner Datensatz eines Tool-Aufrufs."""

    name: str
    status: str
    error: str | None = None


@dataclass
class AgentLoopResult:
    """Ergebnis des Agent-Loops."""

    answer: str
    model: str
    processing_duration_ms: int
    mcp_used: bool = False
    mcp_error: str | None = None
    tools_called: list[McpCallRecord] = field(default_factory=list)
