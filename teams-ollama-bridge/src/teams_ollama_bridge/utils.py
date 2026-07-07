"""Hilfsfunktionen."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> datetime:
    """Aktuelle UTC-Zeit."""
    return datetime.now(UTC)


def utc_now_iso() -> str:
    """Aktuelle UTC-Zeit als ISO-8601 mit Z-Suffix."""
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path: Path) -> str:
    """SHA-256-Hash einer Datei berechnen."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def truncate_for_log(value: str, max_length: int = 40) -> str:
    """Text für Logging kürzen."""
    if len(value) <= max_length:
        return value
    return f"{value[: max_length - 3]}..."


def truncate_filename(filename: str, max_length: int = 50) -> str:
    """Dateinamen für Logging kürzen."""
    return truncate_for_log(filename, max_length)


def sanitize_request_id(request_id: str) -> str:
    """Request-ID für Dateinamen bereinigen."""
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", request_id)
    return sanitized.strip() or "unknown"


def discover_onedrive_paths() -> list[Path]:
    """Bekannte OneDrive-Umgebungsvariablen auswerten."""
    candidates: list[Path] = []
    env_vars = (
        "OneDriveCommercial",
        "OneDrive",
        "OneDriveConsumer",
        "ONEDRIVE",
        "ONEDRIVECOMMERCIAL",
    )
    seen: set[str] = set()
    for var in env_vars:
        value = os.environ.get(var)
        if not value:
            continue
        normalized = str(Path(value).resolve())
        if normalized not in seen and Path(normalized).exists():
            seen.add(normalized)
            candidates.append(Path(normalized))
    return candidates


def unique_destination_path(target: Path) -> Path:
    """Eindeutigen Zielpfad erzeugen, wenn Datei bereits existiert."""
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    timestamp = utc_now().strftime("%Y%m%d_%H%M%S")
    counter = 1
    while True:
        candidate = parent / f"{stem}_{timestamp}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
