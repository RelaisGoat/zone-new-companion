"""Journal page: everything the app and VLC do, in plain French."""

from __future__ import annotations

import html
import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget

from zone_new_companion.services.log_bus import LogBus, LogEntry
from zone_new_companion.ui import theme
from zone_new_companion.ui.widgets.common import button, card, label

_LEVEL_COLORS = {
    "DEBUG": theme.TEXT_FAINT,
    "INFO": theme.TEXT,
    "WARNING": theme.WARN,
    "ERROR": theme.ERROR,
    "CRITICAL": theme.ERROR,
}
_FILTERS = ["Tout", "Lecture (VLC)", "Avertissements et erreurs"]


class JournalPage(QWidget):
    retries_changed = pyqtSignal(int)

    def __init__(self, bus: LogBus, log_dir: Path, retries: int) -> None:
        super().__init__()
        self.setObjectName("Page")
        self._bus = bus
        self._log_dir = log_dir

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 30, 36, 24)
        root.setSpacing(18)
        root.addWidget(label("Journal", "PageTitle"))
        root.addWidget(
            label(
                "Ce que fait l'appli et ce que VLC reçoit vraiment du serveur (codes HTTP, redirections, image reçue).",
                "PageSubtitle",
                wrap=True,
            ),
        )

        frame, layout = card(14, 10)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(_FILTERS)
        self.filter_combo.currentIndexChanged.connect(self._rebuild)
        toolbar.addWidget(self.filter_combo)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Rechercher")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild)
        toolbar.addWidget(self.search, 1)
        toolbar.addSpacing(8)
        toolbar.addWidget(label("Relances auto", "Muted"))
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setValue(retries)
        self.retries.setToolTip("Combien de fois relancer VLC si le serveur refuse (401, 456…)")
        self.retries.valueChanged.connect(self.retries_changed.emit)
        toolbar.addWidget(self.retries)
        toolbar.addSpacing(8)
        copy = button("Copier")
        copy.clicked.connect(self._copy)
        toolbar.addWidget(copy)
        folder = button("Dossier des logs", tooltip=str(log_dir))
        folder.clicked.connect(self._open_folder)
        toolbar.addWidget(folder)
        clear = button("Effacer", "Ghost")
        clear.clicked.connect(self._clear)
        toolbar.addWidget(clear)
        layout.addLayout(toolbar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(4000)
        mono = QFont("Cascadia Mono" if sys.platform == "win32" else "JetBrains Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSizeF(9.5)
        self.view.setFont(mono)
        self.view.setStyleSheet(f"QPlainTextEdit {{ background: {theme.BG}; border-radius: 10px; padding: 8px; }}")
        layout.addWidget(self.view, 1)
        root.addWidget(frame, 1)

        bus.entry_added.connect(self._append)
        self._rebuild()

    def _accept(self, entry: LogEntry) -> bool:
        mode = self.filter_combo.currentIndex()
        if mode == 1 and entry.source != "VLC":
            return False
        if mode == 2 and entry.level not in ("WARNING", "ERROR", "CRITICAL"):
            return False
        needle = self.search.text().strip().lower()
        return not needle or needle in entry.message.lower() or needle in entry.source.lower()

    def _format(self, entry: LogEntry) -> str:
        color = _LEVEL_COLORS.get(entry.level, theme.TEXT)
        source_color = theme.ACCENT if entry.source == "VLC" else theme.INFO
        return (
            f"<span style='color:{theme.TEXT_FAINT}'>{entry.timestamp}</span>&nbsp;&nbsp;"
            f"<span style='color:{source_color}'>{html.escape(entry.source[:12]):<12}</span>&nbsp;&nbsp;"
            f"<span style='color:{color}'>{html.escape(entry.message)}</span>"
        )

    def _append(self, entry: LogEntry) -> None:
        if not self._accept(entry):
            return
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.view.appendHtml(self._format(entry))
        if at_bottom:
            bar.setValue(bar.maximum())

    def _rebuild(self) -> None:
        self.view.clear()
        for entry in self._bus.entries:
            if self._accept(entry):
                self.view.appendHtml(self._format(entry))
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _copy(self) -> None:
        lines = [
            f"{e.timestamp}  {e.level:<7}  {e.source:<12}  {e.message}" for e in self._bus.entries if self._accept(e)
        ]
        QGuiApplication.clipboard().setText("\n".join(lines))

    def _clear(self) -> None:
        self._bus.clear()
        self.view.clear()

    def _open_folder(self) -> None:
        path = str(self._log_dir)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass
