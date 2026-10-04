# -*- coding: utf-8 -*-
"""全屏 / 选区截图，并转为可供视觉模型使用的 data URL（支持多显示器）。"""
import base64

from PyQt6.QtCore import QBuffer, QByteArray, QRect, Qt, pyqtSignal, QPoint
from PyQt6.QtGui import (QColor, QGuiApplication, QImage, QPainter, QPen,
                         QPixmap)
from PyQt6.QtWidgets import QWidget


def grab_screen() -> QPixmap:
    """抓取整个虚拟桌面（含所有显示器），返回原始像素位图。"""
    screens = QGuiApplication.screens()
    if not screens:
        return QPixmap()
    vrect = QRect()
    for s in screens:
        vrect = vrect.united(s.geometry())
    dpr = max((s.devicePixelRatio() for s in screens), default=1.0)
    canvas = QPixmap(int(vrect.width() * dpr), int(vrect.height() * dpr))
    canvas.fill(QColor(0, 0, 0, 0))
    painter = QPainter(canvas)
    for s in screens:
        shot = s.grabWindow(0)
        g = s.geometry()
        target = QRect(int((g.x() - vrect.x()) * dpr), int((g.y() - vrect.y()) * dpr),
                       int(g.width() * dpr), int(g.height() * dpr))
        painter.drawPixmap(target, shot)
    painter.end()
    return canvas


def image_to_data_url(img: QImage, max_w: int = 1280) -> str:
    """QImage -> PNG data URL（QImage 可跨线程读取，编码可放后台线程）。"""
    if img is None or img.isNull():
        return ""
    if img.width() > max_w:
        img = img.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    b64 = base64.b64encode(bytes(ba)).decode("ascii")
    return f"data:image/png;base64,{b64}"


def pixmap_to_data_url(pix: QPixmap, max_w: int = 1280) -> str:
    if pix.isNull():
        return ""
    return image_to_data_url(pix.toImage(), max_w)


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
        # 先抓取全屏，避免覆盖层挡住（含所有显示器，物理像素）
        self._full = grab_screen()
        self._dpr = max((s.devicePixelRatio() for s in QGuiApplication.screens()),
                        default=1.0)
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
            # 选区是逻辑坐标、截图是物理像素：按 DPI 换算后裁剪
            phys = QRect(int(sel.x() * self._dpr), int(sel.y() * self._dpr),
                         int(sel.width() * self._dpr), int(sel.height() * self._dpr))
            shot = self._full.copy(phys)
            shot.setDevicePixelRatio(self._full.devicePixelRatio() or self._dpr)
            self.captured.emit(shot)
        self.close()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
