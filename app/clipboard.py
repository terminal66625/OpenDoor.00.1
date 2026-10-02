# -*- coding: utf-8 -*-
"""剪贴板助手：复制文字后一键唤起大肥鱼解读 / 润色 / 查错 / 翻译。"""
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget


class ClipboardWatcher(QWidget):
    """轮询剪贴板；发现新的文本就通知主程序。"""
    copied = pyqtSignal(str)

    def __init__(self, enabled_getter) -> None:
        super().__init__(None, Qt.WindowType.Tool)
        self.hide()
        self._enabled = enabled_getter
        self._last = ""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(2000)          # 2 秒轮询一次，降低后台唤醒
        try:
            self._last = QApplication.clipboard().text()
        except Exception:
            pass

    def _poll(self) -> None:
        if not self._enabled():
            return
        try:
            text = QApplication.clipboard().text()
        except Exception:
            return
        if text and text != self._last and 4 <= len(text) <= 3000:
            self._last = text
            self.copied.emit(text)
        else:
            self._last = text


class ClipboardBar(QWidget):
    """贴在桌宠旁边的小浮动条。"""
    action = pyqtSignal(str, str)      # 动作, 文本
    closed = pyqtSignal()

    ACTIONS = [("解读", "解读"), ("润色", "润色"), ("查错", "查错"), ("翻译", "翻译")]

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.text = ""
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.dismiss)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(6)
        self.card = QWidget()
        self.card.setStyleSheet("background:rgba(240,247,255,0.97);"
                                "border:1px solid #bcd8f5;border-radius:14px;")
        inner = QHBoxLayout(self.card)
        inner.setContentsMargins(10, 6, 10, 6)
        inner.setSpacing(6)
        tip = QLabel("剪贴板：")
        tip.setStyleSheet("color:#3a6ea8;font-family:'Microsoft YaHei';")
        inner.addWidget(tip)
        for label, key in self.ACTIONS:
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(
                "QPushButton{border:none;border-radius:9px;padding:4px 10px;"
                "background:#9ccbf3;color:white;font-family:'Microsoft YaHei';}"
                "QPushButton:hover{background:#7ab5ea;}")
            b.clicked.connect(lambda _, k=key: self._fire(k))
            inner.addWidget(b)
        close = QPushButton("✕")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet("QPushButton{border:none;color:#5a83b3;background:transparent;}")
        close.clicked.connect(self.dismiss)
        inner.addWidget(close)
        lay.addWidget(self.card)

    def _fire(self, key: str) -> None:
        self.action.emit(key, self.text)
        self.dismiss()

    def dismiss(self) -> None:
        self.hide()
        self.closed.emit()

    def popup_near(self, x: int, y: int, text: str) -> None:
        self.text = text
        self.adjustSize()
        screen = QApplication.primaryScreen().availableGeometry()
        px = max(10, min(x - self.width() // 2, screen.right() - self.width() - 10))
        py = y - self.height() - 8
        if py < 10:
            py = y + 8
        self.move(px, py)
        self.show()
        self.raise_()
        self._auto_hide.start(12000)      # 12 秒无操作自动收起
