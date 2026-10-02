# -*- coding: utf-8 -*-
"""动作叠加层：在桌宠旁边播放「动作行为参考」里的动作（含文字表现）。"""
from __future__ import annotations

import os
from typing import List, Optional

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap, QPainterPath
from PyQt6.QtWidgets import QApplication, QWidget

FPS = 10.0


class ActionOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.frames: List[QPixmap] = []
        self.idx = 0
        self.caption = ""
        self.cycles = 0
        self.max_cycles = 1
        self.background = False
        self._cache = {}          # (目录, 目标高度) -> 帧列表，避免重复读盘
        self._cache_order = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.hide()

    def play(self, item: dict, x: int, y: int, target_h: int,
             caption: Optional[str] = None, cycles: int = 2) -> None:
        d = item.get("dir", "")
        if not d or not os.path.isdir(d):
            return
        key = (d, target_h)
        frames = self._cache.get(key)
        if frames is None:
            files = [os.path.join(d, f) for f in sorted(os.listdir(d))
                     if f.startswith("f") and f.endswith(".png")]
            if not files:
                return
            pm0 = QPixmap(files[0])
            if pm0.isNull():
                return
            kw = max(1, int(pm0.width() * target_h / max(1, pm0.height())))
            kh = max(1, target_h)
            frames = []
            for p in files:
                pm = QPixmap(p)
                if not pm.isNull():
                    frames.append(pm.scaled(kw, kh, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
            if not frames:
                return
            self._cache[key] = frames
            self._cache_order.append(key)
            while len(self._cache_order) > 3:      # 只留最近 3 个，控制内存
                old = self._cache_order.pop(0)
                self._cache.pop(old, None)
        self.frames = frames
        self.idx = 0
        self.cycles = 0
        self.max_cycles = max(1, cycles)
        self.caption = (caption or "").strip()
        self.background = bool(item.get("background"))
        self._resize_to_fit()

        scr = QApplication.primaryScreen().availableGeometry()
        px = max(scr.left() + 6, min(x - self.width() // 2, scr.right() - self.width() - 6))
        py = y - self.height() - 8
        if py < scr.top() + 6:
            py = y + 8
        if py + self.height() > scr.bottom() - 6:
            py = scr.bottom() - self.height() - 6
        self.move(px, py)
        self.show()
        self.raise_()
        self.timer.start(int(1000 / FPS))

    def _resize_to_fit(self) -> None:
        fw = max((f.width() for f in self.frames), default=120)
        fh = max((f.height() for f in self.frames), default=120)
        cap_h = 0
        if self.caption:
            cap_h = 34
        self.resize(fw + 12, fh + cap_h + 8)

    def _tick(self) -> None:
        if not self.frames:
            self.timer.stop(); self.hide(); return
        self.idx += 1
        if self.idx >= len(self.frames):
            self.idx = 0
            self.cycles += 1
            if self.cycles >= self.max_cycles:
                self.timer.stop()
                self.hide()
                return
        self.update()

    def paintEvent(self, e) -> None:
        if not self.frames:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.background:                  # 抠图失败：套一张干净卡片，降低违和感
            card = QPainterPath()
            card.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, 14, 14)
            p.fillPath(card, QColor(255, 255, 255, 242))
            p.setPen(QColor(205, 224, 246))
            p.drawPath(card)
        pm = self.frames[self.idx % len(self.frames)]
        px = max(0, (self.width() - pm.width()) // 2)
        py = max(0, (self.height() - pm.height()) // 2 - (10 if self.caption else 0))
        p.drawPixmap(px, py, pm)
        if self.caption:
            font = QFont("Microsoft YaHei", 10, QFont.Weight.Bold)
            p.setFont(font)
            fm = p.fontMetrics()
            tw = min(self.width() - 16, fm.horizontalAdvance(self.caption) + 18)
            th = 26
            bx = (self.width() - tw) // 2
            by = self.height() - th - 4
            path = QPainterPath()
            path.addRoundedRect(bx, by, tw, th, 12, 12)
            p.fillPath(path, QColor(255, 250, 235, 240))
            p.setPen(QColor(226, 170, 96))
            p.drawPath(path)
            p.setPen(QColor(120, 78, 20))
            p.drawText(QRect(bx, by, tw, th), int(Qt.AlignmentFlag.AlignCenter), self.caption)
        p.end()
