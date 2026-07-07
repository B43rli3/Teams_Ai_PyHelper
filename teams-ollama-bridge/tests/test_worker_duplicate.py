"""Tests für Deduplizierung."""

from __future__ import annotations

import json

from tests.conftest import write_input_file

from teams_ollama_bridge.file_service import output_path_for, write_output_response
from teams_ollama_bridge.logging_config import setup_logging
from teams_ollama_bridge.models import OutputResponse
from teams_ollama_bridge.processor import RequestProcessor
from teams_ollama_bridge.repository import RequestRepository
from teams_ollama_bridge.utils import utc_now_iso


def test_same_request_id_not_processed_twice(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    input_path = write_input_file(settings.input_dir, request_id="dup-001")
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)

    assert processor.process_file(input_path) is True

    write_input_file(settings.input_dir, request_id="dup-001", filename="dup_copy.json")
    second_path = list(settings.input_dir.glob("*.json"))[0]
    result = processor.process_file(second_path)
    assert result is False

    outputs = list(settings.output_dir.glob("response_dup-001.json"))
    assert len(outputs) == 1


def test_restart_no_second_output(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    write_input_file(settings.input_dir, request_id="restart-001")

    repo1 = RequestRepository(settings.database_path)
    processor1 = RequestProcessor(settings, repo1)
    input_path = list(settings.input_dir.glob("*.json"))[0]
    processor1.process_file(input_path)

    write_input_file(settings.input_dir, request_id="restart-001", filename="again.json")
    new_input = list(settings.input_dir.glob("*.json"))[0]

    repo2 = RequestRepository(settings.database_path)
    processor2 = RequestProcessor(settings, repo2)
    processor2.process_file(new_input)

    assert len(list(settings.output_dir.glob("response_restart-001.json"))) == 1


def test_existing_output_not_overwritten(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    existing = OutputResponse(
        requestId="exist-001",
        messageId="1",
        chatId="c",
        answer="Bestehende Antwort",
        status="completed",
        processedAt=utc_now_iso(),
    )
    write_output_response(settings.output_dir, existing)

    write_input_file(settings.input_dir, request_id="exist-001")
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)
    processor.process_file(list(settings.input_dir.glob("*.json"))[0])

    data = json.loads(output_path_for(settings.output_dir, "exist-001").read_text(encoding="utf-8"))
    assert data["answer"] == "Bestehende Antwort"
