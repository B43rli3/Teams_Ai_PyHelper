"""Tests für Prompt-Längenbegrenzung mit Attachments."""

from __future__ import annotations

from pathlib import Path

from teams_ollama_bridge.attachment_context_builder import AttachmentContextBuilder
from teams_ollama_bridge.attachment_service import AttachmentService
from teams_ollama_bridge.attachment_types import (
    AttachmentBatchResult,
    AttachmentKind,
    AttachmentProcessStatus,
    ProcessedAttachment,
)
from teams_ollama_bridge.models import AttachmentInfo, InputRequest


def test_prompt_truncated_to_llm_max(settings, workspace: Path) -> None:
    files_dir = settings.input_dir / "files"
    long_text = "Wort " * 5000
    (files_dir / "long.txt").write_text(long_text, encoding="utf-8")
    settings.llm_max_input_characters = 5000
    settings.attachments_max_extracted_characters_per_file = 30000
    settings.attachments_max_total_extracted_characters = 60000

    service = AttachmentService(settings)
    request = InputRequest(
        requestId="long-prompt",
        messageId="m",
        chatId="c",
        message="Bitte fasse zusammen.",
        attachments=[AttachmentInfo(name="long.txt", localPath="files/long.txt")],
    )
    batch = service.process_request(request)
    prompt = service.build_prompt(
        request.message,
        batch,
        max_chars=settings.llm_max_input_characters,
    )

    assert len(prompt) <= settings.llm_max_input_characters
    assert "Nutzeranfrage:" in prompt


def test_context_builder_respects_max_chars() -> None:
    builder = AttachmentContextBuilder()
    batch = AttachmentBatchResult(
        processed=[
            ProcessedAttachment(
                name="doc.pdf",
                kind=AttachmentKind.DOCUMENT,
                status=AttachmentProcessStatus.PROCESSED,
                prompt_section=(
                    "--- BEGIN DATEI doc.pdf ---\n"
                    + ("Inhalt " * 4000)
                    + "\n--- END DATEI doc.pdf ---"
                ),
            )
        ]
    )
    prompt = builder.build_user_prompt("Kurze Frage", batch, max_chars=3000)
    assert len(prompt) <= 3000
