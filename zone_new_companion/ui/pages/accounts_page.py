"""Secours page: backup accounts, pasted in bulk, with live status dots."""

from __future__ import annotations

import logging
import re
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from zone_new_companion.models import Credentials, PortalType
from zone_new_companion.services.link_parser import parse_link
from zone_new_companion.ui import theme
from zone_new_companion.ui.widgets.common import button, card, label

LOGGER = logging.getLogger("zone.secours")


def account_key(account: Credentials) -> str:
    return f"{account.portal_type.value}|{account.base_url.lower()}|{account.username}"


def parse_bulk(text: str) -> tuple[list[Credentials], list[str]]:
    """One account per line. Optional name before the link: ``Paul http://…`` or ``Paul : http://…``."""
    accounts: list[Credentials] = []
    errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        name = ""
        match = re.search(r"(https?://\S+)", line)
        link = line
        if match:
            link = match.group(1)
            name = line[: match.start()].strip(" :-–|\t")
        parsed = parse_link(link)
        if not parsed.ok:
            errors.append(f"« {line[:60]} » : {parsed.error or 'lien non reconnu'}")
            continue
        if parsed.portal_type == PortalType.STALKER:
            errors.append(f"« {line[:60]} » : un portail Stalker ne peut pas servir de secours")
            continue
        account = parsed.to_credentials()
        account.name = name
        accounts.append(account)
    return accounts, errors


class _Dot(QWidget):
    def __init__(self, color: str) -> None:
        super().__init__()
        self.setFixedSize(12, 12)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.setStyleSheet(f"background: {color}; border-radius: 6px;")


