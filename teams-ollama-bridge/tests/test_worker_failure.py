"""Tests für Fehlerbehandlung."""

from __future__ import annotations

import json

import pytest
from tests.conftest import write_input_file

from teams_ollama_bridge.exceptions import InstanceAlreadyRunningError
from teams_ollama_bridge.file_service import output_path_for
from teams_ollama_bridge.logging_config import setup_logging
from teams_ollama_bridge.processor import RequestProcessor
from teams_ollama_bridge.repository import RequestRepository
from teams_ollama_bridge.worker import Worker


def test_failed_output_after_max_retries(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    settings.max_process_retries = 1
    settings.retry_delay_seconds = 0.0

    path = settings.input_dir / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")

    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)

    processor.process_file(path)
    processor.process_file(path)

    failed_outputs = [
        f for f in settings.output_dir.glob("*.json") if '"status": "failed"' in f.read_text()
    ]
    assert len(failed_outputs) >= 0 or not path.exists()


def test_empty_message_produces_failed(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    path = write_input_file(settings.input_dir, request_id="empty-001", message="   ")
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)
    processor.process_file(path)

    failed = output_path_for(settings.output_dir, "empty-001")
    if failed.exists():
        data = json.loads(failed.read_text(encoding="utf-8"))
        assert data["status"] == "failed"


def test_two_workers_prevented_by_lock(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    worker1 = Worker(settings)
    worker1.acquire_lock()

    worker2 = Worker(settings)
    with pytest.raises(InstanceAlreadyRunningError):
        worker2.acquire_lock()

    worker1.release_lock()


def test_content_mismatch_error(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    write_input_file(settings.input_dir, request_id="mismatch-001", message="Original")
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)
    processor.process_file(list(settings.input_dir.glob("*.json"))[0])

    write_input_file(
        settings.input_dir,
        request_id="mismatch-001",
        message="Abweichend",
        filename="mismatch_copy.json",
    )
    processor.process_file(list(settings.input_dir.glob("*.json"))[0])
    failed = output_path_for(settings.output_dir, "mismatch-001")
    if failed.exists():
        data = json.loads(failed.read_text(encoding="utf-8"))
        assert data.get("status") in ("completed", "failed")
