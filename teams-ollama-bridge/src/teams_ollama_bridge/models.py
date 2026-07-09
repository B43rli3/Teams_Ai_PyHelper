"""Pydantic-Datenmodelle für Input und Output."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequestStatus(StrEnum):
    """Statuswerte in der SQLite-Datenbank."""

    DISCOVERED = "discovered"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class ProcessorMode(StrEnum):
    """Verfügbare Prozessor-Modi."""

    MOCK = "mock"
    OLLAMA = "ollama"


class ImageProcessingMode(StrEnum):
    """Bildverarbeitungsmodus."""

    METADATA = "metadata"
    OLLAMA_VISION = "ollama_vision"


class AttachmentInfo(BaseModel):
    """Attachment-Metadaten aus dem Power-Automate-Flow."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str = ""
    content_type: str | None = Field(default=None, alias="contentType")
    content_url: str | None = Field(default=None, alias="contentUrl")
    local_path: str | None = Field(default=None, alias="localPath")
    status: str | None = None
    error: str | None = None


class AttachmentProcessedInfo(BaseModel):
    """Attachment-Status in der Output-JSON."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    status: str
    kind: str
    extracted_characters: int | None = Field(default=None, alias="extractedCharacters")
    error: str | None = None


class InputRequest(BaseModel):
    """Input-JSON aus dem Power-Automate-Flow."""

    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(alias="requestId", min_length=1)
    message_id: str = Field(alias="messageId", min_length=1)
    chat_id: str = Field(alias="chatId", min_length=1)
    message: str = Field(min_length=1)
    sender: str | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    attachments: list[AttachmentInfo] = Field(default_factory=list)

    @field_validator("request_id", "message_id", "chat_id", "message")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Feld darf nicht leer sein.")
        return stripped

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> InputRequest:
        """Input aus einem JSON-Dictionary erstellen."""
        return cls.model_validate(data)


class OutputResponse(BaseModel):
    """Output-JSON für den Power-Automate-Flow."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(alias="requestId")
    message_id: str = Field(alias="messageId")
    chat_id: str = Field(alias="chatId")
    answer: str
    status: Literal["completed", "failed"]
    processed_at: str = Field(alias="processedAt")
    model: str | None = None
    processing_duration_ms: int | None = Field(default=None, alias="processingDurationMs")
    sender: str | None = None
    source_file: str | None = Field(default=None, alias="sourceFile")
    error: str | None = None
    attachments_processed: list[AttachmentProcessedInfo] | None = Field(
        default=None, alias="attachmentsProcessed"
    )

    def to_json_dict(self) -> dict[str, Any]:
        """Als Dictionary für JSON-Serialisierung."""
        return self.model_dump(by_alias=True, exclude_none=True)
