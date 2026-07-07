"""Tests für Ollama-Client."""

from __future__ import annotations

import httpx
import pytest
import respx

from teams_ollama_bridge.exceptions import OllamaTimeoutError
from teams_ollama_bridge.ollama_client import OllamaClient


@pytest.fixture
def client() -> OllamaClient:
    return OllamaClient(
        base_url="http://127.0.0.1:11434",
        model="qwen3:14b",
        timeout_seconds=5.0,
        keep_alive="10m",
        temperature=0.2,
        system_prompt="Test",
        max_output_characters=20000,
    )


@respx.mock
def test_ollama_request_stream_false(client: OllamaClient) -> None:
    route = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "Antwort vom Modell."},
                "thinking": "interner Gedanke",
            },
        )
    )
    result = client.process("Testfrage")
    assert route.called
    request_json = route.calls[0].request.content
    assert request_json is not None
    assert b'"stream": false' in request_json or b'"stream":false' in request_json
    assert result.answer == "Antwort vom Modell."
    assert "interner" not in result.answer


@respx.mock
def test_ollama_reads_message_content(client: OllamaClient) -> None:
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={"message": {"content": "Hallo aus Ollama"}},
        )
    )
    result = client.process("Hi")
    assert result.answer == "Hallo aus Ollama"


@respx.mock
def test_ollama_thinking_field_ignored(client: OllamaClient) -> None:
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "message": {"content": "Finale Antwort"},
                "thinking": "Sollte ignoriert werden",
            },
        )
    )
    result = client.process("Frage")
    assert result.answer == "Finale Antwort"


@respx.mock
def test_ollama_timeout_temporary(client: OllamaClient) -> None:
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    with pytest.raises(OllamaTimeoutError):
        client.process("Test")
