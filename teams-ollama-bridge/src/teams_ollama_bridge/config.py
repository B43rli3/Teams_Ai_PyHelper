"""Anwendungskonfiguration mit pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from teams_ollama_bridge.exceptions import ConfigurationError
from teams_ollama_bridge.models import ProcessorMode


class Settings(BaseSettings):
    """Zentrale Konfiguration aus Umgebungsvariablen und .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_message_content: bool = False

    teams_llm_root: Path | None = Field(default=None, alias="TEAMS_LLM_ROOT")

    input_dir: Path | None = Field(default=None, alias="INPUT_DIR")
    output_dir: Path | None = Field(default=None, alias="OUTPUT_DIR")
    processed_input_dir: Path | None = Field(default=None, alias="PROCESSED_INPUT_DIR")
    failed_input_dir: Path | None = Field(default=None, alias="FAILED_INPUT_DIR")

    processor_mode: ProcessorMode = ProcessorMode.MOCK

    poll_interval_seconds: float = 2.0
    file_stable_seconds: float = 2.0
    max_process_retries: int = 3
    retry_delay_seconds: float = 5.0
    stale_processing_minutes: int = 10

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:14b"
    ollama_timeout_seconds: float = 180.0
    ollama_keep_alive: str = "10m"
    ollama_temperature: float = 0.2

    llm_system_prompt: str = (
        "Du bist ein hilfreicher interner Assistent in Microsoft Teams. "
        "Antworte präzise, sachlich und auf Deutsch. Gib nur die eigentliche Antwort aus."
    )
    llm_max_input_characters: int = 12000
    llm_max_output_characters: int = 20000

    database_path: Path = Path("data/state.db")
    lock_file_path: Path = Path("data/worker.lock")

    log_file_path: Path = Path("logs/teams-ollama-bridge.log")
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 5

    @field_validator(
        "teams_llm_root",
        "input_dir",
        "output_dir",
        "processed_input_dir",
        "failed_input_dir",
        "database_path",
        "lock_file_path",
        "log_file_path",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def resolve_paths(self) -> Settings:
        """Pfade aus TEAMS_LLM_ROOT ableiten, wenn nicht explizit gesetzt."""
        if self.teams_llm_root is None and any(
            p is None
            for p in (
                self.input_dir,
                self.output_dir,
                self.processed_input_dir,
                self.failed_input_dir,
            )
        ):
            raise ConfigurationError(
                "TEAMS_LLM_ROOT muss gesetzt sein oder alle Verzeichnispfade "
                "(INPUT_DIR, OUTPUT_DIR, PROCESSED_INPUT_DIR, FAILED_INPUT_DIR) müssen "
                "explizit angegeben werden."
            )

        root = self.teams_llm_root
        if self.input_dir is None:
            if root is None:
                raise ConfigurationError("INPUT_DIR ist nicht gesetzt und TEAMS_LLM_ROOT fehlt.")
            self.input_dir = root / "input"
        if self.output_dir is None:
            if root is None:
                raise ConfigurationError("OUTPUT_DIR ist nicht gesetzt und TEAMS_LLM_ROOT fehlt.")
            self.output_dir = root / "output"
        if self.processed_input_dir is None:
            if root is None:
                raise ConfigurationError(
                    "PROCESSED_INPUT_DIR ist nicht gesetzt und TEAMS_LLM_ROOT fehlt."
                )
            self.processed_input_dir = root / "processed" / "input"
        if self.failed_input_dir is None:
            if root is None:
                raise ConfigurationError(
                    "FAILED_INPUT_DIR ist nicht gesetzt und TEAMS_LLM_ROOT fehlt."
                )
            self.failed_input_dir = root / "error" / "input"

        return self

    def ensure_directories(self) -> None:
        """Erforderliche Verzeichnisse erstellen."""
        for directory in (
            self.input_dir,
            self.output_dir,
            self.processed_input_dir,
            self.failed_input_dir,
            self.database_path.parent,
            self.lock_file_path.parent,
            self.log_file_path.parent,
        ):
            if directory is not None:
                directory.mkdir(parents=True, exist_ok=True)

    def safe_config_summary(self) -> dict[str, object]:
        """Konfiguration ohne sensible Werte für Logging."""
        return {
            "app_env": self.app_env,
            "processor_mode": self.processor_mode.value,
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "processed_input_dir": str(self.processed_input_dir),
            "failed_input_dir": str(self.failed_input_dir),
            "poll_interval_seconds": self.poll_interval_seconds,
            "file_stable_seconds": self.file_stable_seconds,
            "max_process_retries": self.max_process_retries,
            "ollama_model": (
                self.ollama_model if self.processor_mode == ProcessorMode.OLLAMA else None
            ),
            "database_path": str(self.database_path),
        }


def load_settings() -> Settings:
    """Konfiguration laden und bei Fehlern verständliche Meldung ausgeben."""
    try:
        settings = Settings()
        settings.ensure_directories()
        return settings
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"Konfigurationsfehler: {exc}") from exc
