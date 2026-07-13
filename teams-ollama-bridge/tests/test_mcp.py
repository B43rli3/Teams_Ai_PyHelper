"""Tests für MCP-Integration."""

from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from tests.conftest import write_input_file

from teams_ollama_bridge.agent_loop import AgentLoop, AgentLoopResult
from teams_ollama_bridge.cli import cmd_mcp_check
from teams_ollama_bridge.config import Settings, load_settings
from teams_ollama_bridge.exceptions import (
    ConfigurationError,
    MCPAuthenticationError,
    MCPConsentRequiredError,
    MCPToolError,
    MCPToolNotAllowedError,
    MCPUnavailableError,
)
from teams_ollama_bridge.logging_config import setup_logging
from teams_ollama_bridge.mcp_client import MCPClient
from teams_ollama_bridge.mcp_models import DiscoveredMcpTool, McpCallRecord, NormalizedToolResult
from teams_ollama_bridge.mcp_result_normalizer import (
    normalize_tool_result,
    truncate_result_text,
)
from teams_ollama_bridge.mcp_tool_registry import McpToolRegistry, to_ollama_tool_definition
from teams_ollama_bridge.models import ProcessorMode
from teams_ollama_bridge.ollama_client import OllamaChatResponse, OllamaClient, OllamaToolCall
from teams_ollama_bridge.processor import RequestProcessor
from teams_ollama_bridge.repository import RequestRepository
from teams_ollama_bridge.tool_policy import ToolPolicy


@pytest.fixture
def policy() -> ToolPolicy:
    return ToolPolicy.from_sets(
        allowed={
            "get_state",
            "query_elements",
            "list_annotations",
            "list_catalog_fields",
            "describe_catalog",
            "get_group_template",
            "get_annotation_values",
            "field_values",
            "get_elements",
            "get_run_status",
        },
        blocked={
            "screenshot",
            "set_active_stage",
            "update_cell_value",
            "delete_group",
            "start_run",
        },
        allow_all=False,
    )


@pytest.fixture
def full_policy() -> ToolPolicy:
    return ToolPolicy.from_settings("full", set(), set())


def test_mcp_disabled_by_default(settings: Settings) -> None:
    assert settings.mcp_enabled is False


