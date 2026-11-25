"""Application bootstrap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Set Windows AppUserModelID BEFORE any UI initialization (must be before QApplication)
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("zone-companion.app")
    except Exception:  # noqa: BLE001
        pass

# Determine base directory for resources (PyInstaller or normal)
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from zone_new_companion import __version__
from zone_new_companion.config import ConfigStore
from zone_new_companion.controllers.app_controller import AppController
from zone_new_companion.logging_config import configure_logging
from zone_new_companion.models import Credentials
from zone_new_companion.services.log_bus import install_log_bus, log_bus
from zone_new_companion.state import StateStore
from zone_new_companion.ui import theme
from zone_new_companion.ui.main_window import PAGE_CONNECTION, PAGE_LIVE, MainWindow


def run() -> None:
    """Start the GUI application."""
    app_data = Path.home() / ".zone-new-companion"
    log_dir = app_data / "logs"
    configure_logging(log_dir)
    install_log_bus()

    config_store = ConfigStore(app_data / "config.json")
    state_store = StateStore()
    controller = AppController(state_store, config_store, log_dir=log_dir)

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Zone Companion")
    qt_app.setApplicationVersion(__version__)
    qt_app.setFont(QFont(theme.FONT_FAMILY, 10))
    qt_app.setStyleSheet(theme.STYLESHEET)

    icon_path = os.path.join(BASE_DIR, "zone_new_companion", "icon", "icon.ico")
    if os.path.exists(icon_path):
        qt_app.setWindowIcon(QIcon(icon_path))

    window = MainWindow(log_bus, app_data, controller.config.ui.auto_retries)
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
    window.resize(controller.config.ui.width, controller.config.ui.height)

    connection = window.connection_page

    def notify_ok(message: str) -> None:
        window.notify(message, "ok")

    def notify_error(message: str) -> None:
        window.notify(message, "error")

    def refresh_history() -> None:
        connection.set_history(controller.history_entries())

    def on_connected(message: str) -> None:
        refresh_history()
        notify_ok(message)
        window.go_to(PAGE_LIVE)

    def on_connect_error(message: str) -> None:
        connection.show_error(message)
        notify_error(message)

    def do_connect(credentials: Credentials) -> None:
        connection.show_error("")
        controller.connect(credentials, on_success=on_connected, on_error=on_connect_error)

    def do_disconnect() -> None:
        controller.reset_form()
        window.go_to(PAGE_CONNECTION)
        window.notify("Déconnecté")

    def do_clear_history() -> None:
        controller.clear_history()
        refresh_history()

    state_store.state_changed.connect(window.apply_state)
    controller.set_playback_progress_callback(lambda text: window.notify(text, "info"))

    connection.connect_requested.connect(do_connect)
    connection.refresh_requested.connect(lambda: controller.refresh_connection_info(notify_ok, notify_error))
    connection.disconnect_requested.connect(do_disconnect)
    connection.history_clear_requested.connect(do_clear_history)

    for page in window.browser_pages.values():
        page.category_selected.connect(
            lambda tab, category: controller.load_items(tab, category, on_success=lambda _m: None, on_error=notify_error),
        )
        page.item_activated.connect(
            lambda tab, item: controller.activate_item(tab, item, on_success=notify_ok, on_error=notify_error),
        )
        page.verify_item_requested.connect(
            lambda tab, item: controller.verify_single_item(tab, item, on_success=notify_ok, on_error=notify_error),
        )
        page.verify_all_requested.connect(
            lambda tab: controller.verify_all_channels(tab, on_success=notify_ok, on_error=notify_error),
        )
        page.cancel_verify_requested.connect(lambda: controller.cancel_verification(notify_ok, notify_error))
        page.now_playing_requested.connect(controller.request_now_playing)
        page.back_requested.connect(lambda tab: controller.go_back(tab))

    window.journal_page.retries_changed.connect(controller.set_auto_retries)

    refresh_history()
    if controller.config.last_input:
        connection.populate(controller.config.last_input)

    qt_app.aboutToQuit.connect(lambda: controller.save_ui_state(window.width(), window.height()))
    window.show()
    sys.exit(qt_app.exec())
