"""Dateioperationen: Lesen, Schreiben, Stabilität, Archivierung."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from teams_ollama_bridge.exceptions import (
    FilePermissionError,
    InvalidInputSchemaError,
    InvalidJsonError,
    OutputFileExistsError,
)
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.models import InputRequest, OutputResponse
from teams_ollama_bridge.utils import file_sha256, sanitize_request_id, unique_destination_path

logger = get_logger(__name__)

TEMP_SUFFIXES = (".tmp", ".part")
HIDDEN_PREFIXES = (".", "~")


@dataclass(frozen=True)
class StableFile:
    """Eine stabile JSON-Datei im Inputordner."""

    path: Path
    size: int
    mtime: float
    ctime: float


def is_ignored_file(path: Path) -> bool:
    """Prüfen, ob eine Datei ignoriert werden soll."""
    name = path.name
    if name.startswith(HIDDEN_PREFIXES):
        return True
    lower_name = name.lower()
    return any(lower_name.endswith(suffix) for suffix in TEMP_SUFFIXES)


def list_json_files(directory: Path) -> list[Path]:
    """Alle nicht ignorierten .json-Dateien auflisten."""
    if not directory.exists():
        return []
    files = [
        entry
        for entry in directory.iterdir()
        if entry.is_file() and entry.suffix.lower() == ".json" and not is_ignored_file(entry)
    ]
    return sorted(files, key=lambda p: (p.stat().st_ctime, p.stat().st_mtime))


def get_file_stat(path: Path) -> tuple[int, float]:
    """Größe und Änderungszeit einer Datei."""
    stat = path.stat()
    return stat.st_size, stat.st_mtime


def is_file_stable(path: Path, stable_seconds: float) -> bool:
    """Prüfen, ob Dateigröße und mtime seit stable_seconds unverändert sind."""
    if not path.exists():
        return False
    size, mtime = get_file_stat(path)
    now = time.time()
    if now - mtime < stable_seconds:
        return False
    time.sleep(0.05)
    if not path.exists():
        return False
    new_size, new_mtime = get_file_stat(path)
    if new_size != size or new_mtime != mtime:
        return False
    return not (now - new_mtime < stable_seconds)


def discover_stable_files(input_dir: Path, stable_seconds: float) -> list[StableFile]:
    """Stabile JSON-Dateien im Inputordner finden."""
    stable_files: list[StableFile] = []
    for path in list_json_files(input_dir):
        if not is_file_stable(path, stable_seconds):
            continue
        stat = path.stat()
        stable_files.append(
            StableFile(
                path=path,
                size=stat.st_size,
                mtime=stat.st_mtime,
                ctime=stat.st_ctime,
            )
        )
    stable_files.sort(key=lambda f: (f.ctime, f.mtime))
    return stable_files


def read_json_file(path: Path) -> dict[str, Any]:
    """JSON-Datei mit UTF-8 oder UTF-8-BOM lesen."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FilePermissionError(f"Datei kann nicht gelesen werden: {path.name}") from exc

    text = raw.decode("utf-8-sig") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidJsonError(f"Ungültiges JSON in {path.name}: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise InvalidJsonError(f"JSON-Wurzel muss ein Objekt sein: {path.name}")

    return data


def load_input_request(path: Path) -> InputRequest:
    """Input-JSON laden und validieren."""
    data = read_json_file(path)
    try:
        return InputRequest.from_json_dict(data)
    except ValidationError as exc:
        raise InvalidInputSchemaError(f"Ungültiges Inputschema in {path.name}: {exc}") from exc


def output_filename_for(request_id: str) -> str:
    """Dateiname für eine Response-Datei."""
    return f"response_{sanitize_request_id(request_id)}.json"


def output_path_for(output_dir: Path, request_id: str) -> Path:
    """Vollständiger Pfad für eine Response-Datei."""
    return output_dir / output_filename_for(request_id)


def write_output_response(output_dir: Path, response: OutputResponse) -> Path:
    """Response-JSON atomar und exklusiv im Outputordner erstellen."""
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / output_filename_for(response.request_id)

    if final_path.exists():
        raise OutputFileExistsError(
            f"Outputdatei existiert bereits: {final_path.name}"
        )

    payload = json.dumps(
        response.to_json_dict(),
        ensure_ascii=False,
        indent=2,
    )
    encoded = payload.encode("utf-8")

    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=tempfile.gettempdir(),
        prefix="teams-ollama-bridge-",
        suffix=".json",
        delete=False,
    ) as tmp:
        tmp.write(encoded)
        tmp_path = Path(tmp.name)

    try:
        fd = os.open(
            str(final_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
        except Exception:
            os.close(fd)
            raise
    except FileExistsError as exc:
        tmp_path.unlink(missing_ok=True)
        raise OutputFileExistsError(
            f"Outputdatei existiert bereits: {final_path.name}"
        ) from exc
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise FilePermissionError(
            f"Outputdatei kann nicht erstellt werden: {final_path.name}"
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info("Outputdatei erstellt: %s", final_path.name)
    return final_path


def move_to_archive(source: Path, target_dir: Path) -> Path:
    """Datei in Archivordner verschieben ohne Überschreiben."""
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination_path(target_dir / source.name)
    try:
        shutil.move(str(source), str(destination))
    except OSError as exc:
        raise FilePermissionError(
            f"Datei kann nicht archiviert werden: {source.name}"
        ) from exc
    logger.info("Datei archiviert: %s -> %s", source.name, destination)
    return destination


def compute_file_hash(path: Path) -> str:
    """SHA-256-Hash einer Datei."""
    return file_sha256(path)
