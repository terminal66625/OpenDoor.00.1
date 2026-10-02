# -*- coding: utf-8 -*-
"""养成面板：好感等级、活力、投喂、囤 token、成就。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar,
                             QPushButton, QTextBrowser, QVBoxLayout)

from . import ui_theme
from .affinity import LEVELS


class GrowthDialog(QDialog):
    feed_requested = pyqtSignal()
    store_requested = pyqtSignal()

    def __init__(self, affinity, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint)
        self.aff = affinity
        self.setWindowTitle("大肥鱼 · 好感与养成")
        self.setStyleSheet(ui_theme.DIALOG_QSS)
        self.resize(470, 440)

        v = QVBoxLayout(self)
        self.title = QLabel(ui_theme.header("好感与养成",
                                            "哼，本鱼才不是想让你多陪陪本鱼呢！"))
        self.title.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.title)

        v.addWidget(QLabel("好感进度："))
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        v.addWidget(self.bar)

        self.body = QTextBrowser()
        v.addWidget(self.body, 1)

        row = QHBoxLayout()
        self.btn_feed = QPushButton("🍚 投喂大白饭")
        self.btn_feed.clicked.connect(self.feed_requested.emit)
        self.btn_store = QPushButton("🪙 囤 token")
        self.btn_store.clicked.connect(self.store_requested.emit)
        row.addWidget(self.btn_feed)
        row.addWidget(self.btn_store)
        v.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        a = self.aff
        idx, pts, nxt = a.progress()
        if idx + 1 < len(LEVELS):
            lo = LEVELS[idx][0]
            pct = int(100 * (pts - lo) / max(1, nxt - lo))
        else:
            pct = 100
        self.bar.setValue(max(0, min(100, pct)))
        self.bar.setFormat(f"{a.level_name()}　{pts} 分")
        self.body.setHtml("<br>".join(a.summary_lines()))
        self.btn_feed.setText("🍚 投喂（不限次数）")
        self.btn_store.setText(f"🪙 囤 token（可囤 {a.pending_tokens()}）")
