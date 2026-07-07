"""Tests für Input-Modelle."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from teams_ollama_bridge.file_service import load_input_request, read_json_file
from teams_ollama_bridge.models import InputRequest


def test_valid_input_file_loaded(tmp_path) -> None:
    data = {
        "requestId": "75d434c8-d025-4afb-a767-9a0b62d18c3b",
        "messageId": "1783415721396",
        "chatId": "19:meeting_test@thread.v2",
        "message": "Dies ist ein Test.",
    }
    path = tmp_path / "input.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    request = load_input_request(path)
    assert request.request_id == data["requestId"]
    assert request.message == "Dies ist ein Test."


def test_utf8_bom_supported(tmp_path) -> None:
    data = {"key": "Wert mit Umlauten: äöü"}
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(data).encode("utf-8"))
    result = read_json_file(path)
    assert result["key"] == "Wert mit Umlauten: äöü"


def test_test_001_request_id_valid() -> None:
    request = InputRequest(
        requestId="test-001",
        messageId="123",
        chatId="chat-1",
        message="Hallo",
    )
    assert request.request_id == "test-001"


def test_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        InputRequest(requestId="", messageId="1", chatId="c", message="x")


def test_invalid_json_handled(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{invalid", encoding="utf-8")
    from teams_ollama_bridge.exceptions import InvalidJsonError

    with pytest.raises(InvalidJsonError):
        load_input_request(path)


def test_german_umlauts_preserved() -> None:
    request = InputRequest(
        requestId="umlaut-test",
        messageId="1",
        chatId="c",
        message="Grüße aus Köln – schön!",
    )
    assert "ü" in request.message
    assert "ö" in request.message
