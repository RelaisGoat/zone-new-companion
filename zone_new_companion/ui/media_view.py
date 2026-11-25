"""Channel / movie list: model, logo loader and painter (list + grid modes)."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from zone_new_companion.models import MediaItem
from zone_new_companion.ui import theme

MEDIA_ROLE = Qt.ItemDataRole.UserRole + 1
STATUS_ROLE = Qt.ItemDataRole.UserRole + 2
NOW_ROLE = Qt.ItemDataRole.UserRole + 3
LOGO_ROLE = Qt.ItemDataRole.UserRole + 4

_LOGO_KEYS = ("stream_icon", "cover", "logo", "tvg_logo", "tvg-logo", "screenshot_uri", "movie_image", "cover_big")


def logo_url_for(item: MediaItem) -> str:
    for key in _LOGO_KEYS:
        value = item.metadata.get(key) if isinstance(item.metadata, dict) else None
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value.strip()
    return ""


class LogoLoader(QObject):
    """Download channel logos once, keep them in memory and on disk."""

    loaded = pyqtSignal(str)
    MAX_PARALLEL = 8
    MAX_SIDE = 160

    def __init__(self, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        cache = QNetworkDiskCache(self)
        cache.setCacheDirectory(str(cache_dir))
        cache.setMaximumCacheSize(200 * 1024 * 1024)
        self._manager.setCache(cache)
        self._pixmaps: dict[str, QPixmap] = {}
        self._failed: set[str] = set()
        self._queue: list[str] = []
        self._in_flight: set[str] = set()

    def get(self, url: str) -> QPixmap | None:
        if not url or url in self._failed:
            return None
        pixmap = self._pixmaps.get(url)
        if pixmap is not None:
            return pixmap
        if url not in self._in_flight:
            if url in self._queue:
                self._queue.remove(url)
            self._queue.append(url)  # last requested = most recently visible
            self._pump()
        return None

    def _pump(self) -> None:
        while self._queue and len(self._in_flight) < self.MAX_PARALLEL:
            url = self._queue.pop()
            self._in_flight.add(url)
            request = QNetworkRequest(QUrl(url))
            request.setAttribute(
                QNetworkRequest.Attribute.CacheLoadControlAttribute,
                QNetworkRequest.CacheLoadControl.PreferCache,
            )
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
            )
            request.setTransferTimeout(10000)
            reply = self._manager.get(request)
            reply.finished.connect(lambda r=reply, u=url: self._on_finished(r, u))
        if len(self._queue) > 400:  # user scrolled far away; forget the oldest
            del self._queue[: len(self._queue) - 400]

    def _on_finished(self, reply: QNetworkReply, url: str) -> None:
        self._in_flight.discard(url)
        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NetworkError.NoError and pixmap.loadFromData(bytes(reply.readAll())):
            if pixmap.width() > self.MAX_SIDE or pixmap.height() > self.MAX_SIDE:
                pixmap = pixmap.scaled(
                    self.MAX_SIDE,
                    self.MAX_SIDE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._pixmaps[url] = pixmap
            self.loaded.emit(url)
        else:
            self._failed.add(url)
        reply.deleteLater()
        self._pump()


class MediaListModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[MediaItem] = []
        self._logos: list[str] = []
        self._status: dict[str, str] = {}
        self._now: dict[str, str] = {}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return item.name
        if role == MEDIA_ROLE:
            return item
        if role == STATUS_ROLE:
            return self._status.get(item.id, "")
        if role == NOW_ROLE:
            return self._now.get(item.id, "")
        if role == LOGO_ROLE:
            return self._logos[index.row()]
        if role == Qt.ItemDataRole.ToolTipRole:
            status = self._status.get(item.id, "")
            return item.name + (f"\n{status}" if status else "")
        return None

    def set_items(self, items: list[MediaItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._logos = [logo_url_for(item) for item in self._items]
        self.endResetModel()

    def set_annotations(self, status: dict[str, str], now: dict[str, str]) -> None:
        if status == self._status and now == self._now:
            return
        self._status = dict(status)
        self._now = dict(now)
        if self._items:
            self.dataChanged.emit(self.index(0), self.index(len(self._items) - 1), [STATUS_ROLE, NOW_ROLE])

    def refresh_logo(self, url: str) -> None:
        for row, logo in enumerate(self._logos):
            if logo == url:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [LOGO_ROLE])

    def has_logos(self) -> bool:
        return any(self._logos)


class MediaFilterModel(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterRole(Qt.ItemDataRole.DisplayRole)


class MediaDelegate(QStyledItemDelegate):
    """Paints rows (list mode) or tiles (grid mode)."""

    play_clicked = pyqtSignal(QModelIndex)

    LIST_HEIGHT = 68
    GRID_SIZE = QSize(164, 146)

    def __init__(self, loader: LogoLoader, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loader = loader
        self.grid = False
        self._hover_row = -1

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        if self.grid:
            return self.GRID_SIZE
        return QSize(option.rect.width(), self.LIST_HEIGHT)

    # -------------------------------------------------------------- helpers
    def _play_rect(self, rect: QRect) -> QRect:
        if self.grid:
            return QRect(rect.right() - 44, rect.top() + 10, 34, 34)
        return QRect(rect.right() - 50, rect.center().y() - 17, 34, 34)

    @staticmethod
    def _rounded(painter: QPainter, rect: QRectF, radius: float, color: QColor) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, color)

    def _draw_logo(self, painter: QPainter, rect: QRect, index: QModelIndex, name: str) -> None:
        self._rounded(painter, QRectF(rect), 10, QColor(theme.SURFACE_3))
        pixmap = self._loader.get(index.data(LOGO_ROLE) or "")
        if pixmap is not None and not pixmap.isNull():
            inner = rect.adjusted(6, 6, -6, -6)
            scaled = pixmap.scaled(
                inner.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
            x = inner.x() + (inner.width() - scaled.width()) // 2
            y = inner.y() + (inner.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            return
        words = [w for w in name.replace("|", " ").replace(":", " ").split() if w[:1].isalnum()]
        initials = "".join(w[0] for w in words[:2]).upper() or "?"
        color = QColor(theme.avatar_color(name))
        painter.setPen(color)
        font = QFont(painter.font())
        font.setPointSizeF(13 if self.grid else 11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initials)

    def _draw_pill(self, painter: QPainter, right: int, center_y: int, status: str) -> int:
        color_hex = theme.status_color(status)
        if not color_hex:
            return right
        label = status.split("(")[0].strip() or status
        detail = status[len(label):].strip(" ()")
        text = f"{label} · {detail}" if detail else label
        font = QFont(painter.font())
        font.setPointSizeF(8.5)
        font.setBold(True)
        painter.setFont(font)
        width = QFontMetrics(font).horizontalAdvance(text) + 20
        rect = QRectF(right - width, center_y - 11, width, 22)
        color = QColor(color_hex)
        bg = QColor(color)
        bg.setAlpha(38)
        self._rounded(painter, rect, 11, bg)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        return int(rect.left()) - 10

    def _draw_play(self, painter: QPainter, rect: QRect, hovered: bool, expandable: bool) -> None:
        if not hovered:
            return
        self._rounded(painter, QRectF(rect), rect.width() / 2, QColor(theme.ACCENT))
        painter.setPen(QPen(QColor("white")))
        font = QFont(painter.font())
        font.setPointSizeF(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.adjusted(2 if not expandable else 0, 0, 0, -1), Qt.AlignmentFlag.AlignCenter, "›" if expandable else "▶")

    # ---------------------------------------------------------------- paint
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        media: MediaItem = index.data(MEDIA_ROLE)
        name = media.name if media else ""
        status = index.data(STATUS_ROLE) or ""
        now = index.data(NOW_ROLE) or ""
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        expandable = bool(media and media.item_type in {"series", "season"})

        rect = option.rect.adjusted(4, 3, -4, -3)
        if selected:
            self._rounded(painter, QRectF(rect), 12, QColor(theme.SURFACE_3))
        elif hovered:
            self._rounded(painter, QRectF(rect), 12, QColor(theme.SURFACE_2))
        elif self.grid:
            self._rounded(painter, QRectF(rect), 12, QColor(theme.SURFACE))

        base_font = QFont(option.font)
        if self.grid:
            logo_rect = QRect(rect.center().x() - 46, rect.top() + 12, 92, 68)
            self._draw_logo(painter, logo_rect, index, name)
            text_rect = QRect(rect.left() + 10, logo_rect.bottom() + 10, rect.width() - 20, 40)
            font = QFont(base_font)
            font.setPointSizeF(9.5)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                QFontMetrics(font).elidedText(name, Qt.TextElideMode.ElideRight, text_rect.width() * 2 - 10),
            )
            color_hex = theme.status_color(status)
            if color_hex:
                self._rounded(painter, QRectF(rect.left() + 12, rect.top() + 12, 10, 10), 5, QColor(color_hex))
            self._draw_play(painter, self._play_rect(rect), hovered, expandable)
            painter.restore()
            return

        logo_rect = QRect(rect.left() + 10, rect.top() + 7, 64, rect.height() - 14)
        self._draw_logo(painter, logo_rect, index, name)
        right = rect.right() - 12
        if hovered:
            self._draw_play(painter, self._play_rect(rect), hovered, expandable)
            right = self._play_rect(rect).left() - 12
        right = self._draw_pill(painter, right, rect.center().y(), status)

        text_left = logo_rect.right() + 14
        text_width = max(40, right - text_left)
        title_font = QFont(base_font)
        title_font.setPointSizeF(11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(theme.TEXT))
        title_metrics = QFontMetrics(title_font)
        if now:
            title_rect = QRect(text_left, rect.top() + 12, text_width, title_metrics.height())
        else:
            title_rect = QRect(text_left, rect.center().y() - title_metrics.height() // 2, text_width, title_metrics.height())
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(name, Qt.TextElideMode.ElideRight, text_width),
        )
        if now:
            sub_font = QFont(base_font)
            sub_font.setPointSizeF(9)
            painter.setFont(sub_font)
            painter.setPen(QColor(theme.TEXT_MUTED))
            sub_metrics = QFontMetrics(sub_font)
            sub_rect = QRect(text_left, title_rect.bottom() + 4, text_width, sub_metrics.height())
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                sub_metrics.elidedText(f"En ce moment · {now}", Qt.TextElideMode.ElideRight, text_width),
            )
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            rect = option.rect.adjusted(4, 3, -4, -3)
            if self._play_rect(rect).contains(event.position().toPoint()):
                self.play_clicked.emit(index)
                return True
        return super().editorEvent(event, model, option, index)


class MediaListView(QListView):
    """QListView preconfigured for the delegate, with list/grid switch."""

    def __init__(self, delegate: MediaDelegate, parent=None) -> None:
        super().__init__(parent)
        self._delegate = delegate
        self.setItemDelegate(delegate)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.set_grid(False)

    def set_grid(self, grid: bool) -> None:
        self._delegate.grid = grid
        if grid:
            self.setViewMode(QListView.ViewMode.IconMode)
            self.setResizeMode(QListView.ResizeMode.Adjust)
            self.setMovement(QListView.Movement.Static)
            self.setGridSize(MediaDelegate.GRID_SIZE + QSize(6, 6))
            self.setSpacing(0)
            self.setWrapping(True)
        else:
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setGridSize(QSize())
            self.setWrapping(False)
            self.setSpacing(0)
        self.doItemsLayout()
        self.viewport().update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.viewport().update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        self.viewport().update()


__all__ = [
    "LOGO_ROLE",
    "MEDIA_ROLE",
    "LogoLoader",
    "MediaDelegate",
    "MediaFilterModel",
    "MediaListModel",
    "MediaListView",
    "QPoint",
]
