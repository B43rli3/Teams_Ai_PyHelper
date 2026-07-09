"""Mock-Prozessor für Tests ohne Ollama."""

from __future__ import annotations

from dataclasses import dataclass, field

from teams_ollama_bridge.attachment_types import AttachmentBatchResult, ProcessedAttachment
from teams_ollama_bridge.text_cleaner import truncate_answer


@dataclass(frozen=True)
class ProcessorResult:
    """Ergebnis einer LLM-Verarbeitung."""

    answer: str
    model: str
    processing_duration_ms: int
    attachments_processed: list[ProcessedAttachment] = field(default_factory=list)


class MockProcessor:
    """Simuliert LLM-Antworten für PoC-Tests."""

    def __init__(self, max_output_characters: int) -> None:
        self._max_output_characters = max_output_characters

    def process(
        self,
        message: str,
        attachment_batch: AttachmentBatchResult | None = None,
    ) -> ProcessorResult:
        if attachment_batch and attachment_batch.processed:
            lines = [
                "PoC erfolgreich. Die lokale Python-Anwendung hat die Teams-Nachricht verarbeitet.",
                "",
                "Nachricht:",
                message,
                "",
                "Erkannte Anhänge:",
            ]
            for item in attachment_batch.processed:
                if item.status.value == "processed":
                    if item.kind.value == "image" and item.extracted_characters:
                        lines.append(
                            f"- {item.name}: Bild erkannt, Inhalt beschrieben "
                            f"({item.extracted_characters} Zeichen)"
                        )
                    elif item.extracted_characters is not None:
                        lines.append(
                            f"- {item.name}: erfolgreich gelesen, "
                            f"{item.extracted_characters} Zeichen extrahiert"
                        )
                    else:
                        lines.append(f"- {item.name}: erfolgreich verarbeitet")
                else:
                    error = item.error or item.status.value
                    lines.append(f"- {item.name}: {error}")
            answer = "\n".join(lines)
        else:
            answer = (
                "PoC erfolgreich. Die lokale Python-Anwendung hat folgende Nachricht verarbeitet: "
                f"{message}"
            )
        answer = truncate_answer(answer, self._max_output_characters)
        processed = attachment_batch.processed if attachment_batch else []
        return ProcessorResult(
            answer=answer,
            model="mock",
            processing_duration_ms=10,
            attachments_processed=processed,
        )