def test_mcp_enabled_without_token_raises(
    workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("TEAMS_LLM_ROOT", str(workspace / "TeamsLLM"))
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.delenv("MCP_TOKEN", raising=False)
    with pytest.raises(ConfigurationError, match="MCP_TOKEN"):
        load_settings()


def test_bearer_header_in_mcp_client(policy: ToolPolicy) -> None:
    client = MCPClient(
        server_url="http://127.0.0.1:7373/mcp",
        token="secret-token",
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_result_characters=1000,
        log_tool_calls=False,
        log_tool_results=False,
        policy=policy,
    )
    headers = client._headers()
    assert headers == {"Authorization": "Bearer secret-token"}


def test_token_not_logged(caplog: pytest.LogCaptureFixture, policy: ToolPolicy) -> None:
    caplog.set_level(logging.INFO)
    client = MCPClient(
        server_url="http://127.0.0.1:7373/mcp",
        token="super-secret",
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_result_characters=1000,
        log_tool_calls=True,
        log_tool_results=False,
        policy=policy,
    )
    with patch.object(client, "list_tools", return_value=[]):
        client.ping()
    assert "super-secret" not in caplog.text


def test_policy_allows_read_tools(policy: ToolPolicy) -> None:
    assert policy.is_allowed("get_state")
    assert policy.is_allowed("query_elements")


def test_policy_blocks_screenshot(policy: ToolPolicy) -> None:
    assert not policy.is_allowed("screenshot")
    with pytest.raises(MCPToolNotAllowedError):
        policy.ensure_allowed("screenshot")


def test_policy_blocks_set_active_stage(policy: ToolPolicy) -> None:
    assert not policy.is_allowed("set_active_stage")


def test_policy_blocks_write_tool(policy: ToolPolicy) -> None:
    assert not policy.is_allowed("update_cell_value")


def test_policy_blocks_delete_tool(policy: ToolPolicy) -> None:
    assert not policy.is_allowed("delete_group")


def test_policy_blocks_admin_tool(policy: ToolPolicy) -> None:
    assert not policy.is_allowed("start_run")


def test_unknown_tool_blocked(policy: ToolPolicy) -> None:
    assert not policy.is_allowed("unknown_tool")


def test_unknown_tool_allowed_in_full_mode(full_policy: ToolPolicy) -> None:
    assert full_policy.is_allowed("delete_group")
    assert full_policy.is_allowed("unknown_tool")


def test_full_policy_blocks_explicit_blocklist() -> None:
    policy = ToolPolicy.from_settings("full", set(), {"screenshot"})
    assert policy.is_allowed("get_state")
    assert not policy.is_allowed("screenshot")


def test_read_only_policy_uses_presets_when_lists_empty() -> None:
    policy = ToolPolicy.from_settings("read_only", set(), set())
    assert policy.is_allowed("get_state")
    assert not policy.is_allowed("delete_group")
    assert not policy.is_allowed("screenshot")


def test_registry_full_mode_includes_all_server_tools(full_policy: ToolPolicy) -> None:
    fake_client = MagicMock()
    fake_client.list_tools.return_value = [
        DiscoveredMcpTool("get_state", "state", {"type": "object"}),
        DiscoveredMcpTool("delete_group", "delete", {"type": "object"}),
    ]
    registry = McpToolRegistry(fake_client, full_policy)
    allowed = registry.discover_allowed_tools()
    assert [tool.name for tool in allowed] == ["get_state", "delete_group"]


def test_to_ollama_tool_definition() -> None:
    tool = DiscoveredMcpTool(
        name="get_state",
        description="Live state",
        input_schema={"type": "object", "properties": {}},
    )
    definition = to_ollama_tool_definition(tool)
    assert definition is not None
    assert definition["function"]["name"] == "get_state"


def test_registry_filters_tools(policy: ToolPolicy) -> None:
    fake_client = MagicMock()
    fake_client.list_tools.return_value = [
        DiscoveredMcpTool("get_state", "state", {"type": "object"}),
        DiscoveredMcpTool("delete_group", "delete", {"type": "object"}),
    ]
    fake_client.policy = policy
    registry = McpToolRegistry(fake_client, policy)
    allowed = registry.discover_allowed_tools()
    assert [tool.name for tool in allowed] == ["get_state"]


def test_normalize_json_ok() -> None:
    result = normalize_tool_result('{"ok": true, "data": "x"}', max_chars=1000)
    assert result.ok is True


def test_normalize_ok_false_raises() -> None:
    with pytest.raises(MCPToolError):
        normalize_tool_result('{"ok": false, "reason": "failed"}', max_chars=1000)


def test_normalize_consent_required() -> None:
    with pytest.raises(MCPConsentRequiredError):
        normalize_tool_result(
            '{"ok": false, "reason": "awaiting in-app authorization — click Allow"}',
            max_chars=1000,
        )


def test_truncate_result_text() -> None:
    text, truncated = truncate_result_text("a" * 100, 50)
    assert truncated is True
    assert len(text) <= 50


def test_mcp_client_call_tool_blocked(policy: ToolPolicy) -> None:
    client = MCPClient(
        server_url="http://127.0.0.1:7373/mcp",
        token="token",
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_result_characters=1000,
        log_tool_calls=False,
        log_tool_results=False,
        policy=policy,
    )
    with pytest.raises(MCPToolNotAllowedError):
        client.call_tool("screenshot", {})


def test_mcp_client_http_401(policy: ToolPolicy) -> None:
    client = MCPClient(
        server_url="http://127.0.0.1:7373/mcp",
        token="token",
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_result_characters=1000,
        log_tool_calls=False,
        log_tool_results=False,
        policy=policy,
    )
    request = httpx.Request("POST", client._server_url)
    response = httpx.Response(401)
    with pytest.raises(MCPAuthenticationError):
        client._handle_http_error(
            httpx.HTTPStatusError("unauthorized", request=request, response=response)
        )


def test_mcp_unavailable_connect(policy: ToolPolicy) -> None:
    client = MCPClient(
        server_url="http://127.0.0.1:7373/mcp",
        token="token",
        connect_timeout_seconds=1,
        read_timeout_seconds=1,
        max_result_characters=1000,
        log_tool_calls=False,
        log_tool_results=False,
        policy=policy,
    )

    def _raise_connect(_op: Any) -> list[DiscoveredMcpTool]:
        raise MCPUnavailableError("nicht erreichbar")

    with (
        patch.object(client, "_with_session", side_effect=_raise_connect),
        pytest.raises(MCPUnavailableError),
    ):
        client.list_tools()


def test_agent_loop_serial_tool_calls(settings: Settings, policy: ToolPolicy) -> None:
    settings.mcp_enabled = True
    settings.processor_mode = ProcessorMode.OLLAMA
    settings.mcp_max_tool_calls_total = 2
    settings.mcp_max_tool_rounds = 3

    ollama = MagicMock(spec=OllamaClient)
    ollama.model_name = "test-model"
    ollama.chat.side_effect = [
        OllamaChatResponse(
            content="",
            tool_calls=[
                OllamaToolCall(name="get_state", arguments={}),
                OllamaToolCall(name="query_elements", arguments={"filter": {}}),
            ],
            model="test-model",
        ),
        OllamaChatResponse(content="Finale Antwort", tool_calls=[], model="test-model"),
    ]

    mcp = MagicMock()
    mcp.policy = policy
    mcp.call_tool.return_value = NormalizedToolResult(text='{"ok": true}', ok=True)

    with patch(
        "teams_ollama_bridge.agent_loop.McpToolRegistry.discover_ollama_tools",
        return_value=[
            {
                "type": "function",
                "function": {
                    "name": "get_state",
                    "description": "state",
                    "parameters": {"type": "object"},
                },
            }
        ],
    ):
        loop = AgentLoop(settings, ollama, mcp)
        result = loop.run("Frage", "System")

    assert result.answer == "Finale Antwort"
    assert mcp.call_tool.call_count == 2
    assert [item.name for item in result.tools_called] == ["get_state", "query_elements"]


def test_agent_loop_tool_messages_include_tool_name(
    settings: Settings, policy: ToolPolicy
) -> None:
    ollama = MagicMock(spec=OllamaClient)
    ollama.model_name = "test-model"
    captured_messages: list[list[dict[str, Any]]] = []

    def _chat(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        think: bool = False,
    ) -> OllamaChatResponse:
        captured_messages.append(messages)
        if len(captured_messages) == 1:
            return OllamaChatResponse(
                content="",
                tool_calls=[OllamaToolCall(name="query_elements", arguments={"filter": {}})],
                model="test-model",
            )
        return OllamaChatResponse(content="Fertig", tool_calls=[], model="test-model")

    ollama.chat.side_effect = _chat

    mcp = MagicMock()
    mcp.policy = policy
    mcp.call_tool.return_value = NormalizedToolResult(text='{"ok": true}', ok=True)

    with patch(
        "teams_ollama_bridge.agent_loop.McpToolRegistry.discover_ollama_tools",
        return_value=[{"type": "function", "function": {"name": "query_elements"}}],
    ):
        loop = AgentLoop(settings, ollama, mcp)
        loop.run("Markiere Stützen", "System")

    second_request_messages = captured_messages[1]
    tool_messages = [msg for msg in second_request_messages if msg.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_name"] == "query_elements"


def test_agent_loop_retries_when_model_skips_tools(
    settings: Settings, policy: ToolPolicy
) -> None:
    ollama = MagicMock(spec=OllamaClient)
    ollama.model_name = "test-model"
    ollama.chat.side_effect = [
        OllamaChatResponse(
            content="Es gibt keine direkte Funktion...",
            tool_calls=[],
            model="test-model",
        ),
        OllamaChatResponse(
            content="",
            tool_calls=[OllamaToolCall(name="get_state", arguments={})],
            model="test-model",
        ),
        OllamaChatResponse(content="Erledigt", tool_calls=[], model="test-model"),
    ]

    mcp = MagicMock()
    mcp.policy = policy
    mcp.call_tool.return_value = NormalizedToolResult(text='{"ok": true}', ok=True)

    with patch(
        "teams_ollama_bridge.agent_loop.McpToolRegistry.discover_ollama_tools",
        return_value=[{"type": "function", "function": {"name": "get_state"}}],
    ):
        loop = AgentLoop(settings, ollama, mcp)
        result = loop.run("Markiere alle Stützen rot", "System")

    assert ollama.chat.call_count == 3
    assert result.answer == "Erledigt"
    assert mcp.call_tool.call_count == 1


def test_agent_loop_stops_at_tool_round_limit(settings: Settings, policy: ToolPolicy) -> None:
    settings.mcp_max_tool_rounds = 1
    settings.mcp_max_tool_calls_total = 8

    ollama = MagicMock(spec=OllamaClient)
    ollama.model_name = "test-model"
    ollama.chat.return_value = OllamaChatResponse(
        content="",
        tool_calls=[OllamaToolCall(name="get_state", arguments={})],
        model="test-model",
    )

    mcp = MagicMock()
    mcp.policy = policy
    mcp.call_tool.return_value = NormalizedToolResult(text='{"ok": true}', ok=True)

    with patch(
        "teams_ollama_bridge.agent_loop.McpToolRegistry.discover_ollama_tools",
        return_value=[],
    ):
        loop = AgentLoop(settings, ollama, mcp)
        result = loop.run("Frage", "System")

    assert "abgebrochen" in result.answer.lower()


def test_ollama_chat_payload_has_no_token(settings: Settings) -> None:
    client = OllamaClient(
        base_url="http://127.0.0.1:11434",
        model="test",
        timeout_seconds=5,
        keep_alive="10m",
        temperature=0.2,
        system_prompt="Test",
        max_output_characters=1000,
    )
    captured: dict[str, Any] = {}

    def _capture(payload: dict[str, Any]) -> dict[str, Any]:
        captured.update(payload)
        return {
            "message": {"role": "assistant", "content": "Hallo"},
        }

    with patch.object(client, "_post_chat", side_effect=_capture):
        client.chat([{"role": "user", "content": "Hi"}], tools=[])

    payload_text = json.dumps(captured)
    assert "Bearer" not in payload_text
    assert "MCP_TOKEN" not in payload_text


def test_env_example_has_no_real_token() -> None:
    from pathlib import Path

    text = (Path(__file__).parent.parent / ".env.example").read_text(encoding="utf-8")
    assert "MCP_TOKEN=" in text
    assert "eyJ" not in text


def test_agent_loop_stops_at_total_tool_call_limit(
    settings: Settings, policy: ToolPolicy
) -> None:
    settings.mcp_max_tool_rounds = 5
    settings.mcp_max_tool_calls_total = 1

    ollama = MagicMock(spec=OllamaClient)
    ollama.model_name = "test-model"
    ollama.chat.side_effect = [
        OllamaChatResponse(
            content="",
            tool_calls=[
                OllamaToolCall(name="get_state", arguments={}),
                OllamaToolCall(name="query_elements", arguments={}),
            ],
            model="test-model",
        ),
    ]

    mcp = MagicMock()
    mcp.policy = policy
    mcp.call_tool.return_value = NormalizedToolResult(text='{"ok": true}', ok=True)

    with patch(
        "teams_ollama_bridge.agent_loop.McpToolRegistry.discover_ollama_tools",
        return_value=[],
    ):
        loop = AgentLoop(settings, ollama, mcp)
        result = loop.run("Frage", "System")

    assert result.answer == (
        "Die CPD-Abfrage wurde abgebrochen, weil zu viele Zwischenschritte erforderlich waren."
    )
    assert mcp.call_tool.call_count == 1


def test_processor_without_mcp_unchanged(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    assert settings.mcp_enabled is False
    write_input_file(settings.input_dir, request_id="no-mcp-001")
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)
    processor.process_file(list(settings.input_dir.glob("*.json"))[0])

    data = json.loads(
        (settings.output_dir / "response_no-mcp-001.json").read_text(encoding="utf-8")
    )
    assert data["status"] == "completed"
    assert "mcp" not in data


def test_processor_output_includes_mcp_metadata(settings, workspace) -> None:
    settings.processor_mode = ProcessorMode.OLLAMA
    settings.mcp_enabled = True
    settings.mcp_token = "test-token"
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    write_input_file(settings.input_dir, request_id="mcp-meta-001")

    loop_result = AgentLoopResult(
        answer="Antwort aus CPD",
        model="test-model",
        processing_duration_ms=42,
        mcp_used=True,
        tools_called=[McpCallRecord(name="get_state", status="completed")],
    )

    with patch("teams_ollama_bridge.processor.AgentLoop") as mock_loop_cls:
        mock_loop_cls.return_value.run.return_value = loop_result
        repo = RequestRepository(settings.database_path)
        processor = RequestProcessor(settings, repo)
        processor.process_file(list(settings.input_dir.glob("*.json"))[0])

    data = json.loads(
        (settings.output_dir / "response_mcp-meta-001.json").read_text(encoding="utf-8")
    )
    assert data["status"] == "completed"
    assert data["mcp"]["enabled"] is True
    assert data["mcp"]["used"] is True
    assert data["mcp"]["toolsCalled"] == [{"name": "get_state", "status": "completed"}]
    assert "test-token" not in json.dumps(data)


def test_mcp_check_cli_disabled(workspace, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("TEAMS_LLM_ROOT", str(workspace / "TeamsLLM"))
    monkeypatch.setenv("MCP_ENABLED", "false")

    exit_code = cmd_mcp_check(argparse.Namespace())
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "MCP aktiviert: False" in captured.out


def test_mcp_check_cli_lists_tools_read_only(
    workspace, monkeypatch: pytest.MonkeyPatch, capsys, policy: ToolPolicy
) -> None:
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("TEAMS_LLM_ROOT", str(workspace / "TeamsLLM"))
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_TOKEN", "secret")

    fake_tools = [
        DiscoveredMcpTool("get_state", "state", {"type": "object"}),
        DiscoveredMcpTool("delete_group", "delete", {"type": "object"}),
    ]

    with patch("teams_ollama_bridge.cli.build_mcp_client") as mock_build:
        mock_client = MagicMock()
        mock_client.list_tools.return_value = fake_tools
        mock_build.return_value = mock_client
        with patch("teams_ollama_bridge.cli.build_tool_policy", return_value=policy):
            exit_code = cmd_mcp_check(argparse.Namespace())

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Gefundene MCP-Tools: 2" in captured.out
    assert "get_state (erlaubt)" in captured.out
    assert "delete_group (blockiert)" in captured.out
    assert "secret" not in captured.out


def test_mcp_check_cli_full_policy(
    workspace, monkeypatch: pytest.MonkeyPatch, capsys, full_policy: ToolPolicy
) -> None:
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("TEAMS_LLM_ROOT", str(workspace / "TeamsLLM"))
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MCP_TOKEN", "secret")

    fake_tools = [
        DiscoveredMcpTool("get_state", "state", {"type": "object"}),
        DiscoveredMcpTool("delete_group", "delete", {"type": "object"}),
    ]

    with patch("teams_ollama_bridge.cli.build_mcp_client") as mock_build:
        mock_client = MagicMock()
        mock_client.list_tools.return_value = fake_tools
        mock_build.return_value = mock_client
        with patch("teams_ollama_bridge.cli.build_tool_policy", return_value=full_policy):
            exit_code = cmd_mcp_check(argparse.Namespace())

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Tool-Policy: full" in captured.out
    assert "get_state (erlaubt)" in captured.out
    assert "delete_group (erlaubt)" in captured.out


@pytest.mark.skipif(
    os.environ.get("RUN_MCP_INTEGRATION_TESTS", "").lower() not in ("1", "true", "yes"),
    reason="Set RUN_MCP_INTEGRATION_TESTS=true for live CPD MCP tests",
)
def test_mcp_integration_live_ping() -> None:
    settings = load_settings()
    if not settings.mcp_enabled or not settings.mcp_token:
        pytest.skip("MCP_ENABLED and MCP_TOKEN required for integration test")
    policy = ToolPolicy.from_settings(
        settings.mcp_tool_policy,
        settings.parsed_mcp_allowed_tools,
        settings.parsed_mcp_blocked_tools,
    )
    client = MCPClient(
        server_url=settings.mcp_server_url,
        token=settings.mcp_token,
        connect_timeout_seconds=settings.mcp_connect_timeout_seconds,
        read_timeout_seconds=settings.mcp_read_timeout_seconds,
        max_result_characters=settings.mcp_max_result_characters,
        log_tool_calls=False,
        log_tool_results=False,
        policy=policy,
    )
    assert client.ping() >= 0
