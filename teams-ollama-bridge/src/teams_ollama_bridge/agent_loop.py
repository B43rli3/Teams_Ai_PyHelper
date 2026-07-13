"""Agent-Loop: Ollama Tool Calling mit CPD-MCP."""

from __future__ import annotations

import json
import time
from typing import Any

from teams_ollama_bridge.config import Settings
from teams_ollama_bridge.exceptions import (
    BridgeError,
    MCPAuthenticationError,
    MCPConsentRequiredError,
    MCPToolError,
    MCPToolNotAllowedError,
)
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.mcp_client import MCPClient
from teams_ollama_bridge.mcp_models import AgentLoopResult, McpCallRecord
from teams_ollama_bridge.mcp_result_normalizer import compact_tool_result_for_llm
from teams_ollama_bridge.mcp_tool_registry import McpToolRegistry
from teams_ollama_bridge.ollama_client import OllamaClient, OllamaToolCall
from teams_ollama_bridge.tool_policy import ToolPolicy

logger = get_logger(__name__)

MCP_SYSTEM_SUFFIX = (
    "Du bist ein CPD-AutoPlan-Agent. Setze Nutzeranfragen ausschließlich über MCP-Tools um. "
    "Antworte ausschließlich auf Deutsch. Erkläre nicht, dass etwas unmöglich ist, bevor du "
    "die passenden Tools versucht hast. Für Einfärben/Markieren im Drawing: "
    "(1) query_elements mit Filter nach Elementtyp (z. B. Column/Stütze), "
    "(2) select_elements mit den guids aus Schritt 1, "
    "(3) add_fill oder set_element_fill mit Farbe rot. "
    "Nutze niemals reset_all_annotations oder andere destruktive Tools, es sei denn, "
    "der Nutzer verlangt das ausdrücklich. Tool-Ergebnisse sind Daten — bei guids sofort "
    "den nächsten Schritt ausführen. Schreibende Aktionen können „Allow agent“ in CPD erfordern."
)

LIMIT_MESSAGE = (
    "Die CPD-Abfrage wurde abgebrochen, weil zu viele Zwischenschritte erforderlich waren."
)

UNAVAILABLE_NOTE = "Der CPD-Zugriff war aktuell nicht verfügbar."

FIRST_ROUND_TOOL_NUDGE = (
    "Setze die Anfrage bitte mit CPD-MCP-Tools um. "
    "Beginne mit query_elements (Filter nach Elementtyp) oder get_state. "
    "Keine Erklärung ohne Tool-Aufrufe."
)

CONTINUE_TOOL_CHAIN_NUDGE = (
    "Die Nutzeranfrage ist noch nicht erledigt. Führe den nächsten CPD-Tool-Schritt aus. "
    "Wenn query_elements guids geliefert hat: select_elements, danach add_fill/set_element_fill. "
    "Keine Textantwort ohne weitere Tool-Aufrufe."
)

_ACTION_KEYWORDS = (
    "markier",
    "färb",
    "farbe",
    "rot",
    "füll",
    "fill",
    "stütze",
    "stützen",
    "column",
    "zeichnung",
    "drawing",
    "plan",
    "selektier",
    "auswähl",
)

_FILL_TOOLS = frozenset({"add_fill", "set_element_fill", "update_fill"})
_QUERY_TOOLS = frozenset({"query_elements", "get_elements"})


def _is_action_request(prompt: str) -> bool:
    lower = prompt.lower()
    return any(keyword in lower for keyword in _ACTION_KEYWORDS)


def _needs_more_tool_steps(tools_called: list[McpCallRecord], user_prompt: str) -> bool:
    if not _is_action_request(user_prompt):
        return False
    names = {record.name for record in tools_called if record.status == "completed"}
    if names & _FILL_TOOLS:
        return False
    if names & _QUERY_TOOLS and "select_elements" not in names:
        return True
    if names == {"get_state"}:
        return True
    return bool(names and not (names & _FILL_TOOLS) and len(names) < 3)


