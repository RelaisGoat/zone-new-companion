"""Chaînes / Films / Séries page: categories on the left, big list or grid on the right."""

from __future__ import annotations

from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from zone_new_companion.models import MediaItem, PlaylistCategory
from zone_new_companion.ui.media_view import (
    MEDIA_ROLE,
    LogoLoader,
    MediaDelegate,
    MediaFilterModel,
    MediaListModel,
    MediaListView,
)
from zone_new_companion.ui.widgets.common import EmptyState, button, card, label

_TITLES = {
    "Live": ("Chaînes", "chaînes"),
    "Movies": ("Films", "films"),
    "Series": ("Séries", "séries"),
}


class BrowserPage(QWidget):
    category_selected = pyqtSignal(str, object)
    item_activated = pyqtSignal(str, object)
    verify_item_requested = pyqtSignal(str, object)
    verify_all_requested = pyqtSignal(str)
    cancel_verify_requested = pyqtSignal()
    now_playing_requested = pyqtSignal(str, object)
    back_requested = pyqtSignal(str)
    go_connect_requested = pyqtSignal()

    def __init__(self, tab_name: str, loader: LogoLoader) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.tab_name = tab_name
        title, self._noun = _TITLES[tab_name]
        self._categories: list[PlaylistCategory] = []
        self._items_ref: object = None
        self._current_category = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 30, 36, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "PageTitle"))
        self.subtitle = label("", "PageSubtitle")
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        root.addLayout(header)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.empty = EmptyState(
            "Pas encore connecté",
            "Connecte-toi pour voir la liste.",
            "Aller à la connexion",
        )
        self.empty.action_clicked.connect(self.go_connect_requested.emit)
        self.stack.addWidget(self.empty)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(18)
        self.stack.addWidget(body)

        # Categories --------------------------------------------------------
        cat_card, cat_layout = card(12, 8)
        cat_card.setFixedWidth(250)
        self.category_search = QLineEdit()
        self.category_search.setObjectName("Search")
        self.category_search.setPlaceholderText("Filtrer les catégories")
        self.category_search.setClearButtonEnabled(True)
        self.category_search.textChanged.connect(self._filter_categories)
        cat_layout.addWidget(self.category_search)
        self.category_list = QListWidget()
        self.category_list.setObjectName("CategoryList")
        self.category_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.category_list.itemClicked.connect(self._on_category_clicked)
        cat_layout.addWidget(self.category_list, 1)
        body_layout.addWidget(cat_card)

        # Items -------------------------------------------------------------
        items_card, items_layout = card(12, 10)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.back_button = button("‹  Retour", "Ghost")
        self.back_button.clicked.connect(lambda: self.back_requested.emit(self.tab_name))
        self.back_button.hide()
        toolbar.addWidget(self.back_button)
        self.list_title = label("", "SectionTitle")
        toolbar.addWidget(self.list_title)
        toolbar.addStretch(1)
        self.item_search = QLineEdit()
        self.item_search.setObjectName("Search")
        self.item_search.setPlaceholderText(f"Rechercher dans les {self._noun}")
        self.item_search.setClearButtonEnabled(True)
        self.item_search.setFixedWidth(260)
        toolbar.addWidget(self.item_search)

        self._view_group = QButtonGroup(self)
        self.list_toggle = button("☰", "IconToggle", "Liste")
        self.grid_toggle = button("▦", "IconToggle", "Grille")
        for index, toggle in enumerate((self.list_toggle, self.grid_toggle)):
            toggle.setCheckable(True)
            self._view_group.addButton(toggle, index)
            toolbar.addWidget(toggle)
        self.list_toggle.setChecked(True)
        self._view_group.idClicked.connect(lambda idx: self.view.set_grid(idx == 1))

        self.verify_button = button("Vérifier tout", tooltip="Teste chaque flux de la liste affichée")
        self.verify_button.clicked.connect(lambda: self.verify_all_requested.emit(self.tab_name))
        toolbar.addWidget(self.verify_button)
        items_layout.addLayout(toolbar)

        self.model = MediaListModel(self)
        self.proxy = MediaFilterModel(self)
        self.proxy.setSourceModel(self.model)
        self.item_search.textChanged.connect(self.proxy.setFilterFixedString)
        self.delegate = MediaDelegate(loader, self)
        loader.loaded.connect(self.model.refresh_logo)
        self.view = MediaListView(self.delegate)
        self.view.setModel(self.proxy)
        self.view.doubleClicked.connect(self._activate_index)
        self.view.activated.connect(self._activate_index)
        self.view.clicked.connect(self._on_item_clicked)
        self.delegate.play_clicked.connect(self._activate_index)
        self.view.customContextMenuRequested.connect(self._context_menu)

        self.items_stack = QStackedWidget()
        self.items_empty = EmptyState("Choisis une catégorie", "La liste s'affichera ici.")
        self.items_stack.addWidget(self.items_empty)
        self.items_stack.addWidget(self.view)
        items_layout.addWidget(self.items_stack, 1)
        self.footer = label("Double-clic ou ▶ pour lancer dans VLC · clic droit pour plus d'options", "Faint")
        items_layout.addWidget(self.footer)
        body_layout.addWidget(items_card, 1)

        self._update_subtitle()

    # ------------------------------------------------------------- updates
    def set_connected(self, connected: bool) -> None:
        self.stack.setCurrentIndex(1 if connected else 0)

    def set_categories(self, categories: list[PlaylistCategory]) -> None:
        if categories is self._categories:
            return
        self._categories = categories
        self.category_list.clear()
        for category in categories:
            item = QListWidgetItem(category.name)
            item.setData(Qt.ItemDataRole.UserRole, category)
            self.category_list.addItem(item)
        self._filter_categories(self.category_search.text())
        if not categories:
            self.items_empty.set_text(f"Aucune catégorie de {self._noun}", "Le serveur n'en propose pas.")
        else:
            self.items_empty.set_text("Choisis une catégorie", "La liste s'affichera ici.")
        self._update_subtitle()

    def set_items(self, items: list[MediaItem], status: dict[str, str], now: dict[str, str]) -> None:
        if items is not self._items_ref:
            self._items_ref = items
            self.model.set_items(items)
            self.view.scrollToTop()
            if items:
                self.items_stack.setCurrentIndex(1)
            nested = bool(items) and items[0].item_type in {"season", "episode"}
            self.back_button.setVisible(nested)
            # Logos make the grid worth it; otherwise keep the dense list.
            if self.model.has_logos() and self.tab_name != "Live" and not self.grid_toggle.isChecked():
                self.grid_toggle.click()
        self.model.set_annotations(status, now)
        self._update_subtitle()

    def _update_subtitle(self) -> None:
        cats = len(self._categories)
        count = self.model.rowCount()
        parts = [f"{cats} catégories"] if cats else []
        if count:
            parts.append(f"{count} {self._noun}" + (f" dans « {self._current_category} »" if self._current_category else ""))
        self.subtitle.setText(" · ".join(parts) if parts else "")
        self.list_title.setText(self._current_category)

    def set_busy(self, busy: bool) -> None:
        self.verify_button.setEnabled(not busy)

    # ------------------------------------------------------------- handlers
    def _filter_categories(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.category_list.count()):
            item = self.category_list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _on_category_clicked(self, item: QListWidgetItem) -> None:
        category = item.data(Qt.ItemDataRole.UserRole)
        self._current_category = category.name
        self.item_search.clear()
        self.category_selected.emit(self.tab_name, category)

    def _media(self, index: QModelIndex) -> MediaItem | None:
        return index.data(MEDIA_ROLE) if index.isValid() else None

    def _activate_index(self, index: QModelIndex) -> None:
        media = self._media(index)
        if media is not None:
            self.item_activated.emit(self.tab_name, media)

    def _on_item_clicked(self, index: QModelIndex) -> None:
        media = self._media(index)
        if media is not None:
            self.now_playing_requested.emit(self.tab_name, media)

    def _context_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        media = self._media(index)
        menu = QMenu(self)
        if media is not None:
            play = menu.addAction("Ouvrir" if media.item_type in {"series", "season"} else "▶  Lire dans VLC")
            play.triggered.connect(lambda: self.item_activated.emit(self.tab_name, media))
            if media.item_type in {"channel", "vod", "episode"}:
                verify = menu.addAction("Vérifier ce flux")
                verify.triggered.connect(lambda: self.verify_item_requested.emit(self.tab_name, media))
            if media.stream_url:
                copy = menu.addAction("Copier le lien du flux")
                copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(media.stream_url or ""))
            menu.addSeparator()
        if self.back_button.isVisible():
            back = menu.addAction("‹  Retour")
            back.triggered.connect(lambda: self.back_requested.emit(self.tab_name))
        cancel = menu.addAction("Annuler les vérifications")
        cancel.triggered.connect(self.cancel_verify_requested.emit)
        menu.exec(self.view.viewport().mapToGlobal(pos))
