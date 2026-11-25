"""Main window: navigation rail + pages."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from zone_new_companion import __version__
from zone_new_companion.services.log_bus import LogBus, LogEntry
from zone_new_companion.state import AppState
from zone_new_companion.ui import theme
from zone_new_companion.ui.media_view import LogoLoader
from zone_new_companion.ui.pages.browser_page import BrowserPage
from zone_new_companion.ui.pages.connection_page import ConnectionPage
from zone_new_companion.ui.pages.journal_page import JournalPage
from zone_new_companion.ui.widgets.common import Toast, button, label

PAGE_CONNECTION, PAGE_LIVE, PAGE_MOVIES, PAGE_SERIES, PAGE_JOURNAL = range(5)
_NAV = [
    ("◉   Connexion", PAGE_CONNECTION),
    ("▶   Chaînes", PAGE_LIVE),
    ("◼   Films", PAGE_MOVIES),
    ("❏   Séries", PAGE_SERIES),
    ("≡   Journal", PAGE_JOURNAL),
]


class MainWindow(QMainWindow):
    def __init__(self, bus: LogBus, app_data: Path, retries: int) -> None:
        super().__init__()
        self.setWindowTitle("Zone Companion")
        self.setMinimumSize(1100, 700)
        self._unseen_problems = 0

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Navigation rail ------------------------------------------------------
        rail = QWidget()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(220)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(14, 22, 14, 18)
        rail_layout.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(0)
        brand.setContentsMargins(10, 0, 0, 0)
        brand.addWidget(label("ZONE", "Brand"))
        brand.addWidget(label(".", "BrandAccent"))
        brand.addStretch(1)
        rail_layout.addLayout(brand)
        sub = label("COMPANION", "BrandSub")
        sub.setContentsMargins(11, 0, 0, 0)
        rail_layout.addWidget(sub)
        rail_layout.addSpacing(26)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.nav_buttons: dict[int, object] = {}
        for text, page in _NAV:
            nav = button(text, "NavButton")
            nav.setCheckable(True)
            self._nav_group.addButton(nav, page)
            self.nav_buttons[page] = nav
            rail_layout.addWidget(nav)
        self._nav_group.idClicked.connect(self.go_to)
        rail_layout.addStretch(1)

        self.connection_status = label("", "Muted", wrap=True)
        self.connection_status.setTextFormat(Qt.TextFormat.RichText)
        self.connection_status.setContentsMargins(10, 0, 0, 0)
        rail_layout.addWidget(self.connection_status)
        rail_layout.addSpacing(6)
        version = label(f"v{__version__}", "Faint")
        version.setContentsMargins(10, 0, 0, 0)
        rail_layout.addWidget(version)
        layout.addWidget(rail)

        # Pages ----------------------------------------------------------------
        right = QWidget()
        right.setObjectName("Page")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setVisible(False)
        right_layout.addWidget(self.progress)
        self.progress_spacer = QWidget()
        self.progress_spacer.setFixedHeight(3)
        right_layout.addWidget(self.progress_spacer)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        layout.addWidget(right, 1)

        self.logo_loader = LogoLoader(app_data / "logo-cache", self)
        self.connection_page = ConnectionPage()
        self.browser_pages = {
            "Live": BrowserPage("Live", self.logo_loader),
            "Movies": BrowserPage("Movies", self.logo_loader),
            "Series": BrowserPage("Series", self.logo_loader),
        }
        self.journal_page = JournalPage(bus, app_data / "logs", retries)
        for widget in (
            self.connection_page,
            self.browser_pages["Live"],
            self.browser_pages["Movies"],
            self.browser_pages["Series"],
            self.journal_page,
        ):
            self.stack.addWidget(widget)
        for page in self.browser_pages.values():
            page.go_connect_requested.connect(lambda: self.go_to(PAGE_CONNECTION))

        self.toast = Toast(self)
        fullscreen = QShortcut(QKeySequence("F11"), self)
        fullscreen.activated.connect(self.toggle_fullscreen)
        leave = QShortcut(QKeySequence("Esc"), self)
        leave.activated.connect(lambda: self.showMaximized() if self.isFullScreen() else None)
        bus.entry_added.connect(self._on_log_entry)
        self.go_to(PAGE_CONNECTION)
        self._render_connection(None)

    # ------------------------------------------------------------ navigation
    def go_to(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        nav = self.nav_buttons[page]
        nav.setChecked(True)
        if page == PAGE_JOURNAL:
            self._unseen_problems = 0
            self._update_journal_badge()

    def _on_log_entry(self, entry: LogEntry) -> None:
        if entry.level in ("WARNING", "ERROR", "CRITICAL") and self.stack.currentIndex() != PAGE_JOURNAL:
            self._unseen_problems += 1
            self._update_journal_badge()

    def _update_journal_badge(self) -> None:
        text = "≡   Journal"
        if self._unseen_problems:
            text += f"   ({self._unseen_problems})"
        self.nav_buttons[PAGE_JOURNAL].setText(text)

    # ----------------------------------------------------------------- state
    def apply_state(self, state: AppState) -> None:
        busy = state.busy
        self.progress.setVisible(busy)
        self.progress_spacer.setVisible(not busy)
        self.connection_page.set_busy(busy)
        connected = state.active_profile is not None and bool(state.credential_info)
        self.connection_page.set_account(state.active_profile if connected else None, state.credential_info)
        for tab_name, page in self.browser_pages.items():
            page.set_connected(connected)
            page.set_busy(busy)
            page.set_categories(state.categories.get(tab_name, []))
            status = dict(state.persistent_verification_results)
            status.update(state.verification_results.get(tab_name, {}))
            page.set_items(state.current_items.get(tab_name, []), status, state.now_playing.get(tab_name, {}))
        self._render_connection(state if connected else None)

    def _render_connection(self, state: AppState | None) -> None:
        if state is None or state.active_profile is None:
            self.connection_status.setText(f"<span style='color:{theme.TEXT_FAINT}'>●</span>&nbsp; Non connecté")
            return
        host = state.active_profile.base_url.split("://", 1)[-1].split("/", 1)[0]
        cons = state.credential_info.get("Active/Max Connections", "")
        extra = f"<br><span style='color:{theme.TEXT_FAINT}'>Connexions {cons}</span>" if cons else ""
        self.connection_status.setText(f"<span style='color:{theme.OK}'>●</span>&nbsp; {host}{extra}")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def notify(self, text: str, kind: str = "info") -> None:
        self.toast.show_message(text, kind)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 28)
