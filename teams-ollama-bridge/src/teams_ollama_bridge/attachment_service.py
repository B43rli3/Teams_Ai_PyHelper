"""Orchestrierung der Attachment-Verarbeitung."""

from __future__ import annotations

from teams_ollama_bridge.attachment_context_builder import AttachmentContextBuilder
from teams_ollama_bridge.attachment_resolver import AttachmentResolver
from teams_ollama_bridge.attachment_types import (
    AttachmentBatchResult,
    AttachmentKind,
    AttachmentProcessStatus,
    ProcessedAttachment,
)
from teams_ollama_bridge.config import Settings
from teams_ollama_bridge.document_extractor import DocumentExtractor
from teams_ollama_bridge.exceptions import (
    AttachmentNotSyncedError,
    AttachmentPathError,
    EncryptedPdfError,
)
from teams_ollama_bridge.file_service import is_file_stable
from teams_ollama_bridge.image_processor import ImageProcessor
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.models import AttachmentInfo, InputRequest
from teams_ollama_bridge.ollama_client import OllamaClient
from teams_ollama_bridge.utils import truncate_filename

logger = get_logger(__name__)


class AttachmentService:
    """Verarbeitet Attachments eines Requests."""

    def __init__(
        self,
        settings: Settings,
        ollama_client: OllamaClient | None = None,
    ) -> None:
        self._settings = settings
        input_dir = settings.input_dir
        if input_dir is None:
            raise ValueError("INPUT_DIR ist nicht konfiguriert.")

        base_dir = settings.attachments_base_dir or input_dir
        self._input_dir = input_dir
        self._resolver = AttachmentResolver(
            input_dir=input_dir,
            attachments_base_dir=base_dir,
            allowed_extensions=settings.parsed_allowed_extensions,
            max_file_size_bytes=settings.attachments_max_file_size_bytes,
            max_files=settings.attachments_max_files,
        )
        self._extractor = DocumentExtractor()
        self._image_processor = ImageProcessor(settings, ollama_client)
        self._context_builder = AttachmentContextBuilder()
        self._total_chars_used = 0

    def check_attachments_stable(self, request: InputRequest) -> None:
        """Prüft, ob alle referenzierten Attachment-Dateien stabil sind."""
        if not self._settings.attachments_enabled or not request.attachments:
            return

        for info in request.attachments[: self._settings.attachments_max_files]:
            if info.status == "not_copied" or not info.local_path or not info.local_path.strip():
                continue
            try:
                path = self._resolver.resolve_local_path(info.local_path)
            except AttachmentPathError:
                continue
            if not path.exists():
                logger.info(
                    "Attachment noch nicht lokal synchronisiert: %s",
                    truncate_filename(info.name or path.name),
                )
                raise AttachmentNotSyncedError(
                    f"Attachment {truncate_filename(info.name or path.name)} "
                    "ist noch nicht lokal verfügbar."
                )
            if not is_file_stable(path, self._settings.file_stable_seconds):
                logger.info(
                    "Attachment noch nicht stabil: %s",
                    truncate_filename(info.name or path.name),
                )
                raise AttachmentNotSyncedError(
                    f"Attachment {truncate_filename(info.name or path.name)} "
                    "ist noch nicht vollständig synchronisiert."
                )

    def process_request(
        self,
        request: InputRequest,
        *,
        treat_missing_as_failed: bool = False,
    ) -> AttachmentBatchResult:
        """Alle Attachments verarbeiten und Prompt-Kontext erzeugen."""
        batch = AttachmentBatchResult()
        if not self._settings.attachments_enabled or not request.attachments:
            return batch

        logger.info(
            "Verarbeite %d Attachment(s) für Request %s",
            min(len(request.attachments), self._settings.attachments_max_files),
            request.request_id,
        )

        self._total_chars_used = 0
        for info in request.attachments[: self._settings.attachments_max_files]:
            processed = self._process_single(info, treat_missing_as_failed=treat_missing_as_failed)
            batch.processed.append(processed)
            if processed.source_path is not None:
                batch.resolved_paths.append(processed.source_path)

        return batch

    def build_prompt(self, message: str, batch: AttachmentBatchResult) -> str:
        if not batch.processed:
            return message
        return self._context_builder.build_user_prompt(message, batch)

    def _remaining_total_chars(self) -> int:
        return max(
            0,
            self._settings.attachments_max_total_extracted_characters - self._total_chars_used,
        )

    def _process_single(
        self,
        info: AttachmentInfo,
        *,
        treat_missing_as_failed: bool = False,
    ) -> ProcessedAttachment:
        display_name = info.name.strip() or "unbenannt"

        if info.status == "not_copied":
            error = info.error or "Die Datei konnte vom Flow nicht kopiert werden."
            logger.info("Attachment nicht kopiert: %s", truncate_filename(display_name))
            return ProcessedAttachment(
                name=display_name,
                kind=AttachmentKind.SKIPPED,
                status=AttachmentProcessStatus.NOT_COPIED,
                error=error,
            )

        if not info.local_path or not info.local_path.strip():
            return ProcessedAttachment(
                name=display_name,
                kind=AttachmentKind.SKIPPED,
                status=AttachmentProcessStatus.FAILED,
                error="Kein lokaler Pfad angegeben.",
            )

        try:
            resolved = self._resolver.resolve_attachment(info)
        except AttachmentPathError as exc:
            logger.warning("Attachment übersprungen (%s): %s", display_name, exc.user_message)
            return ProcessedAttachment(
                name=display_name,
                kind=AttachmentKind.SKIPPED,
                status=AttachmentProcessStatus.FAILED,
                error=exc.user_message,
            )

        if resolved is None:
            if treat_missing_as_failed:
                return ProcessedAttachment(
                    name=display_name,
                    kind=AttachmentKind.SKIPPED,
                    status=AttachmentProcessStatus.FAILED,
                    error="Datei nicht lokal verfügbar oder konnte nicht gelesen werden.",
                )
            return ProcessedAttachment(
                name=display_name,
                kind=AttachmentKind.SKIPPED,
                status=AttachmentProcessStatus.PENDING_SYNC,
                error="Datei lokal noch nicht verfügbar.",
                source_path=None,
            )

        logger.info(
            "Attachment %s: Typ=%s, Größe=%d Bytes",
            truncate_filename(resolved.name),
            resolved.kind.value,
            resolved.file_size_bytes,
        )

        if resolved.kind == AttachmentKind.IMAGE:
            return self._process_image(resolved)
        if resolved.kind == AttachmentKind.DOCUMENT:
            return self._process_document(resolved)
        return ProcessedAttachment(
            name=resolved.name,
            kind=AttachmentKind.SKIPPED,
            status=AttachmentProcessStatus.SKIPPED,
            error=f"Dateityp {resolved.extension} wird nicht unterstützt.",
            source_path=resolved.source_path,
        )

    def _process_document(self, resolved) -> ProcessedAttachment:  # type: ignore[no-untyped-def]
        max_chars = min(
            self._settings.attachments_max_extracted_characters_per_file,
            self._remaining_total_chars(),
        )
        if max_chars <= 0:
            return ProcessedAttachment(
                name=resolved.name,
                kind=AttachmentKind.DOCUMENT,
                status=AttachmentProcessStatus.SKIPPED,
                error="Gesamtlimit für extrahierte Zeichen erreicht.",
                source_path=resolved.source_path,
            )
        try:
            content = self._extractor.extract(resolved.source_path, resolved.extension, max_chars)
        except EncryptedPdfError as exc:
            return ProcessedAttachment(
                name=resolved.name,
                kind=AttachmentKind.DOCUMENT,
                status=AttachmentProcessStatus.FAILED,
                error=exc.user_message,
                source_path=resolved.source_path,
            )
        except Exception as exc:
            return ProcessedAttachment(
                name=resolved.name,
                kind=AttachmentKind.DOCUMENT,
                status=AttachmentProcessStatus.FAILED,
                error=f"Datei konnte nicht gelesen werden: {exc}",
                source_path=resolved.source_path,
            )

        if not content.strip():
            return ProcessedAttachment(
                name=resolved.name,
                kind=AttachmentKind.DOCUMENT,
                status=AttachmentProcessStatus.FAILED,
                error="Kein extrahierbarer Text gefunden.",
                source_path=resolved.source_path,
            )

        self._total_chars_used += len(content)
        section = self._wrap_content(resolved.name, content)
        if self._settings.log_message_content:
            logger.debug("Extrahiert aus %s: %s...", resolved.name, content[:200])

        logger.info(
            "Attachment %s extrahiert: %d Zeichen",
            truncate_filename(resolved.name),
            len(content),
        )
        return ProcessedAttachment(
            name=resolved.name,
            kind=AttachmentKind.DOCUMENT,
            status=AttachmentProcessStatus.PROCESSED,
            extracted_characters=len(content),
            prompt_section=section,
            source_path=resolved.source_path,
        )

    def _process_image(self, resolved) -> ProcessedAttachment:  # type: ignore[no-untyped-def]
        try:
            description = self._image_processor.process(resolved.source_path)
        except Exception as exc:
            return ProcessedAttachment(
                name=resolved.name,
                kind=AttachmentKind.IMAGE,
                status=AttachmentProcessStatus.FAILED,
                error=f"Bild konnte nicht verarbeitet werden: {exc}",
                source_path=resolved.source_path,
            )

        mode = self._settings.image_processing_mode.value
        logger.info(
            "Bild %s verarbeitet (Modus=%s)",
            truncate_filename(resolved.name),
            mode,
        )
        section = (
            f"--- BEGIN BILD {resolved.name} ---\n{description}\n--- END BILD {resolved.name} ---"
        )
        return ProcessedAttachment(
            name=resolved.name,
            kind=AttachmentKind.IMAGE,
            status=AttachmentProcessStatus.PROCESSED,
            extracted_characters=len(description),
            prompt_section=section,
            source_path=resolved.source_path,
        )

    @staticmethod
    def _wrap_content(filename: str, content: str) -> str:
        return (
            f"--- BEGIN DATEI {filename} ---\n{content}\n--- END DATEI {filename} ---"
        )
