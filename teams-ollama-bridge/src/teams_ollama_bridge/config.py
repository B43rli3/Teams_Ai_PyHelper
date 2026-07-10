"""Anwendungskonfiguration mit pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from teams_ollama_bridge.exceptions import ConfigurationError
from teams_ollama_bridge.models import ImageProcessingMode, ProcessorMode
from teams_ollama_bridge.tool_policy import DEFAULT_ALLOWED_TOOLS, DEFAULT_BLOCKED_TOOLS


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

    attachments_enabled: bool = True
    attachments_base_dir: Path | None = Field(default=None, alias="ATTACHMENTS_BASE_DIR")
    attachments_max_files: int = 3
    attachments_max_file_size_mb: int = 20
    attachments_max_extracted_characters_per_file: int = 30000
    attachments_max_total_extracted_characters: int = 60000
    attachments_allowed_extensions: str = ".txt,.md,.csv,.pdf,.docx,.xlsx,.png,.jpg,.jpeg,.webp"
    attachments_include_filenames_in_prompt: bool = True

    image_processing_mode: ImageProcessingMode = ImageProcessingMode.METADATA
    ollama_vision_model: str = "llava:latest"
    ollama_vision_timeout_seconds: float = 180.0
    image_max_size_mb: int = 10
    image_max_dimension_pixels: int = 8000
    image_analysis_prompt: str = (
        "Beschreibe den relevanten Inhalt dieses Bildes präzise auf Deutsch. "
        "Wenn Text erkennbar ist, gib ihn sinngemäß wieder. Erfinde keine Details."
    )

    database_path: Path = Path("data/state.db")
    lock_file_path: Path = Path("data/worker.lock")

    log_file_path: Path = Path("logs/teams-ollama-bridge.log")
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 5

    mcp_enabled: bool = Field(default=False, alias="MCP_ENABLED")
    mcp_server_url: str = Field(
        default="http://127.0.0.1:7373/mcp",
        alias="MCP_SERVER_URL",
    )
    mcp_token: str | None = Field(default=None, alias="MCP_TOKEN")
    mcp_timeout_seconds: float = Field(default=30.0, alias="MCP_TIMEOUT_SECONDS")
    mcp_read_timeout_seconds: float = Field(default=120.0, alias="MCP_READ_TIMEOUT_SECONDS")
    mcp_connect_timeout_seconds: float = Field(default=10.0, alias="MCP_CONNECT_TIMEOUT_SECONDS")
    mcp_max_tool_rounds: int = Field(default=4, alias="MCP_MAX_TOOL_ROUNDS")
    mcp_max_tool_calls_total: int = Field(default=8, alias="MCP_MAX_TOOL_CALLS_TOTAL")
    mcp_max_result_characters: int = Field(default=30000, alias="MCP_MAX_RESULT_CHARACTERS")
    mcp_fail_on_unavailable: bool = Field(default=False, alias="MCP_FAIL_ON_UNAVAILABLE")
    mcp_log_tool_calls: bool = Field(default=True, alias="MCP_LOG_TOOL_CALLS")
    mcp_log_tool_results: bool = Field(default=False, alias="MCP_LOG_TOOL_RESULTS")
    mcp_allow_manual_tool_test: bool = Field(default=False, alias="MCP_ALLOW_MANUAL_TOOL_TEST")
    mcp_allowed_tools: str = Field(
        default=",".join(sorted(DEFAULT_ALLOWED_TOOLS)),
        alias="MCP_ALLOWED_TOOLS",
    )
    mcp_blocked_tools: str = Field(
        default=",".join(sorted(DEFAULT_BLOCKED_TOOLS)),
        alias="MCP_BLOCKED_TOOLS",
    )

    @field_validator("mcp_token", mode="before")
    @classmethod
    def empty_mcp_token_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "teams_llm_root",
        "input_dir",
        "output_dir",
        "processed_input_dir",
        "failed_input_dir",
        "database_path",
        "lock_file_path",
        "log_file_path",
        "attachments_base_dir",
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

        if self.attachments_base_dir is None and self.input_dir is not None:
            self.attachments_base_dir = self.input_dir

        if self.mcp_enabled and not self.mcp_token:
            raise ConfigurationError(
                "MCP_ENABLED=true, aber MCP_TOKEN ist nicht gesetzt. "
                "Tragen Sie den Token aus dem CPD-Agent-Panel in die .env ein."
            )

        return self

    @property
    def attachments_max_file_size_bytes(self) -> int:
        return self.attachments_max_file_size_mb * 1024 * 1024

    @property
    def parsed_allowed_extensions(self) -> set[str]:
        return {
            ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
            for ext in self.attachments_allowed_extensions.split(",")
            if ext.strip()
        }

    @property
    def parsed_mcp_allowed_tools(self) -> set[str]:
        return {name.strip() for name in self.mcp_allowed_tools.split(",") if name.strip()}

    @property
    def parsed_mcp_blocked_tools(self) -> set[str]:
        return {name.strip() for name in self.mcp_blocked_tools.split(",") if name.strip()}

    def warn_if_mcp_non_localhost(self) -> None:
        """Warnt, wenn MCP_SERVER_URL nicht auf Loopback zeigt."""
        if not self.mcp_enabled:
            return
        from urllib.parse import urlparse

        from teams_ollama_bridge.logging_config import get_logger

        host = (urlparse(self.mcp_server_url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            get_logger(__name__).warning(
                "MCP_SERVER_URL zeigt nicht auf localhost (%s). "
                "Der CPD-PoC ist nur für 127.0.0.1 vorgesehen.",
                self.mcp_server_url,
            )

    @property
    def effective_system_prompt(self) -> str:
        from teams_ollama_bridge.attachment_context_builder import AttachmentContextBuilder

        suffix = AttachmentContextBuilder.attachment_system_prompt_suffix()
        if suffix not in self.llm_system_prompt:
            return f"{self.llm_system_prompt.strip()} {suffix}"
        return self.llm_system_prompt

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
            "attachments_enabled": self.attachments_enabled,
            "mcp_enabled": self.mcp_enabled,
            "mcp_server_url": self.mcp_server_url,
            "mcp_token_set": bool(self.mcp_token),
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
        settings.warn_if_mcp_non_localhost()
        return settings
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"Konfigurationsfehler: {exc}") from exc
