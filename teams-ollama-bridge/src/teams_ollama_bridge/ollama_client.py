"""Ollama REST-API Client."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from teams_ollama_bridge.exceptions import (
    OllamaConnectionError,
    OllamaResponseError,
    OllamaTimeoutError,
    TemporaryProcessingError,
)
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.mock_processor import ProcessorResult
from teams_ollama_bridge.text_cleaner import truncate_answer

logger = get_logger(__name__)


@dataclass(frozen=True)
class OllamaToolCall:
    """Ein von Ollama angeforderter Tool-Aufruf."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class OllamaChatResponse:
    """Antwort eines Ollama-Chat-Aufrufs mit optionalem Tool Calling."""

    content: str | None
    tool_calls: list[OllamaToolCall] = field(default_factory=list)
    model: str = ""


class OllamaClient:
    """HTTP-Client für die lokale Ollama-API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        keep_alive: str,
        temperature: float,
        system_prompt: str,
        max_output_characters: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._keep_alive = keep_alive
        self._temperature = temperature
        self._system_prompt = system_prompt
        self._max_output_characters = max_output_characters

    @property
    def model_name(self) -> str:
        return self._model

    def _chat_url(self) -> str:
        return f"{self._base_url}/api/chat"

    def _tags_url(self) -> str:
        return f"{self._base_url}/api/tags"

    def check_connection(self) -> bool:
        """Prüfen, ob Ollama erreichbar ist."""
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(self._tags_url())
                return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    @retry(
        retry=retry_if_exception_type(TemporaryProcessingError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(self._chat_url(), json=payload)
        except httpx.ConnectError as exc:
            raise OllamaConnectionError("Ollama ist nicht erreichbar.") from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError("Ollama-Anfrage hat das Zeitlimit überschritten.") from exc
        except httpx.HTTPError as exc:
            raise TemporaryProcessingError(f"Netzwerkfehler bei Ollama: {exc}") from exc

        if response.status_code >= 500:
            raise TemporaryProcessingError(
                f"Ollama-Serverfehler (HTTP {response.status_code})."
            )
        if response.status_code >= 400:
            raise OllamaResponseError(
                f"Ungültige Ollama-Anfrage (HTTP {response.status_code})."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaResponseError("Ollama-Antwort ist kein gültiges JSON.") from exc

        if not isinstance(data, dict):
            raise OllamaResponseError("Ollama-Antwort hat unerwartetes Format.")

        return data

    def process(self, message: str) -> ProcessorResult:
        """Nachricht an Ollama senden und Antwort extrahieren."""
        return self.process_with_prompt(message)

    def process_with_prompt(self, prompt: str, system_prompt: str | None = None) -> ProcessorResult:
        """Nachricht mit optionalem angepassten Systemprompt senden."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt or self._system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"temperature": self._temperature},
        }

        start = time.perf_counter()
        data = self._post_chat(payload)
        duration_ms = int((time.perf_counter() - start) * 1000)

        message_obj = data.get("message")
        if not isinstance(message_obj, dict):
            raise OllamaResponseError("Ollama-Antwort enthält kein message-Feld.")

        content = message_obj.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaResponseError("Ollama-Antwort ist leer.")

        answer = truncate_answer(content.strip(), self._max_output_characters)
        logger.info(
            "Ollama-Antwort erhalten (Modell=%s, Dauer=%dms)",
            self._model,
            duration_ms,
        )
        return ProcessorResult(
            answer=answer,
            model=self._model,
            processing_duration_ms=duration_ms,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        think: bool = False,
    ) -> OllamaChatResponse:
        """Multi-Turn-Chat mit optionalem Tool Calling."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"temperature": self._temperature},
        }
        if tools:
            payload["tools"] = tools
        if think:
            payload["think"] = True

        start = time.perf_counter()
        data = self._post_chat(payload)
        duration_ms = int((time.perf_counter() - start) * 1000)

        message_obj = data.get("message")
        if not isinstance(message_obj, dict):
            raise OllamaResponseError("Ollama-Antwort enthält kein message-Feld.")

        content = message_obj.get("content")
        content_str = content if isinstance(content, str) else None

        tool_calls: list[OllamaToolCall] = []
        raw_calls = message_obj.get("tool_calls")
        if isinstance(raw_calls, list):
            for item in raw_calls:
                if not isinstance(item, dict):
                    continue
                function = item.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if not isinstance(name, str):
                    continue
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                tool_calls.append(OllamaToolCall(name=name, arguments=arguments))

        logger.info(
            "Ollama-Chat-Antwort (Modell=%s, Dauer=%dms, tool_calls=%d)",
            self._model,
            duration_ms,
            len(tool_calls),
        )
        return OllamaChatResponse(
            content=content_str,
            tool_calls=tool_calls,
            model=self._model,
        )

    def analyze_image(
        self,
        model: str,
        prompt: str,
        image_base64: str,
        timeout_seconds: float,
    ) -> str:
        """Bild über Ollama Vision analysieren."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64],
                }
            ],
            "stream": False,
        }
        original_timeout = self._timeout_seconds
        self._timeout_seconds = timeout_seconds
        try:
            data = self._post_chat(payload)
        finally:
            self._timeout_seconds = original_timeout

        message_obj = data.get("message")
        if not isinstance(message_obj, dict):
            raise OllamaResponseError("Vision-Antwort enthält kein message-Feld.")
        content = message_obj.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaResponseError("Vision-Antwort ist leer.")
        return content.strip()
