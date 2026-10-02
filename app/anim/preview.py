# -*- coding: utf-8 -*-
"""动作预览窗口：实时播放生成的动画序列，可调整每帧间隔、插值参数，
并内置动作状态机做 Idle / 点击 / 思考 / 走路 的切换演示。

兼容 PyQt6 与 PySide6（优先 PyQt6，未安装则用 PySide6）。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from PIL import Image

# ---------------------------------------------------------------- Qt 兼容层
QT_BINDING = "PyQt6"
try:
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal as Signal  # type: ignore
    from PyQt6.QtGui import QImage, QPainter, QPixmap        # type: ignore
    from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox,  # type: ignore
                                 QHBoxLayout, QLabel, QListWidget,
                                 QPushButton, QSlider, QSpinBox,
                                 QVBoxLayout, QWidget)
except Exception:  # pragma: no cover
    QT_BINDING = "PySide6"
    from PySide6.QtCore import Qt, QTimer, Signal  # type: ignore
    from PySide6.QtGui import QImage, QPainter, QPixmap  # type: ignore
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,  # type: ignore
                                   QHBoxLayout, QLabel, QListWidget,
                                   QPushButton, QSlider, QSpinBox,
                                   QVBoxLayout, QWidget)

from . import paths, png_seq
from .bootstrap import compile_all
from .clips import DEFAULT_CLIPS, ActionStateMachine

STYLE = """
QWidget{background:#eef6ff;font-family:'Microsoft YaHei';font-size:13px;color:#173a63;}
QListWidget{background:#e3effd;border:none;border-radius:10px;padding:4px;}
QListWidget::item{padding:6px 8px;border-radius:6px;}
QListWidget::item:selected{background:#bcdcff;color:#173a63;}
QLabel{color:#33608f;}
QPushButton{border:none;border-radius:9px;padding:7px 12px;background:#9ccbf3;color:white;}
QPushButton:hover{background:#7ab5ea;}
QCheckBox{color:#33608f;spacing:6px;}
QSpinBox,QComboBox{background:white;border:1px solid #c3ddf7;border-radius:7px;padding:4px 6px;}
QSlider::groove:horizontal{height:6px;background:#cfe2f7;border-radius:3px;}
QSlider::handle:horizontal{width:16px;margin:-6px 0;border-radius:8px;background:#7ab5ea;}
"""


def pil_to_pixmap(im: Image.Image) -> QPixmap:
    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    qimg = QImage(data, im.width, im.height, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimg)


class PreviewWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"大肥鱼 · 动作预览（{QT_BINDING}）")
        self.setStyleSheet(STYLE)
        self.resize(860, 560)

        self.frames: List[QPixmap] = []
        self.clip_frames: Dict[str, List[QPixmap]] = {}
        self.idx = 0
        self.machine: Optional[ActionStateMachine] = None

        root = QHBoxLayout(self)

        # 左：动作列表
        left = QVBoxLayout()
        left.addWidget(QLabel("动作"))
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._on_pick)
        left.addWidget(self.list, 1)
        btn_all = QPushButton("生成全部动作")
        btn_all.clicked.connect(self._compile_all)
        left.addWidget(btn_all)
        root.addLayout(left)

        # 中：预览
        mid = QVBoxLayout()
        self.canvas = QLabel("（还没有动画，点右侧「生成当前动作」）")
        self.canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.setMinimumSize(380, 400)
        self.canvas.setStyleSheet("background:#ffffff;border:1px solid #c3ddf7;"
                                  "border-radius:12px;")
        mid.addWidget(self.canvas, 1)
        self.play = QPushButton("▶ 播放")
        self.play.clicked.connect(self._toggle)
        mid.addWidget(self.play)
        root.addLayout(mid, 1)

        # 右：控制
        right = QVBoxLayout()
        right.addWidget(QLabel("每帧间隔(ms)"))
        self.interval = QSlider(Qt.Orientation.Horizontal)
        self.interval.setRange(20, 300)
        self.interval.setValue(100)
        self.interval_label = QLabel("100")
        self.interval.valueChanged.connect(self._on_interval)
        row = QHBoxLayout(); row.addWidget(self.interval, 1); row.addWidget(self.interval_label)
        right.addLayout(row)

        right.addWidget(QLabel("插值帧数（每两关键帧之间）"))
        self.inbet = QSpinBox(); self.inbet.setRange(0, 30); self.inbet.setValue(6)
        right.addWidget(self.inbet)

        right.addWidget(QLabel("插值方式"))
        self.mode = QComboBox(); self.mode.addItems(["warp（对齐插值）",
                                                     "dissolve（淡化）", "cut（不插值）"])
        right.addWidget(self.mode)

        right.addWidget(QLabel("生成帧率(fps)"))
        self.fps = QSpinBox(); self.fps.setRange(1, 30); self.fps.setValue(10)
        right.addWidget(self.fps)

        self.loop = QCheckBox("循环播放"); self.loop.setChecked(True)
        right.addWidget(self.loop)

        btn_gen = QPushButton("生成当前动作")
        btn_gen.clicked.connect(self._compile_current)
        right.addWidget(btn_gen)

        self.demo = QCheckBox("动作切换演示（状态机）")
        self.demo.toggled.connect(self._toggle_demo)
        right.addWidget(self.demo)

        self.status = QLabel("提示：关键帧放在 assets/anim_frames/<动作>/")
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        right.addStretch(1)
        root.addLayout(right)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(100)
        self.demo_timer = QTimer(self)
        self.demo_timer.timeout.connect(self._demo_tick)

        self.machine = ActionStateMachine()
        self._refresh_list()

    # ------------------------------------------------------------ 列表
    def _actions(self) -> List[str]:
        root = paths.anim_root()
        names = []
        if os.path.isdir(root):
            for d in sorted(os.listdir(root)):
                full = os.path.join(root, d)
                if os.path.isdir(full) and not d.startswith("_"):
                    names.append(d)
        return names or list(DEFAULT_CLIPS.keys())

    def _refresh_list(self) -> None:
        cur = self.list.currentItem().text() if self.list.currentItem() else None
        self.list.clear()
        for n in self._actions():
            self.list.addItem(n)
        if cur:
            items = self.list.findItems(cur, Qt.MatchFlag.MatchExactly)
            if items:
                self.list.setCurrentItem(items[0])
        if self.list.count() and not self.list.currentItem():
            self.list.setCurrentRow(0)

    # ------------------------------------------------------------ 加载
    def _frames_for(self, action: str) -> List[QPixmap]:
        compiled = os.path.join(paths.compiled_root(), action)
        paths_list = png_seq.list_keyframes(compiled, prefix="f")
        if not paths_list:
            paths_list = png_seq.list_keyframes(os.path.join(paths.anim_root(), action))
        out = []
        for p in paths_list:
            try:
                with Image.open(p) as im:
                    out.append(pil_to_pixmap(im))
            except Exception:
                continue
        return out

    def _on_pick(self, action: str) -> None:
        if not action:
            return
        # 演示模式下预先加载所有动作帧
        self.clip_frames = {a: self._frames_for(a) for a in self._actions()}
        self.frames = self.clip_frames.get(action, [])
        self.idx = 0
        for name, fr in self.clip_frames.items():
            self.machine.set_length(name, len(fr) or 1)
        self._draw_current()
        self.status.setText(f"{action}：{len(self.frames)} 帧")

    def _draw_current(self) -> None:
        pm = self.frames[self.idx] if self.frames else None
        if pm is None:
            self.canvas.setText("（没有帧）")
            return
        self.canvas.setPixmap(pm.scaled(
            self.canvas.width() - 20, self.canvas.height() - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    # ------------------------------------------------------------ 播放
    def _on_interval(self, v: int) -> None:
        self.interval_label.setText(str(v))
        self.timer.setInterval(v)

    def _toggle(self) -> None:
        if self.timer.isActive():
            self.timer.stop(); self.play.setText("▶ 播放")
        else:
            self.timer.start(self.interval.value()); self.play.setText("⏸ 暂停")

    def _tick(self) -> None:
        if self.demo.isChecked():
            return
        if not self.frames:
            return
        self.idx += 1
        if self.idx >= len(self.frames):
            if self.loop.isChecked():
                self.idx = 0
            else:
                self.idx = len(self.frames) - 1
                self.timer.stop()
        self._draw_current()

    # ------------------------------------------------------------ 编译
    def _mode_key(self) -> str:
        return ["warp", "dissolve", "cut"][max(0, self.mode.currentIndex())]

    def _compile_current(self) -> None:
        action = self.list.currentItem().text() if self.list.currentItem() else None
        if not action:
            return
        kf = png_seq.list_keyframes(os.path.join(paths.anim_root(), action))
        if not kf:
            self.status.setText("没有关键帧，请先放 PNG 到该动作文件夹")
            return
        spec = DEFAULT_CLIPS.get(action)
        res = png_seq.compile_clip(
            action, kf, paths.compiled_root(),
            fps=float(self.fps.value()), inbetweens=self.inbet.value(),
            mode=self._mode_key(), loop=spec.loop if spec else True)
        self.status.setText(
            f"{action} 已生成 {res.get('frames')} 帧\n"
            f"APNG: {os.path.basename(res.get('apng') or '')} / "
            f"GIF: {os.path.basename(res.get('gif') or '')}")
        self._on_pick(action)

    def _compile_all(self) -> None:
        results = compile_all(force=True)
        txt = "已生成：" + "，".join(f"{k}({v.get('frames')})" for k, v in results.items()
                                 if v.get("ok"))
        self.status.setText(txt)
        self._refresh_list()
        if self.list.currentItem():
            self._on_pick(self.list.currentItem().text())

    # ------------------------------------------------------------ 状态机演示
    def _toggle_demo(self, on: bool) -> None:
        if on:
            self._on_pick(self.list.currentItem().text() if self.list.currentItem()
                          else "idle")
            order = [a for a in ("idle", "walk", "think") if a in self.clip_frames]
            self._demo_order = order or list(self.clip_frames.keys())
            self._demo_i = 0
            self.machine.set_state(self._demo_order[0], restart=True)
            self.demo_timer.start(66)
        else:
            self.demo_timer.stop()

    def _demo_tick(self) -> None:
        st = self.machine.update(0.066)
        self._demo_i += 1
        # 每 ~2 秒换下一个动作
        if self._demo_i % 30 == 0 and getattr(self, "_demo_order", None):
            self._demo_i = 0
            order = self._demo_order
            cur = order.index(st.clip) if st.clip in order else -1
            self.machine.set_state(order[(cur + 1) % len(order)])
        self._paint_state(st)

    def _paint_state(self, st) -> None:
        cur_list = self.clip_frames.get(st.clip) or []
        if not cur_list:
            return
        base = QPixmap(self.canvas.size()); base.fill(Qt.GlobalColor.transparent)
        p = QPainter(base)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = base.width() - 20, base.height() - 20

        def draw(fr_list, index, alpha):
            if not fr_list:
                return
            pm = fr_list[index % len(fr_list)].scaled(
                w, h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            p.setOpacity(alpha)
            p.drawPixmap((base.width() - pm.width()) // 2,
                         (base.height() - pm.height()) // 2, pm)

        if st.prev_clip:
            draw(self.clip_frames.get(st.prev_clip, []), st.prev_index,
                 1.0 - st.blend)
        draw(cur_list, st.index, st.blend if st.prev_clip else 1.0)
        p.end()
        self.canvas.setPixmap(base)
        self.status.setText(f"状态机：{st.clip}  帧 {st.index + 1}/{st.count}")


def run_preview() -> int:
    """独立启动预览窗口（供 anim_preview.py 调用）。"""
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    win = PreviewWindow()
    win.show()
    if win.list.currentItem():
        win._on_pick(win.list.currentItem().text())
    return app.exec()
