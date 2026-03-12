import logging
import os
import threading
from typing import Optional

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

FILES_DIR = os.getenv("FILES_DIR", "/files")
IMPORT_DIR = os.getenv("IMPORT_DIR", "")
SUPPORTED_EXTENSIONS = {".stl", ".3mf", ".obj", ".lys"}

_observer: Optional[Observer] = None


class _PrintFileHandler(FileSystemEventHandler):
    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        if not any(event.src_path.lower().endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            return
        # Import-Verzeichnis ignorieren – Import-Route übernimmt Registrierung
        if IMPORT_DIR and event.src_path.startswith(IMPORT_DIR):
            return
        logger.info(f"New file detected: {event.src_path}")
        from services.scanner import run_scan
        threading.Thread(target=run_scan, daemon=True).start()


def start_watcher() -> None:
    global _observer
    if not os.path.exists(FILES_DIR):
        logger.warning(f"Watch dir {FILES_DIR} not found – watcher not started")
        return
    _observer = Observer()
    _observer.schedule(_PrintFileHandler(), FILES_DIR, recursive=True)
    _observer.start()
    logger.info(f"File watcher started on {FILES_DIR}")


def stop_watcher() -> None:
    global _observer
    if _observer:
        _observer.stop()
        _observer.join()
        logger.info("File watcher stopped")
