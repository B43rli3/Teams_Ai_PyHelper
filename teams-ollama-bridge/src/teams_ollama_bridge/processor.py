"""Zentrale Request-Verarbeitung."""

from __future__ import annotations

import time
from pathlib import Path

from teams_ollama_bridge.config import Settings
from teams_ollama_bridge.exceptions import (
    BridgeError,
    DuplicateRequestError,
    EmptyMessageError,
    InvalidInputSchemaError,
    InvalidJsonError,
    MessageTooLongError,
    OutputFileExistsError,
    PermanentProcessingError,
    RequestContentMismatchError,
    SQLiteError,
    TemporaryProcessingError,
)
from teams_ollama_bridge.file_service import (
    compute_file_hash,
    load_input_request,
    move_to_archive,
    output_path_for,
    write_output_response,
)
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.mock_processor import MockProcessor, ProcessorResult
from teams_ollama_bridge.models import InputRequest, OutputResponse, ProcessorMode, RequestStatus
from teams_ollama_bridge.ollama_client import OllamaClient
from teams_ollama_bridge.repository import RequestRepository
from teams_ollama_bridge.text_cleaner import clean_message
from teams_ollama_bridge.utils import truncate_filename, utc_now_iso

logger = get_logger(__name__)

TEMPORARY_ERROR_TYPES = {
    "InvalidJsonError",
    "FileNotStableError",
    "TemporaryProcessingError",
    "OllamaConnectionError",
    "OllamaTimeoutError",
    "SQLiteError",
}


