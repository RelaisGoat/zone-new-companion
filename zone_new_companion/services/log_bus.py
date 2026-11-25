"""Bridge Python logging to the UI journal (thread-safe through Qt signals)."""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal


class LogEntry:
    __slots__ = ("timestamp", "level", "source", "message")

    def __init__(self, timestamp: str, level: str, source: str, message: str) -> None:
        self.timestamp = timestamp
        self.level = level
        self.source = source
        self.message = message


class LogBus(QObject):
    """Holds recent entries and broadcasts new ones."""

    entry_added = pyqtSignal(object)
    MAX_ENTRIES = 3000

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[LogEntry] = []

    def publish(self, level: str, source: str, message: str) -> None:
        entry = LogEntry(datetime.now().strftime("%H:%M:%S"), level, source, message)
        self.entries.append(entry)
        if len(self.entries) > self.MAX_ENTRIES:
            del self.entries[: len(self.entries) - self.MAX_ENTRIES]
        self.entry_added.emit(entry)

    def clear(self) -> None:
        self.entries.clear()


_SOURCES = {
    "root": "Appli",
    "app_controller": "Appli",
    "xtream_service": "Xtream",
    "stalker_service": "Stalker",
    "m3u_service": "M3U",
    "stream_verifier": "Vérif",
    "ocr_service": "OCR",
    "player_launcher": "VLC",
}


class _BusHandler(logging.Handler):
    def __init__(self, bus: LogBus) -> None:
        super().__init__(level=logging.INFO)
        self._bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            source = getattr(record, "source", None) or _SOURCES.get(
                record.name.rsplit(".", 1)[-1], record.name.rsplit(".", 1)[-1],
            )
            self._bus.publish(record.levelname, source, record.getMessage())
        except Exception:  # noqa: BLE001 - logging must never crash the app
            pass


log_bus = LogBus()


def install_log_bus() -> None:
    """Attach the bus to the root logger (call after configure_logging)."""
    root = logging.getLogger()
    if not any(isinstance(handler, _BusHandler) for handler in root.handlers):
        root.addHandler(_BusHandler(log_bus))
    # Keep third-party chatter out of the journal.
    for noisy in ("urllib3", "requests", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
