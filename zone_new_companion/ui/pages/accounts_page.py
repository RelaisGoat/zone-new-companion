"""Secours page: backup accounts, pasted in bulk, with live status dots."""

from __future__ import annotations

import re
from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
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
        for account in self._accounts:
            key = account_key(account)
            state, cons, detail, checked = self._status.get(key, ("", "", "", ""))
            self._status[key] = ("checking", cons, detail, checked)
        self._render()
        self.check_requested.emit(list(self._accounts))

    def set_status(self, account: Credentials, info: dict[str, str] | None, error: str = "") -> None:
        key = account_key(account)
        now = datetime.now().strftime("%H:%M")
        if info is None:
            self._status[key] = ("bad", "", error or "injoignable", now)
        elif info.get("Type") == "M3U Playlist":
            self._status[key] = ("unknown", "", "playlist M3U (vérifiée au moment de la bascule)", now)
        else:
            status = str(info.get("Status", "")).lower()
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
                    "expired": "abonnement expiré",
                    "banned": "compte banni",
                    "disabled": "compte désactivé",
                    "unknown": "identifiants refusés",
                    "": "identifiants refusés",
                }.get(status, status)
            self._status[key] = (state, cons, detail, now)
        self.last_check.setText(f"Vérifié à {now}")
        self._render()

    def checking_done(self) -> None:
        self._checking = False
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("↻  Tout vérifier")

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
            added.append(account)
        self.bulk.clear()
        self._render()
        self.accounts_changed.emit(list(self._accounts))
        if added:
            for account in added:
                self._status[account_key(account)] = ("checking", "", "", "")
            self._render()
            self.check_requested.emit(added)

    def _move(self, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= target < len(self._accounts):
            self._accounts[index], self._accounts[target] = self._accounts[target], self._accounts[index]
            self._render()
            self.accounts_changed.emit(list(self._accounts))

    def _remove(self, index: int) -> None:
        if 0 <= index < len(self._accounts):
            self._status.pop(account_key(self._accounts[index]), None)
            del self._accounts[index]
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

    def _rename(self, index: int) -> None:
        if not 0 <= index < len(self._accounts):
            return
        account = self._accounts[index]
        name, ok = QInputDialog.getText(self, "Renommer", "Nom du compte :", text=account.name)
        if ok:
            account.name = name.strip()
            self._render()
            self.accounts_changed.emit(list(self._accounts))

    # ------------------------------------------------------------ rendering
    def _render(self) -> None:
        while self.rows.count():
            child = self.rows.takeAt(0).widget()
            if child is not None:
                child.deleteLater()
        counts = {"ok": 0, "full": 0, "bad": 0}
        for index, account in enumerate(self._accounts):
            state, cons, detail, checked = self._status.get(account_key(account), ("", "", "", ""))
            if state in counts:
                counts[state] += 1
            self.rows.addWidget(self._row(index, account, state, cons, detail))
        self.empty.setVisible(not self._accounts)
        self.clear_button.setEnabled(bool(self._accounts))
        parts = []
        if counts["ok"]:
            parts.append(f"{counts['ok']} libre(s)")
        if counts["full"]:
            parts.append(f"{counts['full']} occupé(s)")
        if counts["bad"]:
            parts.append(f"{counts['bad']} invalide(s)")
        self.summary.setText(("  ·  " + " · ".join(parts)) if parts else "")

    def _row(self, index: int, account: Credentials, state: str, cons: str, detail: str) -> QFrame:
        row = QFrame()
        row.setObjectName("Tile")
        line = QHBoxLayout(row)
        line.setContentsMargins(14, 10, 10, 10)
        line.setSpacing(10)
        color = {
            "ok": theme.OK,
            "full": theme.WARN,
            "bad": theme.ERROR,
            "checking": theme.TEXT_FAINT,
        }.get(state, theme.SURFACE_3)
        line.addWidget(_Dot(color))
        texts = QVBoxLayout()
        texts.setSpacing(2)
        host = account.base_url.split("://", 1)[-1].split("/", 1)[0]
        title = account.name or account.username or host
        texts.addWidget(label(f"{index + 1}. {title}", "SectionTitle"))
        sub = f"{account.portal_type.value.upper()} · {account.username or 'playlist'} · {host}"
        if state == "checking":
            sub += " · vérification…"
        elif detail:
            sub += f" · {detail}"
        sub_label = label(sub, "Faint")
        if state == "bad":
            sub_label.setStyleSheet(f"color: {theme.ERROR};")
        texts.addWidget(sub_label)
        line.addLayout(texts, 1)

        show_cons = cons and state in ("ok", "full", "checking") and "unknown" not in cons.lower()
        cons_label = label(cons.replace("/", " / ") if show_cons else "—", "TileValue")
        cons_label.setToolTip("Connexions actives / maximum en ce moment")
        if state == "full":
            cons_label.setStyleSheet(f"color: {theme.WARN};")
        elif state == "ok":
            cons_label.setStyleSheet(f"color: {theme.OK};")
        cons_label.setMinimumWidth(60)
        cons_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        line.addWidget(cons_label)
        line.addSpacing(8)
        for text, tip, handler in (
            ("✎", "Renommer", lambda _=False, i=index: self._rename(i)),
            ("↑", "Monter (priorité)", lambda _=False, i=index: self._move(i, -1)),
            ("↓", "Descendre", lambda _=False, i=index: self._move(i, 1)),
            ("✕", "Retirer", lambda _=False, i=index: self._remove(i)),
        ):
            btn = button(text, "Ghost", tip)
            btn.clicked.connect(handler)
            line.addWidget(btn)
        return row