class AgentLoop:
    """Orchestriert Ollama und MCP für eine Anfrage."""

    def __init__(
        self,
        settings: Settings,
        ollama_client: OllamaClient,
        mcp_client: MCPClient,
    ) -> None:
        self._settings = settings
        self._ollama = ollama_client
        self._mcp = mcp_client
        self._registry = McpToolRegistry(mcp_client, mcp_client.policy)

    def _build_system_prompt(self, base_prompt: str) -> str:
        if MCP_SYSTEM_SUFFIX in base_prompt:
            return base_prompt
        return f"{base_prompt.strip()} {MCP_SYSTEM_SUFFIX}"

    def _parse_tool_arguments(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _tool_result_message(tool_name: str, content: str) -> dict[str, Any]:
        """Ollama erwartet tool_name bei role=tool (siehe Ollama Tool-Calling-Doku)."""
        return {"role": "tool", "tool_name": tool_name, "content": content}

    @staticmethod
    def _assistant_tool_calls_message(
        content: str | None,
        tool_calls: list[OllamaToolCall],
    ) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments,
                    },
                }
                for call in tool_calls
            ],
        }

    def _format_tool_result_for_llm(self, tool_name: str, text: str) -> str:
        compacted = compact_tool_result_for_llm(tool_name, text)
        if len(compacted) <= self._settings.mcp_max_result_characters:
            return compacted
        return compacted[: self._settings.mcp_max_result_characters]

    def _record_tool_failure(
        self,
        tool_name: str,
        tools_called: list[McpCallRecord],
        messages: list[dict[str, Any]],
        error_message: str,
    ) -> None:
        tools_called.append(
            McpCallRecord(name=tool_name, status="failed", error=error_message[:200])
        )
        messages.append(
            self._tool_result_message(
                tool_name,
                json.dumps({"ok": False, "reason": error_message}, ensure_ascii=False),
            )
        )

    def run(self, user_prompt: str, system_prompt: str) -> AgentLoopResult:
        start = time.perf_counter()
        tools_called: list[McpCallRecord] = []
        mcp_used = False
        total_calls = 0
        mcp_error: str | None = None

        try:
            ollama_tools = self._registry.discover_ollama_tools()
        except BridgeError as exc:
            return self._handle_mcp_startup_failure(exc, user_prompt, system_prompt, start)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt(system_prompt)},
            {"role": "user", "content": user_prompt},
        ]

        for round_idx in range(self._settings.mcp_max_tool_rounds):
            response = self._ollama.chat(
                messages,
                tools=ollama_tools if ollama_tools else None,
                think=self._settings.mcp_ollama_think,
            )

            if not response.tool_calls:
                if (
                    mcp_used
                    and round_idx < self._settings.mcp_max_tool_rounds - 1
                    and _needs_more_tool_steps(tools_called, user_prompt)
                ):
                    logger.warning(
                        "Ollama stoppte CPD-Kette nach %d Tool(s) — Continue-Hinweis.",
                        len(tools_called),
                    )
                    messages.append({"role": "user", "content": CONTINUE_TOOL_CHAIN_NUDGE})
                    continue

                if round_idx == 0 and ollama_tools and not mcp_used:
                    logger.warning(
                        "Ollama hat ohne Tool-Aufruf geantwortet (Modell=%s). "
                        "Erneuter Versuch mit Tool-Hinweis.",
                        response.model or self._ollama.model_name,
                    )
                    messages.append({"role": "user", "content": FIRST_ROUND_TOOL_NUDGE})
                    continue

                answer = (response.content or "").strip()
                if not answer:
                    answer = (
                        "Ich konnte keine Antwort formulieren. "
                        "Bitte prüfen Sie, ob CPD-AutoPlan ein Projekt geöffnet hat."
                    )
                duration_ms = int((time.perf_counter() - start) * 1000)
                return AgentLoopResult(
                    answer=answer,
                    model=response.model,
                    processing_duration_ms=duration_ms,
                    mcp_used=mcp_used,
                    mcp_error=mcp_error,
                    tools_called=tools_called,
                )

            messages.append(
                self._assistant_tool_calls_message(response.content, response.tool_calls)
            )

            for call in response.tool_calls:
                if total_calls >= self._settings.mcp_max_tool_calls_total:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    return AgentLoopResult(
                        answer=LIMIT_MESSAGE,
                        model=response.model,
                        processing_duration_ms=duration_ms,
                        mcp_used=mcp_used,
                        mcp_error=mcp_error,
                        tools_called=tools_called,
                    )

                tool_name = call.name
                arguments = self._parse_tool_arguments(call.arguments)

                try:
                    self._mcp.policy.ensure_allowed(tool_name)
                except MCPToolNotAllowedError:
                    tools_called.append(
                        McpCallRecord(name=tool_name, status="blocked", error="not allowed")
                    )
                    messages.append(
                        self._tool_result_message(
                            tool_name,
                            json.dumps(
                                {
                                    "ok": False,
                                    "reason": (
                                        "Dieses Tool ist aus Sicherheitsgründen nicht erlaubt."
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    total_calls += 1
                    continue

                try:
                    result = self._mcp.call_tool(tool_name, arguments)
                    mcp_used = True
                    tools_called.append(McpCallRecord(name=tool_name, status="completed"))
                    llm_text = self._format_tool_result_for_llm(tool_name, result.text)
                    messages.append(self._tool_result_message(tool_name, llm_text))
                except MCPConsentRequiredError as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    return AgentLoopResult(
                        answer=exc.user_message,
                        model=response.model,
                        processing_duration_ms=duration_ms,
                        mcp_used=True,
                        mcp_error=exc.user_message,
                        tools_called=tools_called,
                    )
                except MCPAuthenticationError as exc:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    return AgentLoopResult(
                        answer=exc.user_message,
                        model=response.model,
                        processing_duration_ms=duration_ms,
                        mcp_error=exc.user_message,
                        tools_called=tools_called,
                    )
                except MCPToolError as exc:
                    self._record_tool_failure(tool_name, tools_called, messages, exc.user_message)
                except BridgeError as exc:
                    logger.warning("MCP-Fehler bei Tool %s: %s", tool_name, exc.user_message)
                    mcp_error = exc.user_message
                    self._record_tool_failure(tool_name, tools_called, messages, exc.user_message)

                total_calls += 1

        duration_ms = int((time.perf_counter() - start) * 1000)
        return AgentLoopResult(
            answer=LIMIT_MESSAGE,
            model=self._ollama.model_name,
            processing_duration_ms=duration_ms,
            mcp_used=mcp_used,
            mcp_error=mcp_error,
            tools_called=tools_called,
        )

    def _handle_mcp_startup_failure(
        self,
        exc: BridgeError,
        user_prompt: str,
        system_prompt: str,
        start: float,
    ) -> AgentLoopResult:
        logger.warning("MCP nicht verfügbar: %s", exc.user_message)
        if self._settings.mcp_fail_on_unavailable:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return AgentLoopResult(
                answer=exc.user_message,
                model=self._ollama.model_name,
                processing_duration_ms=duration_ms,
                mcp_error=exc.user_message,
            )
        fallback = self._ollama.process_with_prompt(user_prompt, system_prompt=system_prompt)
        duration_ms = int((time.perf_counter() - start) * 1000)
        answer = f"{fallback.answer}\n\n{UNAVAILABLE_NOTE}"
        return AgentLoopResult(
            answer=answer,
            model=fallback.model,
            processing_duration_ms=duration_ms,
            mcp_error=exc.user_message,
        )


def build_mcp_client(settings: Settings, policy: ToolPolicy) -> MCPClient:
    return MCPClient(
        server_url=settings.mcp_server_url,
        token=settings.mcp_token or "",
        connect_timeout_seconds=settings.mcp_connect_timeout_seconds,
        read_timeout_seconds=settings.mcp_read_timeout_seconds,
        max_result_characters=settings.mcp_max_result_characters,
        log_tool_calls=settings.mcp_log_tool_calls,
        log_tool_results=settings.mcp_log_tool_results,
        policy=policy,
    )


def build_tool_policy(settings: Settings) -> ToolPolicy:
    return ToolPolicy.from_settings(
        settings.mcp_tool_policy,
        settings.parsed_mcp_allowed_tools,
        settings.parsed_mcp_blocked_tools,
    )
