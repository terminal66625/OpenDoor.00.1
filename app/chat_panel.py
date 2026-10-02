# -*- coding: utf-8 -*-
"""对话气泡面板：微信风格、左右气泡、流式打字机、表情包、展开/收起。"""
import os
from typing import Optional

from PyQt6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QSize, QTimer,
                          QPoint, pyqtSignal)
from PyQt6.QtGui import QPixmap, QMovie, QFont, QColor, QAction, QGuiApplication
from PyQt6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
                             QDialog, QMenu)

from . import ui_theme

COLLAPSED_H = 200
EXPANDED_H = 560
PANEL_W = 400

AI_BUBBLE = "#dcecff"
USER_BUBBLE = "#c8f0c8"

# 输入智能补全：常用指令（按 Tab 快速填充）
COMPLETION_PHRASES = [
    "帮我看看屏幕", "解释这段代码", "这段代码有bug吗", "帮我润色一下",
    "翻译成英文", "翻译成中文", "总结一下这段文字", "帮我写个函数",
    "囤token", "投喂大白饭", "今天吃什么", "本鱼在吗",
    "讲个笑话", "主人夸夸本鱼", "本鱼有点无聊",
]


class StickerViewer(QDialog):
    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("background:rgba(255,255,255,0.96);border-radius:12px;padding:8px;")
        lay.addWidget(self.label)
        self._movie = None
        if path.lower().endswith(".gif"):
            self._movie = QMovie(path)
            self._movie.setScaledSize(_fit_size(path, 460))
            self.label.setMovie(self._movie)
            self._movie.start()
        else:
            pm = QPixmap(path)
            if pm.width() > 560 or pm.height() > 560:
                pm = pm.scaled(560, 560, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            self.label.setPixmap(pm)
        self.adjustSize()
        self.move(QGuiApplication.primaryScreen().availableGeometry().center()
                  - self.rect().center())

    def mousePressEvent(self, e) -> None:
        self.close()


DEFAULT_THEME = {
    "ai_color": AI_BUBBLE, "user_color": USER_BUBBLE, "text_color": "#22364f",
    "font_size": 13, "radius": 10, "opacity": 98,
}


def _fit_size(path: str, box: int) -> QSize:
    """按原图比例算出装进 box 大小后的尺寸（避免 GIF 被拉变形）。"""
    from PyQt6.QtGui import QImageReader
    sz = QImageReader(path).size()
    if not sz.isValid() or sz.width() <= 0 or sz.height() <= 0:
        return QSize(box, box)
    scale = min(box / sz.width(), box / sz.height())
    return QSize(max(1, int(sz.width() * scale)), max(1, int(sz.height() * scale)))


def _apply_sticker(label: QLabel, path: str, box: int = 150):
    """把表情包（含动图）放进 label，返回 QMovie 或 None。"""
    label.setCursor(Qt.CursorShape.PointingHandCursor)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    if path.lower().endswith(".gif"):
        movie = QMovie(path)
        movie.setScaledSize(_fit_size(path, box))
        label.setMovie(movie)
        movie.start()
        return movie
    pm = QPixmap(path).scaled(box, box, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
    label.setPixmap(pm)
    return None


class Bubble(QWidget):
    def __init__(self, role: str, text: str, sticker: Optional[str] = None,
                 on_delete=None, theme: Optional[dict] = None,
                 ts: Optional[str] = None, on_save_code=None) -> None:
        super().__init__()
        self.role = role
        self.sticker = sticker
        self.on_delete = on_delete
        self.on_save_code = on_save_code
        self.theme = dict(DEFAULT_THEME)
        if theme:
            self.theme.update(theme)
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 3, 6, 3)
        root.setSpacing(8)

        avatar = QLabel("🐳" if role == "assistant" else "🧑")
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            "font-size:16px;background:#eaf3ff;border-radius:15px;")

        # 整条消息（文字 + 表情包）装进同一个气泡里，微信风格
        self.bubble = QFrame()
        self.bubble.setObjectName("bubble")
        inner = QVBoxLayout(self.bubble)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(6)

        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        if not text:
            self.text_label.hide()
        inner.addWidget(self.text_label)

        self.sticker_label = QLabel()
        self._movie = None
        inner.addWidget(self.sticker_label)          # 始终在气泡布局内
        if sticker and os.path.exists(sticker):
            self._movie = _apply_sticker(self.sticker_label, sticker, 150)
            self.sticker_label.mousePressEvent = self._zoom  # type: ignore
        else:
            self.sticker_label.hide()

        self.bubble.setMaximumWidth(300)
        self._style()

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(self.bubble, 0, Qt.AlignmentFlag.AlignTop)
        if ts:
            tl = QLabel(ts)
            tl.setStyleSheet("color:#9bb0c6;font-size:10px;background:transparent;")
            col.addWidget(tl, 0, (Qt.AlignmentFlag.AlignLeft if role == "assistant"
                                  else Qt.AlignmentFlag.AlignRight))

        if role == "assistant":
            root.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
            root.addLayout(col)
            root.addStretch(1)
        else:
            root.addStretch(1)
            root.addLayout(col)
            root.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)

    def _style(self) -> None:
        t = self.theme
        bg = t["ai_color"] if self.role == "assistant" else t["user_color"]
        self.bubble.setStyleSheet(
            f"QFrame#bubble{{background:{bg};border-radius:{t['radius']}px;}}")
        self.text_label.setStyleSheet(
            f"background:transparent;color:{t['text_color']};"
            f"font-family:'Microsoft YaHei';font-size:{t['font_size']}px;")

    def apply_theme(self, theme: dict) -> None:
        self.theme.update(theme)
        self._style()

    def _zoom(self, e) -> None:
        if self.sticker:
            StickerViewer(self.sticker, self).exec()

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)
        if text:
            self.text_label.show()

    def contextMenuEvent(self, e) -> None:
        menu = QMenu(self)
        menu.addAction("复制", self._copy)
        if self.on_save_code and "```" in self.text_label.text():
            menu.addAction("收藏代码块", self._save_code)
        if self.on_delete:
            menu.addAction("删除这条", self.on_delete)
        menu.exec(e.globalPos())

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text_label.text())

    def _save_code(self) -> None:
        import re
        m = re.search(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", self.text_label.text(), re.S)
        if m and self.on_save_code:
            self.on_save_code(m.group(2).rstrip(), (m.group(1) or "").strip())


class ChatPanel(QWidget):
    send_message = pyqtSignal(str)
    request_screenshot = pyqtSignal()
    closed = pyqtSignal()
    save_code = pyqtSignal(str, str)      # 代码, 语言

    def __init__(self, stickers, theme: Optional[dict] = None) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.stickers = stickers
        self.theme = dict(DEFAULT_THEME)
        if theme:
            self.theme.update(theme)
        self._expanded = True
        self._stream_bubble: Optional[Bubble] = None
        self._history_input: list = []
        self._hist_idx = 0
        self._unread = 0
        self._phrases: list = list(COMPLETION_PHRASES)
        self._loading = False
        self._dragging = False
        self._drag_off = QPoint()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame()
        self._style_card()
        outer.addWidget(self.card)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # 标题栏
        bar = QHBoxLayout()
        title = QLabel("🐳 大肥鱼")
        title.setToolTip("哼，本鱼才不会主动找你聊天呢……才怪。")
        title.setStyleSheet(
            "font-family:'Microsoft YaHei';font-weight:bold;font-size:14px;"
            "color:#2c5c92;background:transparent;")
        bar.addWidget(title)
        mood = QLabel("· 傲娇营业中")
        mood.setStyleSheet("color:#8aa2bb;font-size:11px;background:transparent;")
        bar.addWidget(mood)
        bar.addStretch(1)
        self.btn_shot = QPushButton("📷 康康")
        self.btn_shot.setToolTip("让大肥鱼看看屏幕（全屏截图）")
        self.btn_clear = QPushButton("🧹")
        self.btn_clear.setToolTip("清空当前会话显示")
        self.btn_fold = QPushButton("▽")
        self.btn_fold.setToolTip("展开 / 收起")
        self.btn_close = QPushButton("✕")
        self.btn_close.setToolTip("收起对话框")
        for b in (self.btn_shot, self.btn_clear, self.btn_fold, self.btn_close):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setMinimumHeight(24)
            b.setStyleSheet(
                "QPushButton{border:none;color:#5a83b3;background:transparent;"
                "font-size:13px;padding:2px 7px;border-radius:7px;}"
                "QPushButton:hover{background:#e4f0ff;}"
                "QPushButton:pressed{background:#cfe4fb;}")
            bar.addWidget(b)
        self.btn_shot.setMinimumWidth(64)
        lay.addLayout(bar)

        # 消息区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:transparent;width:8px;}"
            "QScrollBar::handle:vertical{background:#c9dcf2;border-radius:4px;min-height:24px;}")
        self.msg_host = QWidget()
        self.msg_host.setStyleSheet("background:transparent;")
        self.msg_layout = QVBoxLayout(self.msg_host)
        self.msg_layout.setContentsMargins(0, 0, 0, 0)
        self.msg_layout.addStretch(1)
        self.scroll.setWidget(self.msg_host)
        lay.addWidget(self.scroll, 1)

        # 输入区
        inp = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("和本鱼说点什么吧…（↑↓翻历史）")
        self.input.setStyleSheet(
            "QLineEdit{border:1px solid #cfe2f7;border-radius:12px;padding:8px 10px;"
            "font-family:'Microsoft YaHei';background:#ffffff;color:#22364f;"
            "selection-background-color:#9ccbf3;selection-color:#173a63;}"
            "QLineEdit::placeholder{color:#9bb0c6;}")
        self.input.returnPressed.connect(self._on_send)
        self.btn_send = QPushButton("发送")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.setStyleSheet(
            "QPushButton{background:#8ec6f5;color:white;border:none;border-radius:12px;"
            "padding:8px 16px;font-family:'Microsoft YaHei';}"
            "QPushButton:hover{background:#6fb2ea;}")
        self.btn_send.clicked.connect(self._on_send)
        inp.addWidget(self.input, 1)
        inp.addWidget(self.btn_send)
        lay.addLayout(inp)

        self.input.installEventFilter(self)

        self.btn_close.clicked.connect(self.hide_panel)
        self.btn_fold.clicked.connect(self._toggle_fold)
        self.btn_clear.clicked.connect(self.clear)
        self.btn_shot.clicked.connect(self.request_screenshot.emit)

        # 打字中指示（· / ·· / ···）
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(320)
        self._typing_timer.timeout.connect(self._typing_tick)
        self._typing_step = 0
        self._typing_active = False

        self.setFixedWidth(PANEL_W)
        self.setFixedHeight(EXPANDED_H)

    # ------------------------------------------------------------ 工具
    def _now_ts(self) -> str:
        import datetime
        return datetime.datetime.now().strftime("%H:%M")

    def _typing_tick(self) -> None:
        if self._stream_bubble is None:
            return
        self._typing_step = (self._typing_step + 1) % 3
        self._stream_bubble.set_text("\u00b7" * (self._typing_step + 1))

    # ------------------------------------------------------------ 输入
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.input and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._recall(-1)
                return True
            if key == Qt.Key.Key_Down:
                self._recall(1)
                return True
            if key == Qt.Key.Key_Tab:            # Tab 智能补全
                text = self.input.text().strip()
                if text:
                    for c in self._phrases:
                        if c.startswith(text) and c != text:
                            self.input.setText(c)
                            break
                return True
        return super().eventFilter(obj, event)

    def _recall(self, step: int) -> None:
        if not self._history_input:
            return
        self._hist_idx = max(0, min(len(self._history_input), self._hist_idx + step))
        if self._hist_idx < len(self._history_input):
            self.input.setText(self._history_input[self._hist_idx])
        else:
            self.input.clear()

    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self._history_input.append(text)
        self._hist_idx = len(self._history_input)
        if text in self._phrases:
            self._phrases.remove(text)
        self._phrases.insert(0, text)
        self._phrases = self._phrases[:40]
        self.input.clear()
        self.send_message.emit(text)

    def _style_card(self) -> None:
        op = self.theme.get("opacity", 98) / 100.0
        self.card.setStyleSheet(
            f"QFrame{{background:rgba(250,252,255,{op:.2f});"
            "border:1px solid #cfe2f7;border-radius:16px;}")

    def apply_theme(self, theme: dict) -> None:
        self.theme.update(theme)
        self._style_card()
        for i in range(self.msg_layout.count()):
            w = self.msg_layout.itemAt(i).widget()
            if isinstance(w, Bubble):
                w.apply_theme(self.theme)

    # ------------------------------------------------------------ 消息
    def _add(self, widget: Bubble) -> None:
        widget.on_save_code = self._emit_save_code
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, widget)
        if not self._loading:
            self._fade_in(widget)
        QTimer.singleShot(30, self._scroll_bottom)

    def _emit_save_code(self, code: str, lang: str) -> None:
        self.save_code.emit(code, lang)

    def _fade_in(self, widget: Bubble) -> None:
        try:
            eff = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", widget)
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda w=widget: w.setGraphicsEffect(None))
            anim.start()
            widget._fade_anim = anim
        except Exception:
            try:
                widget.setGraphicsEffect(None)
            except Exception:
                pass

    def _scroll_bottom(self) -> None:
        sb = self.scroll.verticalScrollBar()
        try:
            anim = QPropertyAnimation(sb, b"value", self)
            anim.setDuration(180)
            anim.setStartValue(sb.value())
            anim.setEndValue(sb.maximum())
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.start()
            self._scroll_anim = anim
        except Exception:
            sb.setValue(sb.maximum())

    def add_user(self, text: str) -> None:
        self._add(Bubble("user", text, theme=self.theme, ts=self._now_ts()))

    def add_system(self, text: str, sticker: Optional[str] = None) -> None:
        self._add(Bubble("assistant", text, sticker, theme=self.theme,
                         ts=self._now_ts()))

    def load_history(self, messages) -> None:
        self._loading = True
        try:
            for m in messages:
                self._add(Bubble("assistant" if m.get("role") == "assistant" else "user",
                                 m.get("content", ""), m.get("sticker"), theme=self.theme))
        finally:
            self._loading = False

    def begin_stream(self) -> None:
        self._stream_bubble = Bubble("assistant", "", theme=self.theme,
                                     ts=self._now_ts())
        self._typing_active = True
        self._typing_step = 0
        self._stream_bubble.set_text("\u00b7")
        self._typing_timer.start()
        self._add(self._stream_bubble)

    def append_delta(self, text: str) -> None:
        if self._typing_active:
            self._typing_active = False
            self._typing_timer.stop()
            if self._stream_bubble is not None:
                self._stream_bubble.set_text("")
        if self._stream_bubble is None:
            self.begin_stream()
            self._typing_active = False
            self._typing_timer.stop()
            self._stream_bubble.set_text("")
        cur = self._stream_bubble.text_label.text()
        self._stream_bubble.set_text(cur + text)
        self._scroll_bottom()

    def end_stream(self, text: str, sticker_path: Optional[str]) -> None:
        self._typing_active = False
        self._typing_timer.stop()
        if self._stream_bubble is not None:
            self._stream_bubble.set_text(text)
            if sticker_path and os.path.exists(sticker_path):
                self._attach_sticker(self._stream_bubble, sticker_path)
        else:
            b = Bubble("assistant", text, sticker_path, theme=self.theme)
            self._add(b)
        self._stream_bubble = None
        self._scroll_bottom()

    def _attach_sticker(self, bubble: Bubble, path: str) -> None:
        bubble.sticker = path
        bubble.sticker_label.show()
        bubble._movie = _apply_sticker(bubble.sticker_label, path, 150)
        bubble.sticker_label.mousePressEvent = bubble._zoom  # type: ignore

    def clear(self) -> None:
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ------------------------------------------------------------ 面板
    def _toggle_fold(self) -> None:
        self._expanded = not self._expanded
        self.setFixedHeight(EXPANDED_H if self._expanded else COLLAPSED_H)
        self.btn_fold.setText("▽" if self._expanded else "△")

    # ------------------------------------------------------------ 拖动
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() <= 44:
            child = self.childAt(e.position().toPoint())
            if not isinstance(child, QPushButton):
                self._dragging = True
                self._drag_off = (e.globalPosition().toPoint()
                                  - self.frameGeometry().topLeft())
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._dragging and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_off)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        self._dragging = False
        super().mouseReleaseEvent(e)

    def hide_panel(self) -> None:
        self.hide()
        self.closed.emit()

    def show_near(self, x: int, y: int) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        px = max(10, min(x - PANEL_W // 2, screen.right() - PANEL_W - 10))
        py = y - self.height() - 10
        if py < 10:
            py = y + 10
        self.move(px, py)
        try:
            self.input.setPlaceholderText(ui_theme.random_placeholder())
        except Exception:
            pass
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
