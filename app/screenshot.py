# -*- coding: utf-8 -*-
"""全屏 / 选区截图，并转为可供视觉模型使用的 data URL。"""
import base64
from io import BytesIO

from PyQt6.QtCore import QBuffer, QByteArray, QRect, Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QGuiApplication, QPainter, QColor, QPen, QPixmap
from PyQt6.QtWidgets import QWidget


def grab_screen() -> QPixmap:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return QPixmap()
    return screen.grabWindow(0)


def pixmap_to_data_url(pix: QPixmap, max_w: int = 1280) -> str:
    if pix.isNull():
        return ""
    if pix.width() > max_w:
        pix = pix.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    buf.close()
    b64 = base64.b64encode(bytes(ba)).decode("ascii")
    return f"data:image/png;base64,{b64}"


class RegionSelector(QWidget):
    """覆盖全部屏幕，让主人拖拽选择截图区域。"""

    captured = pyqtSignal(QPixmap)
    cancelled = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(0.35)
        self.setCursor(Qt.CursorShape.CrossCursor)
        rects = [s.geometry() for s in QGuiApplication.screens()]
        left = min(r.left() for r in rects)
        top = min(r.top() for r in rects)
        right = max(r.right() for r in rects)
        bottom = max(r.bottom() for r in rects)
        self._virtual = QRect(left, top, right - left, bottom - top)
        # 先抓取全屏，避免覆盖层挡住
        self._full = grab_screen()
        self.setGeometry(self._virtual)
        self._origin = None
        self._current = None
        self._dragging = False

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 60))
        if self._origin and self._current:
            sel = QRect(self._origin, self._current).normalized()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(sel, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(140, 200, 255), 2))
            p.drawRect(sel)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._dragging:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        if self._origin and self._current:
            sel = QRect(self._origin, self._current).normalized()
        else:
            sel = QRect()
        if sel.width() < 8 or sel.height() < 8:
            # 视为点击 -> 全屏
            self.captured.emit(self._full)
        else:
            gx = sel.x() + self._virtual.x()
            gy = sel.y() + self._virtual.y()
            self.captured.emit(self._full.copy(sel))
        self.close()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
