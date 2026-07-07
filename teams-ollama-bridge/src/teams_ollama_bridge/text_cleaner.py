"""Textbereinigung für Teams-Nachrichten."""

from __future__ import annotations

import html
import re

from teams_ollama_bridge.exceptions import EmptyMessageError, MessageTooLongError

_NBSP_PATTERN = re.compile(r"\u00a0")
_MULTI_SPACE_PATTERN = re.compile(r"[^\S\n]+")


def clean_message(text: str, max_length: int) -> str:
    """Nachrichtentext für die LLM-Übergabe bereinigen.

    - führende/nachfolgende Leerzeichen entfernen
    - HTML-Entities dekodieren
    - &nbsp; entfernen
    - Unicode-NBSP durch normale Leerzeichen ersetzen
    - mehrfache Leerzeichen reduzieren (Zeilenumbrüche bleiben erhalten)
    - leere Nachrichten ablehnen
    - maximale Länge prüfen
    """
    if not text:
        raise EmptyMessageError("Die Nachricht ist leer.")

    cleaned = text.strip()
    cleaned = html.unescape(cleaned)
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = _NBSP_PATTERN.sub(" ", cleaned)

    lines = cleaned.split("\n")
    normalized_lines = [_MULTI_SPACE_PATTERN.sub(" ", line).strip() for line in lines]
    cleaned = "\n".join(normalized_lines).strip()

    if not cleaned:
        raise EmptyMessageError("Die Nachricht ist nach Bereinigung leer.")

    if len(cleaned) > max_length:
        raise MessageTooLongError(
            f"Die Nachricht überschreitet die maximale Länge von {max_length} Zeichen."
        )

    return cleaned


def truncate_answer(text: str, max_length: int) -> str:
    """Antwort auf maximale Länge begrenzen."""
    if len(text) <= max_length:
        return text
    truncated = text[: max_length - 3].rstrip()
    return f"{truncated}..."
