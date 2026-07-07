"""Tests für Mock-Prozessor."""

from __future__ import annotations

from teams_ollama_bridge.mock_processor import MockProcessor


def test_mock_processor_expected_answer() -> None:
    processor = MockProcessor(max_output_characters=20000)
    result = processor.process("Dies ist ein Test.")
    assert "PoC erfolgreich" in result.answer
    assert "Dies ist ein Test." in result.answer
    assert result.model == "mock"
