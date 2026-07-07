"""Tests für erfolgreiche Worker-Verarbeitung."""

from __future__ import annotations

import json

from tests.conftest import write_input_file

from teams_ollama_bridge.file_service import output_path_for
from teams_ollama_bridge.logging_config import setup_logging
from teams_ollama_bridge.processor import RequestProcessor
from teams_ollama_bridge.repository import RequestRepository


def test_worker_success_flow(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    input_dir = settings.input_dir
    write_input_file(input_dir, request_id="success-001", message="Dies ist ein Test.")

    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)

    assert processor.process_file(list(input_dir.glob("*.json"))[0]) is True

    output_path = output_path_for(settings.output_dir, "success-001")
    assert output_path.exists()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["requestId"] == "success-001"
    assert "PoC erfolgreich" in data["answer"]

    archived = list(settings.processed_input_dir.glob("*.json"))
    assert len(archived) == 1
    assert not list(input_dir.glob("*.json"))


def test_input_archived_after_output(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    input_path = write_input_file(settings.input_dir, request_id="archive-001")
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)

    processor.process_file(input_path)
    assert not input_path.exists()
    assert list(settings.processed_input_dir.glob("*.json"))
