"""Prompt-Zusammenbau mit Attachment-Kontext."""

from __future__ import annotations

from teams_ollama_bridge.attachment_types import AttachmentBatchResult, ProcessedAttachment


class AttachmentContextBuilder:
    """Baut strukturierten LLM-Prompt aus Nachricht und Attachments."""

    def build_user_prompt(self, message: str, batch: AttachmentBatchResult) -> str:
        sections: list[str] = [f"Nutzeranfrage:\n{message}"]

        if batch.processed or batch.prompt_sections:
            sections.append("Angehängte Dateien:")
            for index, item in enumerate(batch.processed, start=1):
                sections.append(self._format_attachment(index, item))

        sections.append(
            "Aufgabe:\n"
            "Beantworte die Nutzeranfrage unter Berücksichtigung der bereitgestellten "
            "Dateiinhalte. Wenn Dateiinhalte fehlen oder nicht verarbeitet werden konnten, "
            "weise transparent darauf hin."
        )
        return "\n\n".join(sections)

    def _format_attachment(self, index: int, item: ProcessedAttachment) -> str:
        lines = [f"{index}. {item.name}", f"   Typ: {item.kind.value}"]
        if item.status.value == "processed":
            lines.append("   Status: erfolgreich extrahiert")
            if item.prompt_section:
                lines.append("   Inhalt:")
                lines.append(item.prompt_section)
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
