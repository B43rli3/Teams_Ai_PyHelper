"""Worker mit Polling-Schleife und Instanzsperre."""

from __future__ import annotations

import signal
import time
from pathlib import Path
from types import FrameType

from filelock import FileLock, Timeout

from teams_ollama_bridge.config import Settings, load_settings
from teams_ollama_bridge.exceptions import InstanceAlreadyRunningError
from teams_ollama_bridge.file_service import discover_stable_files
from teams_ollama_bridge.logging_config import get_logger, setup_logging
from teams_ollama_bridge.processor import RequestProcessor
from teams_ollama_bridge.repository import RequestRepository

logger = get_logger(__name__)


class Worker:
    """Überwacht den Inputordner und verarbeitet neue Dateien."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._repository = RequestRepository(settings.database_path)
        self._processor = RequestProcessor(settings, self._repository)
        self._running = False
        self._lock: FileLock | None = None

    def acquire_lock(self) -> None:
        """Instanzsperre erwerben."""
        lock_path = self._settings.lock_file_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(lock_path), timeout=0)
        try:
            self._lock.acquire()
        except Timeout as exc:
            raise InstanceAlreadyRunningError(
                "Eine andere Instanz von teams-ollama-bridge läuft bereits. "
                f"Lockdatei: {lock_path}"
            ) from exc
        logger.info("Instanzsperre erworben: %s", lock_path)

    def release_lock(self) -> None:
        """Instanzsperre freigeben."""
        if self._lock is not None and self._lock.is_locked:
            self._lock.release()
            logger.info("Instanzsperre freigegeben.")

    def _release_stale_processing(self) -> None:
        released = self._repository.release_stale_processing(
            self._settings.stale_processing_minutes
        )
        if released:
            logger.warning("%d veraltete processing-Einträge freigegeben.", released)

    def process_pending_files(self, limit: int | None = None) -> int:
        """Alle stabilen, ausstehenden Dateien verarbeiten."""
        self._release_stale_processing()
        stable_files = discover_stable_files(
            self._settings.input_dir,  # type: ignore[arg-type]
            self._settings.file_stable_seconds,
        )
        processed = 0
        for stable_file in stable_files:
            if limit is not None and processed >= limit:
                break
            if self._processor.process_file(stable_file.path):
                processed += 1
        return processed

    def run(self) -> None:
        """Dauerhafte Polling-Schleife."""
        self._running = True
        logger.info(
            "Worker gestartet (Modus=%s, Intervall=%.1fs)",
            self._settings.processor_mode.value,
            self._settings.poll_interval_seconds,
        )

        def handle_signal(signum: int, _frame: FrameType | None) -> None:
            logger.info("Signal %d empfangen, beende Worker...", signum)
            self._running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            while self._running:
                count = self.process_pending_files(limit=1)
                if count:
                    logger.debug("%d Datei(en) in diesem Zyklus verarbeitet.", count)
                time.sleep(self._settings.poll_interval_seconds)
        finally:
            logger.info("Worker beendet.")
            self.release_lock()

    def process_single_file(self, path: Path) -> bool:
        """Genau eine Datei verarbeiten."""
        self._release_stale_processing()
        return self._processor.process_file(path)


def create_worker(settings: Settings | None = None) -> Worker:
    """Worker mit geladener Konfiguration erstellen."""
    resolved_settings = settings or load_settings()
    setup_logging(
        resolved_settings.log_level,
        resolved_settings.log_file_path,
        resolved_settings.log_max_bytes,
        resolved_settings.log_backup_count,
    )
    logger.info("teams-ollama-bridge v1.0.0 gestartet")
    logger.info("Konfiguration: %s", resolved_settings.safe_config_summary())
    worker = Worker(resolved_settings)
    worker.acquire_lock()
    return worker
