"""Small reusable building blocks."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from zone_new_companion.ui import theme


def label(text: str, object_name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


def card(padding: int = 20, spacing: int = 14) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(spacing)
    return frame, layout


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


def button(text: str, object_name: str = "", tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    if object_name:
        widget.setObjectName(object_name)
    if tooltip:
        widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class SegmentBar(QFrame):
    """iOS-like segmented control."""

    changed = pyqtSignal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, text in enumerate(labels):
            btn = button(text, "Segment")
            btn.setCheckable(True)
            self._group.addButton(btn, index)
            layout.addWidget(btn)
        self._group.button(0).setChecked(True)
        self._group.idClicked.connect(self.changed.emit)

    def set_current(self, index: int) -> None:
        btn = self._group.button(index)
        if btn is not None:
            btn.setChecked(True)
            self.changed.emit(index)

    def current(self) -> int:
        return self._group.checkedId()


class Tile(QFrame):
    """Label + big value, used for account information."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Tile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        self.title = label(title.upper(), "TileLabel")
        self.value = label("—", "TileValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, text: str, color: str | None = None) -> None:
        self.value.setText(text or "—")
        self.value.setStyleSheet(f"color: {color};" if color else "")


class Toast(QLabel):
    """Bottom-centred transient message."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMaximumWidth(560)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, kind: str = "info", timeout_ms: int = 2800) -> None:
        accent = {"error": theme.ERROR, "ok": theme.OK, "warn": theme.WARN}.get(kind, theme.ACCENT)
        self.setStyleSheet(
            f"background: {theme.SURFACE_3}; color: {theme.TEXT}; padding: 11px 18px;"
            f"border-radius: 10px; border: 1px solid {theme.BORDER}; border-left: 3px solid {accent};"
            "font-weight: 600;",
        )
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 28)
        self.raise_()
        self.show()
        self._timer.start(timeout_ms)


class EmptyState(QWidget):
    """Centered message for empty lists."""

    action_clicked = pyqtSignal()

    def __init__(self, title: str, subtitle: str = "", action: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self.title = label(title, "SectionTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = label(subtitle, "Muted", wrap=True)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        self.action = None
        if action:
            row = QHBoxLayout()
            row.addStretch(1)
            self.action = button(action, "Primary")
            self.action.clicked.connect(self.action_clicked.emit)
            row.addWidget(self.action)
            row.addStretch(1)
            layout.addSpacing(10)
            layout.addLayout(row)
        layout.addStretch(2)

    def set_text(self, title: str, subtitle: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
