"""Gemeinsame Test-Fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from teams_ollama_bridge.config import Settings
from teams_ollama_bridge.models import ProcessorMode


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
  """Isoliertes Arbeitsverzeichnis mit Standardordnern."""
  root = tmp_path / "TeamsLLM"
  input_dir = root / "input"
  output_dir = root / "output"
  processed_dir = root / "processed" / "input"
  failed_dir = root / "error" / "input"
  data_dir = tmp_path / "data"
  logs_dir = tmp_path / "logs"

  for directory in (input_dir, output_dir, processed_dir, failed_dir, data_dir, logs_dir):
    directory.mkdir(parents=True)
  (input_dir / "files").mkdir(parents=True, exist_ok=True)

  return tmp_path


@pytest.fixture
def settings(workspace: Path) -> Settings:
  """Test-Konfiguration mit Mock-Modus."""
  root = workspace / "TeamsLLM"
  return Settings(
    _env_file=None,
    teams_llm_root=root,
    processor_mode=ProcessorMode.MOCK,
    poll_interval_seconds=0.1,
    file_stable_seconds=0.0,
    max_process_retries=3,
    retry_delay_seconds=0.0,
    stale_processing_minutes=10,
    database_path=workspace / "data" / "state.db",
    lock_file_path=workspace / "data" / "worker.lock",
    log_file_path=workspace / "logs" / "test.log",
    log_message_content=False,
    llm_max_input_characters=12000,
    llm_max_output_characters=20000,
    attachments_enabled=True,
  )


def write_input_file(
  input_dir: Path,
  request_id: str = "test-001",
  message: str = "Dies ist ein Test.",
  filename: str | None = None,
  extra: dict | None = None,
) -> Path:
  """Hilfsfunktion zum Erstellen einer Input-JSON."""
  payload = {
    "requestId": request_id,
    "messageId": "1783415721396",
    "chatId": "19:meeting_test@thread.v2",
    "sender": "Test User",
    "message": message,
    "createdAt": "2026-07-07T09:15:22.6932048Z",
  }
  if extra:
    payload.update(extra)
  path = input_dir / (filename or f"request_{request_id}.json")
  path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
  return path


@pytest.fixture(autouse=True)
def chdir_to_workspace(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  """Arbeitsverzeichnis für Settings auf Workspace setzen."""
  monkeypatch.chdir(workspace)
  monkeypatch.setenv("TEAMS_LLM_ROOT", str(workspace / "TeamsLLM"))
