"""Interne Typen für Attachment-Verarbeitung."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class AttachmentKind(StrEnum):
    """Art des Attachments."""

    DOCUMENT = "document"
    IMAGE = "image"
    SKIPPED = "skipped"


class AttachmentProcessStatus(StrEnum):
    """Verarbeitungsstatus eines Attachments."""

    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_COPIED = "not_copied"
    PENDING_SYNC = "pending_sync"


@dataclass(frozen=True)
class ResolvedAttachment:
    """Aufgelöstes lokales Attachment."""

    name: str
    source_path: Path
    extension: str
    file_size_bytes: int
    kind: AttachmentKind


@dataclass
class ProcessedAttachment:
    """Ergebnis der Verarbeitung eines Attachments."""

    name: str
    kind: AttachmentKind
    status: AttachmentProcessStatus
    extracted_characters: int | None = None
    error: str | None = None
    prompt_section: str = ""
    source_path: Path | None = None


@dataclass
class AttachmentBatchResult:
    """Gesamtergebnis aller Attachments eines Requests."""

    prompt_sections: list[str] = field(default_factory=list)
    processed: list[ProcessedAttachment] = field(default_factory=list)
    pending_sync: bool = False
    resolved_paths: list[Path] = field(default_factory=list)

    @property
    def has_attachments(self) -> bool:
        return bool(self.processed) or bool(self.prompt_sections)
