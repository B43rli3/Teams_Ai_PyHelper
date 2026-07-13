"""Normalisierung von MCP-Toolergebnissen."""

from __future__ import annotations

import json
from typing import Any

from teams_ollama_bridge.exceptions import MCPConsentRequiredError, MCPToolError
from teams_ollama_bridge.mcp_models import NormalizedToolResult

_TRUNCATION_NOTE = "\n[Ergebnis wurde wegen Größenlimit gekürzt.]"

_ELEMENT_QUERY_TOOLS = frozenset({"query_elements", "get_elements"})


def truncate_result_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    if max_chars <= len(_TRUNCATION_NOTE):
        return text[:max_chars], True
    return text[: max_chars - len(_TRUNCATION_NOTE)].rstrip() + _TRUNCATION_NOTE, True


def _parse_tool_payload(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _extract_guids_from_payload(obj: Any) -> list[str]:
    guids: list[str] = []
    if isinstance(obj, str):
        stripped = obj.strip()
        if len(stripped) >= 8:
            guids.append(stripped)
        return guids
    if isinstance(obj, list):
        for item in obj:
            guids.extend(_extract_guids_from_payload(item))
        return guids
    if isinstance(obj, dict):
        for key in ("guid", "globalId", "global_id", "id"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                guids.append(value.strip())
        for key in ("guids", "globalIds", "global_ids", "elements", "data", "items", "results"):
            if key in obj:
                guids.extend(_extract_guids_from_payload(obj[key]))
    return guids


def compact_tool_result_for_llm(
    tool_name: str,
    text: str,
    *,
    max_guids: int = 80,
) -> str:
    """Kürzt große Elementlisten auf eine für LLM-Tool-Chains nutzbare Form."""
    if tool_name not in _ELEMENT_QUERY_TOOLS:
        return text

    parsed = _parse_tool_payload(text)
    if parsed is None:
        return text

    guids = _extract_guids_from_payload(parsed)
    unique_guids = list(dict.fromkeys(guids))
    if not unique_guids:
        return text

    compact: dict[str, Any] = {
        "ok": parsed.get("ok", True),
        "elementCount": len(unique_guids),
        "guids": unique_guids[:max_guids],
        "nextStep": (
            "Nutze select_elements mit dem Feld guids (Array dieser IDs), "
            "danach add_fill oder set_element_fill für die gewünschte Farbe."
        ),
    }
    if len(unique_guids) > max_guids:
        compact["truncated"] = True
        compact["totalGuids"] = len(unique_guids)
    return json.dumps(compact, ensure_ascii=False)


def normalize_tool_result(
    raw_text: str,
    *,
    max_chars: int,
    is_error: bool = False,
) -> NormalizedToolResult:
    """CPD-Tool-JSON parsen, Fehler erkennen und Größe begrenzen."""
    parsed = _parse_tool_payload(raw_text)
    if parsed is not None:
        ok = parsed.get("ok", True)
        reason = parsed.get("reason")
        if isinstance(reason, str) and "awaiting in-app authorization" in reason.lower():
            raise MCPConsentRequiredError(
                "Der Zugriff auf CPD ist noch nicht freigegeben. Bitte im "
                "CPD-/BIM-Annotation-Tool im Agent-Panel „Allow agent“ aktivieren "
                "und die Anfrage erneut senden."
            )
        if ok is False or is_error:
            message = reason if isinstance(reason, str) and reason.strip() else raw_text[:500]
            if "no project open" in message.lower() or "no drawing/setup open" in message.lower():
                raise MCPToolError(
                    "In CPD-AutoPlan ist aktuell kein Projekt oder kein Drawing/Setup "
                    "geöffnet. Bitte das gewünschte Projekt öffnen und erneut fragen."
                )
            raise MCPToolError(message)
        text = json.dumps(parsed, ensure_ascii=False)
    else:
        if is_error:
            raise MCPToolError(raw_text[:500] if raw_text else "Unbekannter Tool-Fehler.")
        text = raw_text

    truncated_text, truncated = truncate_result_text(text, max_chars)
    return NormalizedToolResult(text=truncated_text, ok=True, truncated=truncated)


def extract_tool_text_content(content: list[Any]) -> tuple[str, bool]:
    """Text und isError-Flag aus MCP CallToolResult.content extrahieren."""
    if not content:
        return "", False
    first = content[0]
    text = getattr(first, "text", None)
    if not isinstance(text, str):
        return "", False
    return text, bool(getattr(first, "type", None) == "text")
