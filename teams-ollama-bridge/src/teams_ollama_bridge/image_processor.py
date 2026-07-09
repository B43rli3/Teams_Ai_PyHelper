"""Bildverarbeitung: Metadaten oder Ollama Vision."""

from __future__ import annotations

import base64
from pathlib import Path

from teams_ollama_bridge.config import Settings
from teams_ollama_bridge.exceptions import OllamaResponseError
from teams_ollama_bridge.logging_config import get_logger
from teams_ollama_bridge.models import ImageProcessingMode
from teams_ollama_bridge.ollama_client import OllamaClient

logger = get_logger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class ImageProcessor:
    """Liest Bildmetadaten oder nutzt Ollama Vision."""

    def __init__(self, settings: Settings, ollama_client: OllamaClient | None = None) -> None:
        self._settings = settings
        self._ollama_client = ollama_client

    def _read_metadata(self, path: Path) -> str:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
            fmt = img.format or path.suffix.lstrip(".").upper()
        size_kb = path.stat().st_size / 1024
        return (
            f"Bild erkannt: Format {fmt}, Größe {width}x{height} px, "
            f"Dateigröße {size_kb:.1f} KB"
        )

    def _analyze_with_vision(self, path: Path) -> str:
        if self._ollama_client is None:
            raise OllamaResponseError("Ollama-Client für Vision nicht verfügbar.")

        max_bytes = self._settings.image_max_size_mb * 1024 * 1024
        if path.stat().st_size > max_bytes:
            raise OllamaResponseError("Bild überschreitet die maximale Größe für Vision.")

        image_bytes = path.read_bytes()
        encoded = base64.b64encode(image_bytes).decode("ascii")

        description = self._ollama_client.analyze_image(
            model=self._settings.ollama_vision_model,
            prompt=self._settings.image_analysis_prompt,
            image_base64=encoded,
            timeout_seconds=self._settings.ollama_vision_timeout_seconds,
        )
        return description

    def process(self, path: Path) -> str:
        """Bild verarbeiten und Beschreibungstext zurückgeben."""
        if self._settings.image_processing_mode == ImageProcessingMode.OLLAMA_VISION:
            try:
                return self._analyze_with_vision(path)
            except Exception as exc:
                logger.warning("Vision-Analyse fehlgeschlagen für %s: %s", path.name, exc)
                meta = self._read_metadata(path)
                return f"{meta}. Vision-Analyse fehlgeschlagen: {exc}"
        return self._read_metadata(path)