class RequestProcessor:
    """Verarbeitet einzelne Input-Dateien end-to-end."""

    def __init__(self, settings: Settings, repository: RequestRepository) -> None:
        self._settings = settings
        self._repository = repository
        self._mock_processor = MockProcessor(settings.llm_max_output_characters)
        self._ollama_client: OllamaClient | None = None
        if settings.processor_mode == ProcessorMode.OLLAMA:
            self._ollama_client = OllamaClient(
                base_url=settings.ollama_base_url,
                model=settings.ollama_model,
                timeout_seconds=settings.ollama_timeout_seconds,
                keep_alive=settings.ollama_keep_alive,
                temperature=settings.ollama_temperature,
                system_prompt=settings.llm_system_prompt,
                max_output_characters=settings.llm_max_output_characters,
            )

    def _log_message_content(self, request_id: str, message: str) -> None:
        if self._settings.log_message_content:
            logger.debug("Nachricht für %s: %s", request_id, message)

    def _invoke_processor(self, cleaned_message: str) -> ProcessorResult:
        if self._settings.processor_mode == ProcessorMode.MOCK:
            return self._mock_processor.process(cleaned_message)
        if self._ollama_client is None:
            raise PermanentProcessingError("Ollama-Client ist nicht konfiguriert.")
        return self._ollama_client.process(cleaned_message)

    def _is_already_completed(self, request_id: str) -> bool:
        record = self._repository.get(request_id)
        if record is None:
            return False
        if record.status not in (RequestStatus.COMPLETED, RequestStatus.ARCHIVED):
            return False
        output_path = output_path_for(self._settings.output_dir, request_id)  # type: ignore[arg-type]
        return output_path.exists()

    def _build_success_response(
        self,
        request: InputRequest,
        result: ProcessorResult,
        source_file: str,
    ) -> OutputResponse:
        return OutputResponse(
            requestId=request.request_id,
            messageId=request.message_id,
            chatId=request.chat_id,
            answer=result.answer,
            status="completed",
            processedAt=utc_now_iso(),
            model=result.model,
            processingDurationMs=result.processing_duration_ms,
            sender=request.sender,
            sourceFile=source_file,
        )

    def _build_failure_response(
        self,
        request: InputRequest,
        error_message: str,
    ) -> OutputResponse:
        return OutputResponse(
            requestId=request.request_id,
            messageId=request.message_id,
            chatId=request.chat_id,
            answer="",
            status="failed",
            processedAt=utc_now_iso(),
            error=error_message,
        )

    def _handle_permanent_failure(
        self,
        path: Path,
        request: InputRequest | None,
        error: BridgeError,
    ) -> None:
        request_id = request.request_id if request else path.stem

        logger.error(
            "Dauerhafter Fehler für %s (%s): %s",
            request_id,
            error.error_type,
            error.user_message,
        )

        if request is not None:
            try:
                self._repository.mark_failed(
                    request.request_id,
                    error.error_type,
                    error.user_message,
                    increment_retry=False,
                )
            except SQLiteError:
                logger.exception("SQLite-Fehler beim Markieren als failed")

            try:
                failure_response = OutputResponse(
                    requestId=request.request_id,
                    messageId=request.message_id,
                    chatId=request.chat_id,
                    answer="",
                    status="failed",
                    processedAt=utc_now_iso(),
                    error=error.user_message,
                )
                output_path = output_path_for(self._settings.output_dir, request.request_id)  # type: ignore[arg-type]
                if not output_path.exists():
                    write_output_response(self._settings.output_dir, failure_response)  # type: ignore[arg-type]
            except OutputFileExistsError:
                logger.warning(
                    "Fehler-Outputdatei existiert bereits für %s", request.request_id
                )
            except BridgeError:
                logger.exception("Fehler-Outputdatei konnte nicht erstellt werden")

        if path.exists():
            move_to_archive(path, self._settings.failed_input_dir)  # type: ignore[arg-type]

    def _handle_retryable_failure(
        self,
        request_id: str,
        error: BridgeError,
    ) -> bool:
        retry_count = self._repository.mark_failed(
            request_id,
            error.error_type,
            error.user_message,
            increment_retry=True,
        )
        logger.warning(
            "Temporärer Fehler für %s (Versuch %d/%d): %s",
            request_id,
            retry_count,
            self._settings.max_process_retries,
            error.user_message,
        )
        if retry_count >= self._settings.max_process_retries:
            return False
        time.sleep(self._settings.retry_delay_seconds)
        return True

    def process_file(self, path: Path) -> bool:
        """Eine Input-Datei verarbeiten. Gibt True bei Erfolg zurück."""
        logger.info("Verarbeite Datei: %s", truncate_filename(path.name))

        request: InputRequest | None = None
        try:
            file_hash = compute_file_hash(path)
            try:
                request = load_input_request(path)
            except (InvalidJsonError, InvalidInputSchemaError) as exc:
                if isinstance(exc, InvalidJsonError):
                    raise TemporaryProcessingError(exc.user_message) from exc
                raise PermanentProcessingError(exc.user_message) from exc

            self._log_message_content(request.request_id, request.message)

            if self._is_already_completed(request.request_id):
                logger.info(
                    "Request %s bereits abgeschlossen, überspringe.",
                    request.request_id,
                )
                if path.exists():
                    move_to_archive(path, self._settings.processed_input_dir)  # type: ignore[arg-type]
                    self._repository.mark_archived(request.request_id)
                raise DuplicateRequestError(
                    f"Request {request.request_id} wurde bereits verarbeitet."
                )

            existing = self._repository.get(request.request_id)
            if existing and existing.input_file_hash and existing.input_file_hash != file_hash:
                raise RequestContentMismatchError(
                    f"Abweichender Inhalt für requestId '{request.request_id}'."
                )

            output_path = output_path_for(self._settings.output_dir, request.request_id)  # type: ignore[arg-type]
            if output_path.exists():
                logger.info(
                    "Outputdatei existiert bereits für %s, überspringe.",
                    request.request_id,
                )
                self._repository.upsert_discovered(
                    request.request_id,
                    request.message_id,
                    request.chat_id,
                    path.name,
                    file_hash,
                )
                self._repository.mark_completed(
                    request.request_id,
                    output_path.name,
                    None,
                    0,
                )
                if path.exists():
                    move_to_archive(path, self._settings.processed_input_dir)  # type: ignore[arg-type]
                    self._repository.mark_archived(request.request_id)
                return False

            self._repository.upsert_discovered(
                request.request_id,
                request.message_id,
                request.chat_id,
                path.name,
                file_hash,
            )

            if not self._repository.try_mark_processing(request.request_id):
                logger.info(
                    "Request %s wird bereits verarbeitet, überspringe.",
                    request.request_id,
                )
                return False

            cleaned = clean_message(request.message, self._settings.llm_max_input_characters)
            result = self._invoke_processor(cleaned)

            response = self._build_success_response(request, result, path.name)
            output_file = write_output_response(self._settings.output_dir, response)  # type: ignore[arg-type]

            self._repository.mark_completed(
                request.request_id,
                output_file.name,
                result.model,
                result.processing_duration_ms,
            )

            move_to_archive(path, self._settings.processed_input_dir)  # type: ignore[arg-type]
            self._repository.mark_archived(request.request_id)

            logger.info(
                "Request %s erfolgreich verarbeitet (%dms, Modus=%s)",
                request.request_id,
                result.processing_duration_ms,
                self._settings.processor_mode.value,
            )
            return True

        except DuplicateRequestError:
            return False

        except (EmptyMessageError, MessageTooLongError, RequestContentMismatchError) as exc:
            if request is not None:
                self._handle_permanent_failure(path, request, exc)
            else:
                self._handle_permanent_failure(path, None, exc)
            return False

        except OutputFileExistsError as exc:
            logger.warning("%s", exc.user_message)
            if request is not None and path.exists():
                move_to_archive(path, self._settings.processed_input_dir)  # type: ignore[arg-type]
                self._repository.mark_archived(request.request_id)
            return False

        except (TemporaryProcessingError, InvalidJsonError) as exc:
            bridge_exc = (
                exc
                if isinstance(exc, BridgeError)
                else TemporaryProcessingError(str(exc))
            )
            if request is not None:
                should_retry = self._handle_retryable_failure(request.request_id, bridge_exc)
                if not should_retry:
                    self._handle_permanent_failure(path, request, bridge_exc)
            return False

        except BridgeError as exc:
            if request is not None and exc.error_type in TEMPORARY_ERROR_TYPES:
                should_retry = self._handle_retryable_failure(request.request_id, exc)
                if not should_retry:
                    self._handle_permanent_failure(path, request, exc)
            elif request is not None:
                self._handle_permanent_failure(path, request, exc)
            else:
                self._handle_permanent_failure(path, None, exc)
            return False

        except Exception as exc:
            permanent_exc = PermanentProcessingError(f"Unerwarteter Fehler: {exc}")
            self._handle_permanent_failure(path, request, permanent_exc)
            return False
