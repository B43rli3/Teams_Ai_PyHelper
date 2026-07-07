"""Tests für Textbereinigung."""

from __future__ import annotations

import pytest

from teams_ollama_bridge.exceptions import EmptyMessageError, MessageTooLongError
from teams_ollama_bridge.text_cleaner import clean_message, truncate_answer


def test_nbsp_and_unicode_nbsp_cleaned() -> None:
    result = clean_message("Hallo&nbsp;Welt\u00a0Test", max_length=100)
    assert result == "Hallo Welt Test"


def test_html_entities_decoded() -> None:
    result = clean_message("Tom &amp; Jerry", max_length=100)
    assert result == "Tom & Jerry"


def test_empty_message_rejected() -> None:
    with pytest.raises(EmptyMessageError):
        clean_message("   ", max_length=100)


def test_whitespace_only_after_cleaning_rejected() -> None:
    with pytest.raises(EmptyMessageError):
        clean_message("&nbsp;", max_length=100)


def test_line_breaks_preserved() -> None:
    result = clean_message("Zeile 1\n\nZeile 2", max_length=100)
    assert "\n" in result
    assert "Zeile 1" in result
    assert "Zeile 2" in result


def test_multiple_spaces_reduced() -> None:
    result = clean_message("Hallo    Welt", max_length=100)
    assert result == "Hallo Welt"


def test_message_too_long_rejected() -> None:
    with pytest.raises(MessageTooLongError):
        clean_message("a" * 101, max_length=100)


def test_long_answer_truncated() -> None:
    result = truncate_answer("a" * 50, max_length=20)
    assert len(result) <= 20
    assert result.endswith("...")
