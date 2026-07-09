"""SQLite-Repository für Request-Status."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from teams_ollama_bridge.attachment_types import ProcessedAttachment
from teams_ollama_bridge.exceptions import SQLiteError
from teams_ollama_bridge.models import RequestStatus
from teams_ollama_bridge.utils import utc_now, utc_now_iso


@dataclass(frozen=True)
class AttachmentRecord:
    """Ein Datensatz aus der request_attachments-Tabelle."""

    id: int
    request_id: str
    name: str
    local_path: str | None
    resolved_path: str | None
    status: str
    kind: str | None
    file_size_bytes: int | None
    extracted_characters: int | None
    error_message: str | None
    created_at: str | None
    processed_at: str | None


@dataclass(frozen=True)
class RequestRecord:
    """Ein Datensatz aus der requests-Tabelle."""

    request_id: str
    message_id: str | None
    chat_id: str | None
    input_filename: str | None
    input_file_hash: str | None
    status: RequestStatus
    retry_count: int
    created_at: str | None
    started_at: str | None
    completed_at: str | None
    output_filename: str | None
    model: str | None
    processing_duration_ms: int | None
    error_type: str | None
    error_message: str | None


class RequestRepository:
    """SQLite-Zugriff für Request-Status und Deduplizierung."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._database_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise SQLiteError(f"SQLite-Fehler: {exc}") from exc
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    message_id TEXT,
                    chat_id TEXT,
                    input_filename TEXT,
                    input_file_hash TEXT,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    output_filename TEXT,
                    model TEXT,
                    processing_duration_ms INTEGER,
                    error_type TEXT,
                    error_message TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS request_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    name TEXT,
                    local_path TEXT,
                    resolved_path TEXT,
                    status TEXT,
                    kind TEXT,
                    file_size_bytes INTEGER,
                    extracted_characters INTEGER,
                    error_message TEXT,
                    created_at TEXT,
                    processed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_request_attachments_request_id
                ON request_attachments(request_id)
                """
            )

    def _row_to_attachment(self, row: sqlite3.Row) -> AttachmentRecord:
        return AttachmentRecord(
            id=row["id"],
            request_id=row["request_id"],
            name=row["name"],
            local_path=row["local_path"],
            resolved_path=row["resolved_path"],
            status=row["status"],
            kind=row["kind"],
            file_size_bytes=row["file_size_bytes"],
            extracted_characters=row["extracted_characters"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            processed_at=row["processed_at"],
        )

    def _row_to_record(self, row: sqlite3.Row) -> RequestRecord:
        return RequestRecord(
            request_id=row["request_id"],
            message_id=row["message_id"],
            chat_id=row["chat_id"],
            input_filename=row["input_filename"],
            input_file_hash=row["input_file_hash"],
            status=RequestStatus(row["status"]),
            retry_count=row["retry_count"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            output_filename=row["output_filename"],
            model=row["model"],
            processing_duration_ms=row["processing_duration_ms"],
            error_type=row["error_type"],
            error_message=row["error_message"],
        )

    def get(self, request_id: str) -> RequestRecord | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def upsert_discovered(
        self,
        request_id: str,
        message_id: str,
        chat_id: str,
        input_filename: str,
        input_file_hash: str,
    ) -> RequestRecord:
        now = utc_now_iso()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO requests (
                        request_id, message_id, chat_id, input_filename,
                        input_file_hash, status, retry_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        request_id,
                        message_id,
                        chat_id,
                        input_filename,
                        input_file_hash,
                        RequestStatus.DISCOVERED.value,
                        now,
                    ),
                )
            else:
                if existing["input_file_hash"] and existing["input_file_hash"] != input_file_hash:
                    from teams_ollama_bridge.exceptions import RequestContentMismatchError

                    raise RequestContentMismatchError(
                        f"Abweichender Inhalt für requestId '{request_id}'."
                    )
                conn.execute(
                    """
                    UPDATE requests
                    SET message_id = ?, chat_id = ?, input_filename = ?,
                        input_file_hash = ?, status = ?
                    WHERE request_id = ? AND status IN (?, ?)
                    """,
                    (
                        message_id,
                        chat_id,
                        input_filename,
                        input_file_hash,
                        RequestStatus.DISCOVERED.value,
                        request_id,
                        RequestStatus.DISCOVERED.value,
                        RequestStatus.FAILED.value,
                    ),
                )
        record = self.get(request_id)
        if record is None:
            raise SQLiteError(f"Request '{request_id}' konnte nicht gespeichert werden.")
        return record

    def try_mark_processing(self, request_id: str) -> bool:
        """Atomar als processing markieren. Gibt False zurück, wenn bereits aktiv."""
        now = utc_now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE requests
                SET status = ?, started_at = ?
                WHERE request_id = ?
                  AND status IN (?, ?)
                """,
                (
                    RequestStatus.PROCESSING.value,
                    now,
                    request_id,
                    RequestStatus.DISCOVERED.value,
                    RequestStatus.FAILED.value,
                ),
            )
            return cursor.rowcount == 1

    def mark_completed(
        self,
        request_id: str,
        output_filename: str,
        model: str | None,
        processing_duration_ms: int,
    ) -> None:
        now = utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE requests
                SET status = ?, completed_at = ?, output_filename = ?,
                    model = ?, processing_duration_ms = ?,
                    error_type = NULL, error_message = NULL
                WHERE request_id = ?
                """,
                (
                    RequestStatus.COMPLETED.value,
                    now,
                    output_filename,
                    model,
                    processing_duration_ms,
                    request_id,
                ),
            )

    def mark_failed(
        self,
        request_id: str,
        error_type: str,
        error_message: str,
        increment_retry: bool = True,
    ) -> int:
        """Als fehlgeschlagen markieren. Gibt neuen retry_count zurück."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT retry_count FROM requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise SQLiteError(f"Request '{request_id}' nicht gefunden.")
            retry_count = row["retry_count"]
            if increment_retry:
                retry_count += 1
            status = (
                RequestStatus.FAILED.value
                if retry_count >= 0
                else RequestStatus.DISCOVERED.value
            )
            conn.execute(
                """
                UPDATE requests
                SET status = ?, retry_count = ?, error_type = ?, error_message = ?
                WHERE request_id = ?
                """,
                (status, retry_count, error_type, error_message, request_id),
            )
        return int(retry_count)

    def mark_archived(self, request_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "UPDATE requests SET status = ? WHERE request_id = ?",
                (RequestStatus.ARCHIVED.value, request_id),
            )

    def reset_failed_to_discovered(self, request_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE requests
                SET status = ?, error_type = NULL, error_message = NULL
                WHERE request_id = ? AND status = ?
                """,
                (RequestStatus.DISCOVERED.value, request_id, RequestStatus.FAILED.value),
            )
            return cursor.rowcount == 1

    def release_stale_processing(self, stale_minutes: int) -> int:
        """Alte processing-Einträge wieder freigeben."""
        cutoff = (utc_now() - timedelta(minutes=stale_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._connection() as conn:
            cursor = conn.execute(
                """
                UPDATE requests
                SET status = ?
                WHERE status = ? AND started_at IS NOT NULL AND started_at < ?
                """,
                (
                    RequestStatus.DISCOVERED.value,
                    RequestStatus.PROCESSING.value,
                    cutoff,
                ),
            )
            return cursor.rowcount

    def list_pending_and_failed(self) -> list[RequestRecord]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM requests
                WHERE status IN (?, ?, ?)
                ORDER BY created_at ASC
                """,
                (
                    RequestStatus.DISCOVERED.value,
                    RequestStatus.PROCESSING.value,
                    RequestStatus.FAILED.value,
                ),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_failed(self) -> list[RequestRecord]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM requests WHERE status = ? ORDER BY created_at ASC",
                (RequestStatus.FAILED.value,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_recent(self, limit: int = 20) -> list[RequestRecord]:
        """Letzte Requests unabhängig vom Status."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM requests
                ORDER BY COALESCE(completed_at, started_at, created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def save_attachments(
        self,
        request_id: str,
        attachments: Sequence[ProcessedAttachment],
    ) -> None:
        """Attachment-Verarbeitungsergebnisse speichern."""
        now = utc_now_iso()
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM request_attachments WHERE request_id = ?",
                (request_id,),
            )
            for item in attachments:
                file_size = item.source_path.stat().st_size if item.source_path else None
                conn.execute(
                    """
                    INSERT INTO request_attachments (
                        request_id, name, local_path, resolved_path, status, kind,
                        file_size_bytes, extracted_characters, error_message,
                        created_at, processed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        item.name,
                        str(item.source_path) if item.source_path else None,
                        str(item.source_path) if item.source_path else None,
                        item.status.value,
                        item.kind.value,
                        file_size,
                        item.extracted_characters,
                        item.error,
                        now,
                        now if item.status.value == "processed" else None,
                    ),
                )

    def list_attachments(self, request_id: str) -> list[AttachmentRecord]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM request_attachments WHERE request_id = ? ORDER BY id",
                (request_id,),
            ).fetchall()
        return [self._row_to_attachment(row) for row in rows]
