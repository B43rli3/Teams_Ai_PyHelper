"""Mock-Prozessor für Tests ohne Ollama."""

from __future__ import annotations

from dataclasses import dataclass

from teams_ollama_bridge.text_cleaner import truncate_answer


@dataclass(frozen=True)
class ProcessorResult:
    """Ergebnis einer LLM-Verarbeitung."""

    answer: str
    model: str
    processing_duration_ms: int


class MockProcessor:
    """Simuliert LLM-Antworten für PoC-Tests."""

    def __init__(self, max_output_characters: int) -> None:
        self._max_output_characters = max_output_characters

    def process(self, message: str) -> ProcessorResult:
        answer = (
            "PoC erfolgreich. Die lokale Python-Anwendung hat folgende Nachricht verarbeitet: "
            f"{message}"
        )
        answer = truncate_answer(answer, self._max_output_characters)
        return ProcessorResult(
            answer=answer,
            model="mock",
            processing_duration_ms=10,
        )
