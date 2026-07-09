"""Sichere Auflösung lokaler Attachment-Pfade."""

from __future__ import annotations

from pathlib import Path

from teams_ollama_bridge.attachment_types import AttachmentKind, ResolvedAttachment
from teams_ollama_bridge.exceptions import AttachmentPathError
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.models import AttachmentInfo
from teams_ollama_bridge.utils import truncate_filename

logger = get_logger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DOCUMENT_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx", ".xlsx"}


class AttachmentResolver:
    """Löst relative localPath-Werte zu sicheren lokalen Pfaden auf."""

    def __init__(
        self,
        input_dir: Path,
        attachments_base_dir: Path,
        allowed_extensions: set[str],
        max_file_size_bytes: int,
        max_files: int,
    ) -> None:
        self._input_dir = input_dir.resolve()
        self._attachments_base_dir = attachments_base_dir.resolve()
        self._allowed_extensions = {ext.lower() for ext in allowed_extensions}
        self._max_file_size_bytes = max_file_size_bytes
        self._max_files = max_files

    def _ensure_within_input_dir(self, resolved: Path) -> Path:
        try:
            resolved.relative_to(self._input_dir)
        except ValueError as exc:
            raise AttachmentPathError(
                "Attachment-Pfad liegt außerhalb des erlaubten Inputordners."
            ) from exc
        return resolved

    def resolve_local_path(self, local_path: str) -> Path:
        """Relativen localPath sicher auflösen."""
        stripped = local_path.strip()
        if not stripped:
            raise AttachmentPathError("Attachment-localPath ist leer.")

        raw = Path(stripped)
        if raw.is_absolute() or (len(stripped) > 1 and stripped[1] == ":"):
            raise AttachmentPathError("Absolute Attachment-Pfade sind nicht erlaubt.")

        if ".." in raw.parts:
            raise AttachmentPathError("Pfad-Traversal in localPath ist nicht erlaubt.")

        candidate = (self._attachments_base_dir / raw).resolve()
        return self._ensure_within_input_dir(candidate)

    def classify_extension(self, extension: str) -> AttachmentKind:
        ext = extension.lower()
        if ext in IMAGE_EXTENSIONS:
            return AttachmentKind.IMAGE
        if ext in DOCUMENT_EXTENSIONS:
            return AttachmentKind.DOCUMENT
        return AttachmentKind.SKIPPED

    def is_allowed_extension(self, extension: str) -> bool:
        return extension.lower() in self._allowed_extensions

    def resolve_attachment(self, info: AttachmentInfo) -> ResolvedAttachment | None:
        """Attachment auflösen und validieren. None wenn not_copied ohne Pfad."""
        if info.status == "not_copied" or not info.local_path or not info.local_path.strip():
            return None

        path = self.resolve_local_path(info.local_path)
        if not path.exists():
            return None
        if not path.is_file():
            raise AttachmentPathError(f"Attachment ist keine Datei: {truncate_filename(path.name)}")

        size = path.stat().st_size
        if size > self._max_file_size_bytes:
            raise AttachmentPathError(
                f"Datei {truncate_filename(info.name or path.name)} "
                "überschreitet die maximale Größe."
            )

        extension = path.suffix.lower()
        if not self.is_allowed_extension(extension):
            raise AttachmentPathError(
                f"Dateityp {extension} ist nicht erlaubt."
            )

        name = info.name.strip() if info.name.strip() else path.name
        return ResolvedAttachment(
            name=name,
            source_path=path,
            extension=extension,
            file_size_bytes=size,
            kind=self.classify_extension(extension),
        )

    def resolve_batch(self, attachments: list[AttachmentInfo]) -> list[ResolvedAttachment]:
        """Mehrere Attachments auflösen (begrenzt durch max_files)."""
        if len(attachments) > self._max_files:
            logger.warning(
                "Mehr als %d Attachments angegeben, nur die ersten %d werden verarbeitet.",
                self._max_files,
                self._max_files,
            )
        limited = attachments[: self._max_files]
        resolved: list[ResolvedAttachment] = []
        for info in limited:
            item = self.resolve_attachment(info)
            if item is not None:
                resolved.append(item)
        return resolved
