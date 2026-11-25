"""Connexion page: paste a link or fill the form, see account details, history."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from zone_new_companion.models import Credentials, PortalType
from zone_new_companion.services.link_parser import parse_link
from zone_new_companion.ui import theme
from zone_new_companion.ui.widgets.common import SegmentBar, Tile, button, card, label

_INFO_LABELS = {
    "Status": "Statut",
    "Expiry": "Expire le",
    "Active/Max Connections": "Connexions actives",
    "Real URL": "Serveur réel",
    "Ports": "Ports",
    "Timezone": "Fuseau horaire",
    "Created At": "Créé le",
}


def _mask(secret: str) -> str:
    if len(secret) <= 3:
        return "•" * len(secret)
    return secret[:2] + "•" * (len(secret) - 2)


def _field(title: str, widget: QWidget) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(label(title, "FieldLabel"))
    layout.addWidget(widget)
    return box


class ConnectionPage(QWidget):
    connect_requested = pyqtSignal(object)
    refresh_requested = pyqtSignal()
    disconnect_requested = pyqtSignal()
    history_clear_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Page")
        self._history: list[Credentials] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        content.setObjectName("Page")
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(36, 30, 36, 30)
        root.setSpacing(22)
        root.addWidget(label("Connexion", "PageTitle"))
        root.addWidget(label("Colle le lien de ton fournisseur ou remplis les champs à la main.", "PageSubtitle"))

        columns = QHBoxLayout()
        columns.setSpacing(22)
        root.addLayout(columns, 1)

        left = QVBoxLayout()
        left.setSpacing(22)
        columns.addLayout(left, 3)
        left.addWidget(self._build_login_card())
        self.account_card = self._build_account_card()
        self.account_card.hide()
        left.addWidget(self.account_card)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(22)
        right.addWidget(self._build_history_card())
        right.addStretch(1)
        columns.addLayout(right, 2)

    # ------------------------------------------------------------ builders
    def _build_login_card(self):
        frame, layout = card(22, 16)
        header = QHBoxLayout()
        header.addWidget(label("Se connecter", "SectionTitle"))
        header.addStretch(1)
        self.mode_bar = SegmentBar(["Coller un lien", "Saisie manuelle"])
        header.addWidget(self.mode_bar)
        layout.addLayout(header)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._build_link_mode())
        self.mode_stack.addWidget(self._build_manual_mode())
        self.mode_bar.changed.connect(self.mode_stack.setCurrentIndex)
        layout.addWidget(self.mode_stack)

        bottom = QHBoxLayout()
        self.form_error = label("", "Error", wrap=True)
        bottom.addWidget(self.form_error, 1)
        self.logout_button = button("Se déconnecter", tooltip="Fermer la session en cours")
        self.logout_button.clicked.connect(self.disconnect_requested.emit)
        self.logout_button.hide()
        bottom.addWidget(self.logout_button)
        self.connect_button = button("Se connecter", "Primary")
        self.connect_button.clicked.connect(self._emit_connect)
        bottom.addWidget(self.connect_button)
        layout.addLayout(bottom)
        return frame

    def _build_link_mode(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self.link_input = QLineEdit()
        self.link_input.setObjectName("BigInput")
        self.link_input.setPlaceholderText("http://serveur:port/get.php?username=…&password=…   ou un lien de chaîne")
        self.link_input.setClearButtonEnabled(True)
        self.link_input.textChanged.connect(self._on_link_changed)
        self.link_input.returnPressed.connect(self._emit_connect)
        layout.addWidget(self.link_input)

        self.detect_label = label("", "Muted", wrap=True)
        self.detect_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.detect_label)

        self.link_mac = QLineEdit()
        self.link_mac.setPlaceholderText("00:1A:79:00:00:00")
        self.link_mac_box = _field("Adresse MAC", self.link_mac)
        self.link_mac_box.hide()
        layout.addWidget(self.link_mac_box)
        layout.addWidget(
            label(
                "Accepté : get.php, player_api.php, xmltv.php, liens de chaîne (/live/…, /login/mdp/id), "
                "playlists .m3u, portails Stalker.",
                "Faint",
                wrap=True,
            ),
        )
        self._on_link_changed("")
        return box

    def _build_manual_mode(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)
        self.type_bar = SegmentBar(["Xtream", "M3U", "Stalker"])
        row = QHBoxLayout()
        row.addWidget(self.type_bar)
        row.addStretch(1)
        layout.addLayout(row)

        self.type_stack = QStackedWidget()
        # Xtream
        xtream = QWidget()
        grid = QGridLayout(xtream)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.x_server = QLineEdit()
        self.x_server.setPlaceholderText("http://serveur:port")
        self.x_user = QLineEdit()
        self.x_pass = QLineEdit()
        self.x_pass.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(_field("Serveur", self.x_server), 0, 0, 1, 2)
        grid.addWidget(_field("Identifiant", self.x_user), 1, 0)
        grid.addWidget(_field("Mot de passe", self.x_pass), 1, 1)
        self.type_stack.addWidget(xtream)
        # M3U
        m3u = QWidget()
        m3u_layout = QVBoxLayout(m3u)
        m3u_layout.setContentsMargins(0, 0, 0, 0)
        self.m3u_url = QLineEdit()
        self.m3u_url.setPlaceholderText("http://exemple.com/playlist.m3u")
        m3u_layout.addWidget(_field("URL de la playlist", self.m3u_url))
        m3u_layout.addStretch(1)
        self.type_stack.addWidget(m3u)
        # Stalker
        stalker = QWidget()
        st_layout = QGridLayout(stalker)
        st_layout.setContentsMargins(0, 0, 0, 0)
        st_layout.setHorizontalSpacing(12)
        self.s_portal = QLineEdit()
        self.s_portal.setPlaceholderText("http://portail.com/c/")
        self.s_mac = QLineEdit()
        self.s_mac.setPlaceholderText("00:1A:79:00:00:00")
        st_layout.addWidget(_field("Portail", self.s_portal), 0, 0)
        st_layout.addWidget(_field("Adresse MAC", self.s_mac), 0, 1)
        self.type_stack.addWidget(stalker)

        self.type_bar.changed.connect(self.type_stack.setCurrentIndex)
        layout.addWidget(self.type_stack)
        for field in (self.x_server, self.x_user, self.x_pass, self.m3u_url, self.s_portal, self.s_mac):
            field.returnPressed.connect(self._emit_connect)
        return box

    def _build_account_card(self):
        frame, layout = card(22, 16)
        header = QHBoxLayout()
        self.account_title = label("Compte", "SectionTitle")
        header.addWidget(self.account_title)
        header.addStretch(1)
        self.refresh_button = button("↻  Rafraîchir", tooltip="Relire les infos du compte (connexions actives…)")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        self.account_hint = label("", "Faint", wrap=True)
        layout.addWidget(self.account_hint)
        self.tiles_grid = QGridLayout()
        self.tiles_grid.setHorizontalSpacing(12)
        self.tiles_grid.setVerticalSpacing(12)
        layout.addLayout(self.tiles_grid)
        self._tiles: list[Tile] = []
        return frame

    def _build_history_card(self):
        frame, layout = card(18, 10)
        header = QHBoxLayout()
        header.addWidget(label("Récents", "SectionTitle"))
        header.addStretch(1)
        clear = button("Effacer", "Ghost")
        clear.clicked.connect(self.history_clear_requested.emit)
        header.addWidget(clear)
        layout.addLayout(header)
        layout.addWidget(label("Clic : remplir le formulaire · Double-clic : se connecter", "Faint"))
        self.history_list = QListWidget()
        self.history_list.setObjectName("HistoryList")
        self.history_list.setMinimumHeight(140)
        self.history_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.history_list.itemClicked.connect(lambda item: self._pick_history(item, connect=False))
        self.history_list.itemDoubleClicked.connect(lambda item: self._pick_history(item, connect=True))
        layout.addWidget(self.history_list)
        self.history_empty = label("Les connexions réussies apparaîtront ici.", "Muted", wrap=True)
        layout.addWidget(self.history_empty)
        frame.setMinimumWidth(300)
        return frame

    # ------------------------------------------------------------- link mode
    def _on_link_changed(self, text: str) -> None:
        parsed = parse_link(text)
        if hasattr(self, "form_error"):
            self.form_error.setText("")
        self.link_mac_box.setVisible(parsed.needs_mac)
        if not text.strip():
            self.detect_label.setText("")
            return
        if not parsed.ok:
            self.detect_label.setText(f"<span style='color:{theme.ERROR}'>✖ {parsed.error}</span>")
            return
        parts = [f"<span style='color:{theme.OK}'>✔ {parsed.description}</span>"]
        if parsed.portal_type == PortalType.M3U:
            parts.append(f"Playlist : <b>{parsed.playlist_url}</b>")
        else:
            parts.append(f"Serveur : <b>{parsed.base_url}</b>")
            if parsed.username:
                parts.append(f"Identifiant : <b>{parsed.username}</b> · Mot de passe : <b>{_mask(parsed.password)}</b>")
        self.detect_label.setText("<br>".join(parts))

    # ------------------------------------------------------------- emitting
    def current_credentials(self) -> Credentials | None:
        self.form_error.setText("")
        if self.mode_stack.currentIndex() == 0:
            parsed = parse_link(self.link_input.text())
            if not parsed.ok:
                self.form_error.setText(parsed.error or "Colle un lien d'abord.")
                return None
            return parsed.to_credentials(self.link_mac.text().strip())
        kind = self.type_stack.currentIndex()
        if kind == 0:
            server = self.x_server.text().strip()
            # People often paste a full link in the server field: be nice.
            parsed = parse_link(server)
            if parsed.ok and parsed.username and not self.x_user.text().strip():
                return parsed.to_credentials()
            return Credentials(
                name="Manuel",
                base_url=server,
                portal_type=PortalType.XTREAM,
                username=self.x_user.text().strip(),
                password=self.x_pass.text().strip(),
            )
        if kind == 1:
            return Credentials(name="Manuel", base_url=self.m3u_url.text().strip(), portal_type=PortalType.M3U)
        return Credentials(
            name="Manuel",
            base_url=self.s_portal.text().strip(),
            portal_type=PortalType.STALKER,
            mac_address=self.s_mac.text().strip(),
        )

    def _emit_connect(self) -> None:
        credentials = self.current_credentials()
        if credentials is not None:
            self.connect_requested.emit(credentials)

    def show_error(self, message: str) -> None:
        self.form_error.setText(message)

    def set_busy(self, busy: bool) -> None:
        self.connect_button.setEnabled(not busy)
        if busy:
            self.connect_button.setText("Connexion…")
        elif self.connect_button.text() == "Connexion…":
            self.connect_button.setText("Changer de compte" if self.logout_button.isVisible() else "Se connecter")
        self.refresh_button.setEnabled(not busy)

    def populate(self, credentials: Credentials) -> None:
        self.mode_bar.set_current(1)
        if credentials.portal_type == PortalType.XTREAM:
            self.type_bar.set_current(0)
            self.x_server.setText(credentials.base_url)
            self.x_user.setText(credentials.username)
            self.x_pass.setText(credentials.password)
        elif credentials.portal_type == PortalType.M3U:
            self.type_bar.set_current(1)
            self.m3u_url.setText(credentials.base_url)
        else:
            self.type_bar.set_current(2)
            self.s_portal.setText(credentials.base_url)
            self.s_mac.setText(credentials.mac_address)

    def clear(self) -> None:
        for field in (self.link_input, self.link_mac, self.x_server, self.x_user, self.x_pass, self.m3u_url, self.s_portal, self.s_mac):
            field.clear()

    # --------------------------------------------------------------- history
    def set_history(self, history: list[Credentials]) -> None:
        self._history = list(history)
        self.history_list.clear()
        for index, entry in enumerate(self._history):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, index)
            widget = QWidget()
            row = QVBoxLayout(widget)
            row.setContentsMargins(12, 9, 12, 9)
            row.setSpacing(2)
            host = entry.base_url.split("://", 1)[-1].split("/", 1)[0]
            who = entry.username or entry.mac_address or "playlist"
            row.addWidget(label(host, "SectionTitle"))
            when = ""
            if entry.saved_at:
                try:
                    when = datetime.fromisoformat(entry.saved_at).strftime("%d/%m %H:%M")
                except ValueError:
                    when = entry.saved_at[:10]
            row.addWidget(label(f"{entry.portal_type.value.upper()} · {who}" + (f" · {when}" if when else ""), "Faint"))
            item.setSizeHint(widget.sizeHint())
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, widget)
        self.history_empty.setVisible(not self._history)
        self.history_list.setVisible(bool(self._history))

    def _pick_history(self, item: QListWidgetItem, connect: bool) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not (0 <= index < len(self._history)):
            return
        entry = self._history[index]
        self.populate(entry)
        if connect:
            self.connect_requested.emit(entry)

    # --------------------------------------------------------------- account
    def set_account(self, profile: Credentials | None, info: dict[str, str]) -> None:
        connected = profile is not None and bool(info)
        self.logout_button.setVisible(connected)
        self.connect_button.setText("Changer de compte" if connected else "Se connecter")
        if not connected:
            self.account_card.hide()
            return
        self.account_card.show()
        host = profile.base_url.split("://", 1)[-1]
        self.account_title.setText(f"Compte · {host}")
        while self._tiles:
            tile = self._tiles.pop()
            self.tiles_grid.removeWidget(tile)
            tile.deleteLater()
        hint = ""
        for position, (key, value) in enumerate(info.items()):
            tile = Tile(_INFO_LABELS.get(key, key))
            color = None
            if key == "Status":
                color = theme.OK if str(value).lower() == "active" else theme.WARN
                value = {"active": "Actif", "expired": "Expiré", "banned": "Banni", "disabled": "Désactivé"}.get(
                    str(value).lower(), value,
                )
            if key == "Active/Max Connections":
                active, _, maximum = str(value).partition("/")
                if active.isdigit() and maximum.isdigit():
                    full = int(active) >= int(maximum)
                    color = theme.ERROR if full else theme.OK
                    value = f"{active} / {maximum}"
                    if full:
                        hint = (
                            "Toutes les connexions sont prises : si rien n'est ouvert chez toi, quelqu'un d'autre "
                            "utilise cette ligne en ce moment. Lancer une chaîne risque d'échouer (HTTP 401)."
                        )
            if key == "Expiry" and value == "Unlimited":
                value = "Illimité"
            if key in ("Expiry", "Created At"):
                try:
                    value = datetime.strptime(str(value), "%Y-%m-%d %H:%M").strftime("%d/%m/%Y à %H:%M")
                except ValueError:
                    pass
            if key == "Real URL":
                value = str(value).split("://", 1)[-1]
            tile.set_value(str(value), color)
            self.tiles_grid.addWidget(tile, position // 3, position % 3)
            self._tiles.append(tile)
        self.account_hint.setText(hint)
        self.account_hint.setVisible(bool(hint))
        self.account_hint.setStyleSheet(f"color: {theme.WARN};" if hint else "")


__all__ = ["ConnectionPage"]