class AccountsPage(QWidget):
    accounts_changed = pyqtSignal(list)
    check_requested = pyqtSignal(list)  # list[Credentials] to query

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Page")
        self._accounts: list[Credentials] = []
        # key -> (state, connections text, detail, checked_at)
        self._status: dict[str, tuple[str, str, str, str]] = {}

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
        root.setSpacing(18)

        root.addWidget(label("Comptes de secours", "PageTitle"))
        root.addWidget(
            label(
                "Si une chaîne refuse de passer sur ton compte, l'appli la relance sur ces comptes : "
                "d'abord ceux qui ont une connexion libre, puis les autres. Les comptes invalides sont ignorés.",
                "PageSubtitle",
                wrap=True,
            ),
        )

        # Accounts list --------------------------------------------------------
        list_card, list_layout = card(18, 10)
        header = QHBoxLayout()
        header.addWidget(label("Comptes", "SectionTitle"))
        self.summary = label("", "Muted")
        header.addWidget(self.summary)
        header.addStretch(1)
        self.last_check = label("", "Faint")
        header.addWidget(self.last_check)
        self.refresh_button = button("↻  Tout vérifier", tooltip="Interroge chaque compte (ne lance aucune chaîne)")
        self.refresh_button.clicked.connect(self.check_all)
        header.addWidget(self.refresh_button)
        self.clear_button = button("Tout retirer", tooltip="Supprimer tous les comptes de secours")
        self.clear_button.clicked.connect(self._remove_all)
        header.addWidget(self.clear_button)
        list_layout.addLayout(header)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        list_layout.addLayout(self.rows)
        self.empty = label("Aucun compte pour l'instant : colle des liens ci-dessous.", "Muted")
        list_layout.addWidget(self.empty)
        root.addWidget(list_card)

        # Bulk paste -----------------------------------------------------------
        add_card, add_layout = card(18, 10)
        add_layout.addWidget(label("Ajouter", "SectionTitle"))
        add_layout.addWidget(
            label(
                "Colle un ou plusieurs liens, un par ligne. Pour nommer un compte, écris le nom devant : "
                "« Paul http://serveur/get.php?username=…&password=… ».",
                "Faint",
                wrap=True,
            ),
        )
        self.bulk = QPlainTextEdit()
        self.bulk.setPlaceholderText(
            "Paul http://serveur:80/get.php?username=…&password=…\nhttp://autre-serveur/live/login/mdp/12345.ts",
        )
        self.bulk.setFixedHeight(110)
        self.bulk.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};"
            f" border-radius: 9px; padding: 8px; }} QPlainTextEdit:focus {{ border-color: {theme.ACCENT}; }}",
        )
        self.bulk.textChanged.connect(self._preview)
        add_layout.addWidget(self.bulk)
        row = QHBoxLayout()
        self.preview = label("", "Faint", wrap=True)
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.preview, 1)
        self.add_button = button("Ajouter", "Primary")
        self.add_button.setToolTip("Ctrl+Entrée")
        self.add_button.clicked.connect(self._add_bulk)
        row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)
        add_layout.addLayout(row)
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.bulk)
        shortcut.activated.connect(self._add_bulk)
        root.addWidget(add_card)
        root.addStretch(1)

        self._checking = False
        self._row_widgets: dict[str, AccountRow] = {}
        self._checking_keys: set[str] = set()
        self._removed_note = ""
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render)
        self._preview()

    # -------------------------------------------------------------- public
    def set_accounts(self, accounts: list[Credentials]) -> None:
        self._accounts = list(accounts)
        self._render()

    def check_all(self) -> None:
        if not self._accounts or self._checking:
            return
        self._checking = True
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Vérification…")
        self._checking_keys = {account_key(account) for account in self._accounts}
        self._render()
        self.check_requested.emit(list(self._accounts))

    def set_status(self, account: Credentials, info: dict[str, str] | None, error: str = "") -> None:
        key = account_key(account)
        self._checking_keys.discard(key)
        if not any(account_key(a) == key for a in self._accounts):
            return  # removed meanwhile
        now = datetime.now().strftime("%H:%M")
        if info is None:
            self._status[key] = ("bad", "", error or "injoignable", now)
        elif info.get("Type") == "M3U Playlist":
            self._status[key] = ("unknown", "", "playlist M3U (vérifiée au moment de la bascule)", now)
        else:
            status = str(info.get("Status", "")).lower()
            if status == "expired":
                self._drop(key, "abonnement expiré")
                return
            cons = str(info.get("Active/Max Connections", ""))
            expiry = str(info.get("Expiry", ""))
            try:
                expiry = datetime.strptime(expiry, "%Y-%m-%d %H:%M").strftime("%d/%m/%Y")
            except ValueError:
                pass
            if status == "active":
                active, _, maximum = cons.partition("/")
                full = active.isdigit() and maximum.isdigit() and int(active) >= int(maximum)
                state = "full" if full else "ok"
                detail = f"expire le {expiry}" if expiry and expiry != "Unlimited" else "sans expiration"
            else:
                state = "bad"
                detail = {
                    "banned": "compte banni",
                    "disabled": "compte désactivé",
                    "unknown": "identifiants refusés",
                    "": "identifiants refusés",
                }.get(status, status)
            self._status[key] = (state, cons, detail, now)
        self.last_check.setText(f"Vérifié à {now}")
        self._schedule_render()

    def checking_done(self) -> None:
        self._checking = False
        self._checking_keys.clear()
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("↻  Tout vérifier")
        self._render()

    # ------------------------------------------------------------- editing
    def _preview(self) -> None:
        accounts, errors = parse_bulk(self.bulk.toPlainText())
        parts = []
        if accounts:
            parts.append(f"<span style='color:{theme.OK}'>✔ {len(accounts)} compte(s) prêt(s)</span>")
        for error in errors[:3]:
            parts.append(f"<span style='color:{theme.ERROR}'>✖ {error}</span>")
        if len(errors) > 3:
            parts.append(f"<span style='color:{theme.ERROR}'>… et {len(errors) - 3} autre(s) ligne(s) illisible(s)</span>")
        self.preview.setText("<br>".join(parts))
        self.add_button.setEnabled(bool(accounts))

    def _add_bulk(self) -> None:
        accounts, _errors = parse_bulk(self.bulk.toPlainText())
        if not accounts:
            return
        known = {account_key(a) for a in self._accounts}
        added = []
        for account in accounts:
            key = account_key(account)
            if key in known:
                continue
            known.add(key)
            self._accounts.append(account)
            self._checking_keys.add(key)
            added.append(account)
        self.bulk.clear()
        self._render()
        self.accounts_changed.emit(list(self._accounts))
        if added:
            self.check_requested.emit(added)

    def _drop(self, key: str, reason: str) -> None:
        for index, account in enumerate(self._accounts):
            if account_key(account) == key:
                LOGGER.warning("Compte de secours « %s » retiré automatiquement : %s", _title(account), reason)
                del self._accounts[index]
                self._status.pop(key, None)
                self._removed_note = f"« {_title(account)} » retiré : {reason}"
                self.accounts_changed.emit(list(self._accounts))
                self._schedule_render()
                return

    def _move(self, key: str, delta: int) -> None:
        """Swap with the neighbour shown above/below (same priority group only)."""
        order = self._display_order()
        position = next((i for i, a in enumerate(order) if account_key(a) == key), -1)
        target = position + delta
        if position < 0 or not 0 <= target < len(order):
            return
        first, second = order[position], order[target]
        i, j = self._accounts.index(first), self._accounts.index(second)
        self._accounts[i], self._accounts[j] = self._accounts[j], self._accounts[i]
        self._render()
        self.accounts_changed.emit(list(self._accounts))

    def _remove(self, key: str) -> None:
        self._accounts = [a for a in self._accounts if account_key(a) != key]
        self._status.pop(key, None)
        self._render()
        self.accounts_changed.emit(list(self._accounts))

    def _remove_all(self) -> None:
        if not self._accounts:
            return
        answer = QMessageBox.question(
            self,
            "Tout retirer",
            f"Retirer les {len(self._accounts)} comptes de secours ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._accounts.clear()
        self._status.clear()
        self._render()
        self.accounts_changed.emit([])

    def _rename(self, key: str) -> None:
        account = next((a for a in self._accounts if account_key(a) == key), None)
        if account is None:
            return
        name, ok = QInputDialog.getText(self, "Renommer", "Nom du compte :", text=account.name)
        if ok:
            account.name = name.strip()
            self._render()
            self.accounts_changed.emit(list(self._accounts))

    # ------------------------------------------------------------ rendering
    def _state(self, account: Credentials) -> str:
        return self._status.get(account_key(account), ("", "", "", ""))[0]

    def _display_order(self) -> list[Credentials]:
        """Exactly the order a fallback would use: free, unknown, full, then invalid."""
        indexed = list(enumerate(self._accounts))
        indexed.sort(key=lambda pair: (_RANK.get(self._state(pair[1]), 1), pair[0]))
        return [account for _index, account in indexed]

    def _schedule_render(self) -> None:
        # Many results arrive within milliseconds: repaint once per burst.
        if not self._render_timer.isActive():
            self._render_timer.start(120)

    def _render(self) -> None:
        self._render_timer.stop()
        self.setUpdatesEnabled(False)
        try:
            order = self._display_order()
            wanted = [account_key(a) for a in order]
            # Drop widgets of removed accounts.
            for key in list(self._row_widgets):
                if key not in wanted:
                    widget = self._row_widgets.pop(key)
                    self.rows.removeWidget(widget)
                    widget.deleteLater()
            counts = {"ok": 0, "full": 0, "bad": 0}
            for position, account in enumerate(order):
                key = account_key(account)
                state, cons, detail, _checked = self._status.get(key, ("", "", "", ""))
                if state in counts:
                    counts[state] += 1
                row = self._row_widgets.get(key)
                if row is None:
                    row = AccountRow(key)
                    row.rename_clicked.connect(self._rename)
                    row.move_clicked.connect(self._move)
                    row.remove_clicked.connect(self._remove)
                    self._row_widgets[key] = row
                previous_rank = _RANK.get(self._state(order[position - 1]), 1) if position > 0 else None
                next_rank = _RANK.get(self._state(order[position + 1]), 1) if position + 1 < len(order) else None
                rank = _RANK.get(state, 1)
                row.update_view(
                    position + 1,
                    account,
                    "checking" if key in self._checking_keys else state,
                    cons,
                    detail,
                    can_up=previous_rank == rank,
                    can_down=next_rank == rank,
                )
                if self.rows.indexOf(row) != position:
                    self.rows.removeWidget(row)
                    self.rows.insertWidget(position, row)
            self.empty.setVisible(not self._accounts)
            self.clear_button.setEnabled(bool(self._accounts))
            parts = []
            if counts["ok"]:
                parts.append(f"{counts['ok']} libre(s)")
            if counts["full"]:
                parts.append(f"{counts['full']} occupé(s)")
            if counts["bad"]:
                parts.append(f"{counts['bad']} invalide(s)")
            if self._removed_note:
                parts.append(self._removed_note)
            self.summary.setText(("  ·  " + " · ".join(parts)) if parts else "")
        finally:
            self.setUpdatesEnabled(True)


_RANK = {"ok": 0, "unknown": 1, "checking": 1, "": 1, "full": 2, "bad": 3}


def _title(account: Credentials) -> str:
    host = account.base_url.split("://", 1)[-1].split("/", 1)[0]
    return account.name or account.username or host


class AccountRow(QFrame):
    """One account line, updated in place (no rebuild, no flicker)."""

    rename_clicked = pyqtSignal(str)
    move_clicked = pyqtSignal(str, int)
    remove_clicked = pyqtSignal(str)

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("Tile")
        line = QHBoxLayout(self)
        line.setContentsMargins(14, 10, 10, 10)
        line.setSpacing(10)
        self.dot = _Dot(theme.SURFACE_3)
        line.addWidget(self.dot)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = label("", "SectionTitle")
        self.sub = label("", "Faint")
        texts.addWidget(self.title)
        texts.addWidget(self.sub)
        line.addLayout(texts, 1)
        self.cons = label("—", "TileValue")
        self.cons.setToolTip("Connexions actives / maximum")
        self.cons.setMinimumWidth(60)
        self.cons.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(self.cons)
        line.addSpacing(8)
        self.rename_button = button("✎", "Ghost", "Renommer")
        self.up_button = button("↑", "Ghost", "Monter (parmi les comptes du même état)")
        self.down_button = button("↓", "Ghost", "Descendre")
        self.remove_button = button("✕", "Ghost", "Retirer")
        self.rename_button.clicked.connect(lambda: self.rename_clicked.emit(self.key))
        self.up_button.clicked.connect(lambda: self.move_clicked.emit(self.key, -1))
        self.down_button.clicked.connect(lambda: self.move_clicked.emit(self.key, 1))
        self.remove_button.clicked.connect(lambda: self.remove_clicked.emit(self.key))
        for btn in (self.rename_button, self.up_button, self.down_button, self.remove_button):
            line.addWidget(btn)
        self._last: tuple | None = None

    def update_view(
        self,
        rank: int,
        account: Credentials,
        state: str,
        cons: str,
        detail: str,
        can_up: bool,
        can_down: bool,
    ) -> None:
        snapshot = (rank, account.name, account.username, state, cons, detail, can_up, can_down)
        if snapshot == self._last:
            return
        self._last = snapshot
        color = {"ok": theme.OK, "full": theme.WARN, "bad": theme.ERROR, "checking": theme.TEXT_FAINT}.get(
            state, theme.SURFACE_3,
        )
        self.dot.set_color(color)
        self.title.setText(f"{rank}. {_title(account)}")
        host = account.base_url.split("://", 1)[-1].split("/", 1)[0]
        sub = f"{account.portal_type.value.upper()} · {account.username or 'playlist'} · {host}"
        if state == "checking":
            sub += " · vérification…"
        elif detail:
            sub += f" · {detail}"
        self.sub.setText(sub)
        self.sub.setStyleSheet(f"color: {theme.ERROR};" if state == "bad" else "")
        show_cons = bool(cons) and state in ("ok", "full", "checking") and "unknown" not in cons.lower()
        self.cons.setText(cons.replace("/", " / ") if show_cons else "—")
        self.cons.setStyleSheet(
            f"color: {theme.WARN};" if state == "full" else (f"color: {theme.OK};" if state == "ok" else ""),
        )
        self.up_button.setEnabled(can_up)
        self.down_button.setEnabled(can_down)
