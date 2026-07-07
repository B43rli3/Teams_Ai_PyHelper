"""Tests für SQLite-Repository."""

from __future__ import annotations

from teams_ollama_bridge.models import RequestStatus
from teams_ollama_bridge.repository import RequestRepository


def test_sqlite_status_transitions(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    repo = RequestRepository(db_path)

    record = repo.upsert_discovered(
        "req-1", "msg-1", "chat-1", "input.json", "hash1"
    )
    assert record.status == RequestStatus.DISCOVERED

    assert repo.try_mark_processing("req-1") is True
    record = repo.get("req-1")
    assert record is not None
    assert record.status == RequestStatus.PROCESSING

    repo.mark_completed("req-1", "response_req-1.json", "mock", 100)
    record = repo.get("req-1")
    assert record is not None
    assert record.status == RequestStatus.COMPLETED

    repo.mark_archived("req-1")
    record = repo.get("req-1")
    assert record is not None
    assert record.status == RequestStatus.ARCHIVED


def test_mark_failed_increments_retry(tmp_path) -> None:
    repo = RequestRepository(tmp_path / "state.db")
    repo.upsert_discovered("req-2", "m", "c", "f.json", "h")
    count = repo.mark_failed("req-2", "TestError", "Fehler", increment_retry=True)
    assert count == 1
    record = repo.get("req-2")
    assert record is not None
    assert record.status == RequestStatus.FAILED


def test_reset_failed_to_discovered(tmp_path) -> None:
    repo = RequestRepository(tmp_path / "state.db")
    repo.upsert_discovered("req-3", "m", "c", "f.json", "h")
    repo.mark_failed("req-3", "Err", "Msg", increment_retry=False)
    assert repo.reset_failed_to_discovered("req-3") is True
    record = repo.get("req-3")
    assert record is not None
    assert record.status == RequestStatus.DISCOVERED
