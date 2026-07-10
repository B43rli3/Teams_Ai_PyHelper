"""MCP-Client für CPD-AutoPlan (Streamable HTTP)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from teams_ollama_bridge.exceptions import (
    MCPAuthenticationError,
    MCPConsentRequiredError,
    MCPProtocolError,
    MCPToolError,
    MCPUnavailableError,
)
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.mcp_models import DiscoveredMcpTool, NormalizedToolResult
from teams_ollama_bridge.mcp_result_normalizer import (
    extract_tool_text_content,
    normalize_tool_result,
)
from teams_ollama_bridge.tool_policy import ToolPolicy

logger = get_logger(__name__)


class MCPClient:
    """Verbindung zum lokalen CPD-AutoPlan MCP-Server."""

    def __init__(
        self,
        server_url: str,
        token: str,
        *,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        max_result_characters: int,
        log_tool_calls: bool,
        log_tool_results: bool,
        policy: ToolPolicy,
    ) -> None:
        self._server_url = server_url
        self._token = token
        self._connect_timeout = connect_timeout_seconds
        self._read_timeout = read_timeout_seconds
        self._max_result_characters = max_result_characters
        self._log_tool_calls = log_tool_calls
        self._log_tool_results = log_tool_results
        self._policy = policy

    @property
    def policy(self) -> ToolPolicy:
        return self._policy

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._connect_timeout,
            read=self._read_timeout,
            write=self._read_timeout,
            pool=self._connect_timeout,
        )

    def _handle_http_error(self, exc: httpx.HTTPStatusError) -> None:
        status = exc.response.status_code
        if status == 401:
            raise MCPAuthenticationError(
                "Der CPD-Zugriff ist aktuell nicht autorisiert. "
                "Bitte den Token aus dem CPD-Agent-Panel prüfen."
            ) from exc
        if status == 404:
            raise MCPProtocolError(
                f"MCP-Endpunkt nicht gefunden: {self._server_url}. "
                "Bitte MCP_SERVER_URL prüfen."
            ) from exc
        if status == 405:
            raise MCPProtocolError(
                "Ungültiger HTTP-Transport für MCP (405 Method Not Allowed). "
                "Erwartet wird Streamable HTTP per POST."
            ) from exc
        raise MCPProtocolError(f"MCP-HTTP-Fehler ({status}).") from exc

    async def _with_session(self, operation: Any) -> Any:
        try:
            async with httpx.AsyncClient(
                headers=self._headers(),
                timeout=self._timeout(),
            ) as http_client, streamable_http_client(
                url=self._server_url,
                http_client=http_client,
            ) as streams:
                read_stream = streams[0]
                write_stream = streams[1]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await operation(session)
        except httpx.ConnectError as exc:
            raise MCPUnavailableError(
                "CPD-AutoPlan läuft nicht oder der MCP-Server ist nicht aktiv."
            ) from exc
        except httpx.TimeoutException as exc:
            raise MCPUnavailableError("MCP-Anfrage hat das Zeitlimit überschritten.") from exc
        except httpx.HTTPStatusError as exc:
            self._handle_http_error(exc)
        except (MCPAuthenticationError, MCPConsentRequiredError, MCPToolError, MCPProtocolError):
            raise
        except Exception as exc:
            message = str(exc).lower()
            if "401" in message or "unauthorized" in message:
                raise MCPAuthenticationError(
                    "Der CPD-Zugriff ist aktuell nicht autorisiert. "
                    "Bitte den Token aus dem CPD-Agent-Panel prüfen."
                ) from exc
            raise MCPProtocolError(f"MCP-Protokollfehler: {exc}") from exc

    def list_tools(self) -> list[DiscoveredMcpTool]:
        async def _op(session: ClientSession) -> list[DiscoveredMcpTool]:
            result = await session.list_tools()
            tools: list[DiscoveredMcpTool] = []
            for tool in result.tools:
                schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
                tools.append(
                    DiscoveredMcpTool(
                        name=tool.name,
                        description=(tool.description or "").strip(),
                        input_schema=schema,
                    )
                )
            return tools

        return asyncio.run(self._with_session(_op))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> NormalizedToolResult:
        self._policy.ensure_allowed(name)
        if self._log_tool_calls:
            logger.info("MCP Tool Call gestartet: %s", name)

        async def _op(session: ClientSession) -> NormalizedToolResult:
            result = await session.call_tool(name, arguments)
            raw_text, _ = extract_tool_text_content(list(result.content))
            is_error = bool(result.isError)
            normalized = normalize_tool_result(
                raw_text,
                max_chars=self._max_result_characters,
                is_error=is_error,
            )
            if self._log_tool_results:
                preview = normalized.text[:200]
                logger.debug("MCP Tool Ergebnis (%s): %s...", name, preview)
            return normalized

        normalized: NormalizedToolResult = asyncio.run(self._with_session(_op))
        if self._log_tool_calls:
            logger.info("MCP Tool Call beendet: %s", name)
        return normalized

    def ping(self) -> int:
        """Verbindung testen und Anzahl gemeldeter Tools zurückgeben."""
        return len(self.list_tools())
