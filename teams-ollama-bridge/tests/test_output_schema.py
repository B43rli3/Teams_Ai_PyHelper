"""Tests für Output-Schema."""

from __future__ import annotations

import json

from tests.conftest import write_input_file

from teams_ollama_bridge.file_service import write_output_response
from teams_ollama_bridge.logging_config import setup_logging
from teams_ollama_bridge.models import OutputResponse
from teams_ollama_bridge.processor import RequestProcessor
from teams_ollama_bridge.repository import RequestRepository
from teams_ollama_bridge.utils import utc_now_iso


def test_output_schema_completed(settings, workspace) -> None:
    setup_logging("WARNING", settings.log_file_path, 10000, 1)
    write_input_file(settings.input_dir, request_id="schema-001")
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)
    processor.process_file(list(settings.input_dir.glob("*.json"))[0])

    output_file = settings.output_dir / "response_schema-001.json"
    data = json.loads(output_file.read_text(encoding="utf-8"))

    required = {"requestId", "messageId", "chatId", "answer", "status", "processedAt"}
    assert required.issubset(data.keys())
    assert data["status"] == "completed"
    assert data["requestId"] == "schema-001"


def test_output_utf8_no_bom(settings, workspace) -> None:
    response = OutputResponse(
        requestId="utf8-001",
        messageId="1",
        chatId="c",
        answer="Grüße mit äöüß",
        status="completed",
        processedAt=utc_now_iso(),
    )
    path = write_output_response(settings.output_dir, response)
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    assert "ü" in data["answer"]


def test_sensitive_content_not_logged_by_default(settings, workspace, caplog) -> None:
    setup_logging("INFO", settings.log_file_path, 10000, 1)
    secret_message = "GEHEIME_NACHRICHT_12345"
    write_input_file(settings.input_dir, request_id="log-001", message=secret_message)
    repo = RequestRepository(settings.database_path)
    processor = RequestProcessor(settings, repo)

    import logging

    with caplog.at_level(logging.INFO):
        processor.process_file(list(settings.input_dir.glob("*.json"))[0])

    combined = caplog.text
    assert secret_message not in combined
