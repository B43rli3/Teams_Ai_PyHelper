"""Prompt-Zusammenbau mit Attachment-Kontext."""

from __future__ import annotations

from teams_ollama_bridge.attachment_types import AttachmentBatchResult, ProcessedAttachment
from teams_ollama_bridge.logging_config import get_logger

logger = get_logger(__name__)

_TASK_SECTION = (
    "Aufgabe:\n"
    "Beantworte die Nutzeranfrage unter Berücksichtigung der bereitgestellten "
    "Dateiinhalte. Wenn Dateiinhalte fehlen oder nicht verarbeitet werden konnten, "
    "weise transparent darauf hin."
)
_TRUNCATION_NOTE = (
    "\n[Hinweis: Inhalt wurde aufgrund der Eingabelängenbegrenzung gekürzt.]"
)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= len(_TRUNCATION_NOTE):
        return text[:max_chars]
    return text[: max_chars - len(_TRUNCATION_NOTE)].rstrip() + _TRUNCATION_NOTE


class AttachmentContextBuilder:
    """Baut strukturierten LLM-Prompt aus Nachricht und Attachments."""

    def build_user_prompt(
        self,
        message: str,
        batch: AttachmentBatchResult,
        *,
        max_chars: int | None = None,
    ) -> str:
        if not batch.processed and not batch.prompt_sections:
            prompt = f"Nutzeranfrage:\n{message}\n\n{_TASK_SECTION}"
            if max_chars is not None and len(prompt) > max_chars:
                message_budget = max_chars - len(f"Nutzeranfrage:\n\n\n{_TASK_SECTION}")
                message = _truncate_text(message, max(0, message_budget))
                prompt = f"Nutzeranfrage:\n{message}\n\n{_TASK_SECTION}"
            return prompt

        attachment_blocks = [
            self._format_attachment(index, item)
            for index, item in enumerate(batch.processed, start=1)
        ]
        prompt = (
            f"Nutzeranfrage:\n{message}\n\n"
            f"Angehängte Dateien:\n"
            f"{chr(10).join(attachment_blocks)}\n\n"
            f"{_TASK_SECTION}"
        )

        if max_chars is None or len(prompt) <= max_chars:
            return prompt

        prompt = self._fit_prompt_to_limit(message, batch.processed, max_chars)
        if len(prompt) > max_chars:
            prompt = _truncate_text(prompt, max_chars)
        logger.warning(
            "LLM-Prompt auf %d Zeichen gekürzt (Limit=%d).",
            len(prompt),
            max_chars,
        )
        return prompt

    def _assemble_prompt(
        self,
        message: str,
        items: list[ProcessedAttachment],
        bodies: list[str],
    ) -> str:
        return (
            f"Nutzeranfrage:\n{message}\n\n"
            f"Angehängte Dateien:\n"
            f"{self._format_attachments_with_bodies(items, bodies)}\n\n"
            f"{_TASK_SECTION}"
        )

    def _fit_prompt_to_limit(
        self,
        message: str,
        items: list[ProcessedAttachment],
        max_chars: int,
    ) -> str:
        """Prompt auf max_chars begrenzen, primär durch Kürzen der Dateiinhalte."""
        original_bodies = [item.prompt_section for item in items if item.prompt_section]
        if not original_bodies:
            return self._assemble_prompt(message, items, [])

        truncated_bodies = list(original_bodies)
        prompt = self._assemble_prompt(message, items, truncated_bodies)

        while len(prompt) > max_chars and any(len(body) > 0 for body in truncated_bodies):
            index = max(range(len(truncated_bodies)), key=lambda i: len(truncated_bodies[i]))
            current_len = len(truncated_bodies[index])
            if current_len <= 1:
                truncated_bodies[index] = ""
            else:
                truncated_bodies[index] = _truncate_text(
                    truncated_bodies[index],
                    max(1, int(current_len * 0.85)),
                )
            prompt = self._assemble_prompt(message, items, truncated_bodies)

        if len(prompt) > max_chars:
            prompt = (
                f"Nutzeranfrage:\n{message}\n\n"
                f"Angehängte Dateien:\n"
                f"{self._format_attachments_without_content(items)}\n\n"
                f"{_TASK_SECTION}"
            )

        return prompt

    def _format_attachments_without_content(self, items: list[ProcessedAttachment]) -> str:
        return "\n".join(
            self._format_attachment(index, item, include_content=False)
            for index, item in enumerate(items, start=1)
        )

    def _format_attachments_with_bodies(
        self,
        items: list[ProcessedAttachment],
        bodies: list[str],
    ) -> str:
        blocks: list[str] = []
        body_index = 0
        for index, item in enumerate(items, start=1):
            body = None
            if item.prompt_section:
                body = bodies[body_index]
                body_index += 1
            blocks.append(self._format_attachment(index, item, content_override=body))
        return "\n".join(blocks)

    def _format_attachment(
        self,
        index: int,
        item: ProcessedAttachment,
        *,
        include_content: bool = True,
        content_override: str | None = None,
    ) -> str:
        lines = [f"{index}. {item.name}", f"   Typ: {item.kind.value}"]
        if item.status.value == "processed":
            lines.append("   Status: erfolgreich extrahiert")
            content = content_override if content_override is not None else item.prompt_section
            if include_content and content:
                lines.append("   Inhalt:")
                lines.append(content)
        elif item.status.value == "not_copied":
            lines.append("   Status: nicht kopiert")
            if item.error:
                lines.append(f"   Hinweis: {item.error}")
        else:
            lines.append(f"   Status: {item.status.value}")
            if item.error:
                lines.append(f"   Hinweis: {item.error}")
        return "\n".join(lines)

    @staticmethod
    def attachment_system_prompt_suffix() -> str:
        return (
            "Antworte auf Deutsch. Nutze nur die bereitgestellten Inhalte und allgemeines "
            "Wissen, sofern sinnvoll. Wenn eine Datei nicht gelesen werden konnte, sage das "
            "transparent. Erfinde keine Inhalte aus nicht lesbaren Dateien. Gib keine internen "
            "Dateipfade aus. Gib keine Tokens, JSON-Rohdaten oder technischen Debugdetails aus. "
            "Wenn die Anfrage eine Zusammenfassung verlangt, strukturiere die Antwort kurz und "
            "verständlich."
        )
