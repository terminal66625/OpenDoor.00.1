# -*- coding: utf-8 -*-
"""半圆形悬浮快捷面板：右键桌宠呼出，一步直达高频操作。"""
from __future__ import annotations

import math
from typing import List, Tuple

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import (QApplication, QGraphicsOpacityEffect, QPushButton,
                             QWidget)

BTN = 58
RADIUS = 108

DEFAULT_ITEMS: List[Tuple[str, str]] = [
    ("vision", "📷\n识图"),
    ("clip", "📋\n剪贴板"),
    ("clear", "🧹\n清空"),
    ("mode", "🎯\n模式"),
    ("hide", "👻\n隐藏"),
    ("feed", "🍚\n投喂"),
    ("store", "🪙\n囤token"),
    ("more", "⋯\n更多"),
]

STYLE = """
QPushButton{border:1px solid #bcd8f5;border-radius:29px;
 background:rgba(245,250,255,0.97);color:#2c5c92;font-size:11px;
 font-family:'Microsoft YaHei';}
QPushButton:hover{background:#d6e9ff;border:1px solid #7ab5ea;}
QPushButton:pressed{background:#bcdcff;}
"""


class RadialMenu(QWidget):
    action = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._buttons: List[QPushButton] = []
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._build(DEFAULT_ITEMS)

    def _build(self, items: List[Tuple[str, str]]) -> None:
        tips = {"vision": "选区识图（截屏给大肥鱼看）",
                "clip": "解读剪贴板内容",
                "clear": "清空当前会话",
                "mode": "切换 聊天 / 专注 模式",
                "hide": "隐藏并退出（可从桌面快捷方式重新启动）",
                "feed": "投喂大白饭",
                "store": "囤 token",
                "more": "更多设置"}
        for b in self._buttons:
            b.deleteLater()
        self._buttons.clear()
        for key, label in items:
            b = QPushButton(label, self)
            b.setFixedSize(BTN, BTN)
            b.setStyleSheet(STYLE)
            b.setToolTip(tips.get(key, ""))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 不抢焦点，避免面板误收起
            b.clicked.connect(lambda _, k=key: self._fire(k))
            self._buttons.append(b)
        self._items = items

    def _fire(self, key: str) -> None:
        self.hide()
        self.action.emit(key)

    def show_at(self, x: int, y: int) -> None:
        n = len(self._items)
        pad = 10
        # 保证半圆两端（sin=0）与顶端（sin=1）的按钮都完整落在面板内
        cx = RADIUS + BTN // 2 + pad
        cy = pad + RADIUS + BTN // 2
        w = RADIUS * 2 + BTN + pad * 2
        h = cy + BTN // 2 + pad
        self.resize(w, h)
        for i, b in enumerate(self._buttons):
            ang = math.pi * (1 - i / max(1, n - 1))     # 180° -> 0°，上半圆
            bx = cx + RADIUS * math.cos(ang) - BTN // 2
            by = cy - RADIUS * math.sin(ang) - BTN // 2
            b.move(int(round(bx)), int(round(by)))
        scr = QApplication.primaryScreen().availableGeometry()
        px = max(scr.left() + 4, min(x - w // 2, scr.right() - w - 4))
        py = y - h + 6
        if py < scr.top() + 4:
            py = y + 4
        self.move(px, py)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._hide_timer.start(8000)
        # 弹出淡入 + 轻微上浮
        try:
            eff = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(180)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: self.setGraphicsEffect(None))
            anim.start()
            self._pop_anim = anim
        except Exception:
            try:
                self.setGraphicsEffect(None)
            except Exception:
                pass

    def focusOutEvent(self, e) -> None:
        # 点到子按钮时焦点会移到按钮、也会触发 focusOut；
        # 因此只有鼠标确实在面板之外时才收起，否则按钮会点不动。
        try:
            from PyQt6.QtGui import QCursor
            if not self.geometry().contains(QCursor.pos()):
                self.hide()
        except Exception:
            pass

    def mousePressEvent(self, e) -> None:
        self.hide()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.hide()

    def paintEvent(self, e) -> None:
        # 淡淡的光晕底，突出半圆面板
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() - 12
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(150, 195, 240, 26))
        p.drawEllipse(cx - RADIUS - BTN // 2, cy - RADIUS - BTN // 2,
                      (RADIUS + BTN // 2) * 2, (RADIUS + BTN // 2) * 2)
        # 底部中间的傲娇小气泡（短文本，避免挡住两端按钮）
        text = "哼！"
        p.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text) + 20
        th = 24
        bx = cx - tw // 2
        by = self.height() - th - 3
        path = QPainterPath()
        path.addRoundedRect(bx, by, tw, th, 13, 13)
        p.fillPath(path, QColor(255, 255, 255, 244))
        p.setPen(QColor(198, 220, 245))
        p.drawPath(path)
        p.setPen(QColor(44, 92, 146))
        p.drawText(bx, by, tw, th, int(Qt.AlignmentFlag.AlignCenter), text)
        p.end()
