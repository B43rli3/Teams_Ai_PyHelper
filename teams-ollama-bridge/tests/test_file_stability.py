"""Tests für Dateistabilität."""

from __future__ import annotations

import time

from teams_ollama_bridge.file_service import (
    discover_stable_files,
    is_file_stable,
    is_ignored_file,
    list_json_files,
)


def test_ignored_files(tmp_path) -> None:
    (tmp_path / "valid.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".hidden.json").write_text("{}", encoding="utf-8")
    (tmp_path / "~temp.json").write_text("{}", encoding="utf-8")
    (tmp_path / "file.tmp").write_text("{}", encoding="utf-8")
    (tmp_path / "file.part").write_text("{}", encoding="utf-8")

    files = list_json_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "valid.json"
    assert is_ignored_file(tmp_path / ".hidden.json")
    assert is_ignored_file(tmp_path / "~temp.json")


def test_unstable_file_not_processed(tmp_path) -> None:
    path = tmp_path / "new.json"
    path.write_text('{"requestId":"x"}', encoding="utf-8")
    assert is_file_stable(path, stable_seconds=2.0) is False
    stable = discover_stable_files(tmp_path, stable_seconds=2.0)
    assert len(stable) == 0


def test_stable_file_processed(tmp_path) -> None:
    path = tmp_path / "stable.json"
    path.write_text('{"requestId":"x"}', encoding="utf-8")
    past = time.time() - 10
    import os

    os.utime(path, (past, past))
    assert is_file_stable(path, stable_seconds=0.0) is True
    stable = discover_stable_files(tmp_path, stable_seconds=0.0)
    assert len(stable) == 1
