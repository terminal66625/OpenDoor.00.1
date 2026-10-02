# -*- coding: utf-8 -*-
"""设置面板：API / 模型 / 压缩上下文 / 透明度 / 隐形 / 闹钟 / 删除记忆。"""
from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
                             QFileDialog, QFormLayout, QGraphicsOpacityEffect,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QSlider, QSpinBox, QStackedWidget,
                             QTextBrowser, QVBoxLayout, QWidget)

from . import const
from . import ui_theme


def _ask_text(parent, title: str, default: str):
    return QInputDialog.getText(parent, "大肥鱼", title, QLineEdit.EchoMode.Normal, default)

STYLE = """
QDialog{background:#eef6ff;font-family:'Microsoft YaHei';font-size:13px;color:#173a63;}
QListWidget{background:#e3effd;border:none;border-radius:12px;padding:6px;color:#33608f;font-size:13px;}
QListWidget::item{padding:9px 10px;border-radius:8px;}
QListWidget::item:selected{background:#bcdcff;color:#173a63;}
QLabel{color:#33608f;background:transparent;}
QLineEdit{background:#ffffff;color:#173a63;border:1px solid #c3ddf7;border-radius:8px;padding:6px 8px;selection-background-color:#9ccbf3;selection-color:#173a63;}
QLineEdit:focus{border:1px solid #7ab5ea;}
QComboBox{background:#ffffff;color:#173a63;border:1px solid #c3ddf7;border-radius:8px;padding:6px 8px;}
QComboBox QAbstractItemView{background:#ffffff;color:#173a63;border:1px solid #c3ddf7;selection-background-color:#bcdcff;selection-color:#173a63;outline:none;}
QSpinBox{background:#ffffff;color:#173a63;border:1px solid #c3ddf7;border-radius:8px;padding:4px 6px;}
QCheckBox{color:#33608f;spacing:8px;}
QPushButton{border:none;border-radius:10px;padding:8px 14px;background:#9ccbf3;color:white;}
QPushButton:hover{background:#7ab5ea;}
QPushButton#ghost{background:#dceafb;color:#33608f;}
QPushButton#ghost:hover{background:#c9def5;}
QSlider::groove:horizontal{height:6px;background:#cfe2f7;border-radius:3px;}
QSlider::handle:horizontal{width:16px;margin:-6px 0;border-radius:8px;background:#7ab5ea;}
"""

PAGES = ["API", "信息与余额", "气泡外观", "整体透明度", "定闹钟", "待办",
         "角色", "功能开关", "压缩上下文", "隐形", "删除记忆"]


class SettingsDialog(QDialog):
    saved = pyqtSignal()
    test_requested = pyqtSignal(str)          # api_key
    compress_now = pyqtSignal()
    invisible = pyqtSignal()
    delete_memory = pyqtSignal()
    theme_changed = pyqtSignal(dict)
    character_switch = pyqtSignal(str)
    character_import = pyqtSignal()
    info_refresh = pyqtSignal()

    def __init__(self, cfg, scheduler, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint)
        self.cfg = cfg
        self.scheduler = scheduler
        self.setWindowTitle("大肥鱼 · 设置")
        self.setStyleSheet(ui_theme.DIALOG_QSS)
        self.resize(800, 620)
        self.setMinimumSize(720, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)
        head = QLabel(ui_theme.header("大肥鱼 · 设置", ui_theme.random_subtitle()))
        head.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(head)

        root = QHBoxLayout()
        outer.addLayout(root, 1)
        self.nav = QListWidget()
        self.nav.setFixedWidth(156)
        self.nav.setSpacing(3)                 # 拉开选项间距
        self.nav.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        for name in PAGES:
            item = QListWidgetItem(name)
            item.setSizeHint(QSize(0, 40))     # 每项固定高度，避免边框互相遮挡
            self.nav.addItem(item)
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_api()
        self._build_info()
        self._build_theme()
        self._build_opacity()
        self._build_alarm()
        self._build_todos()
        self._build_character()
        self._build_toggles()
        self._build_compress()
        self._build_invisible()
        self._build_memory()

        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)

    def _on_nav(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        page = self.stack.currentWidget()
        if page is not None:             # 页面切换淡入动画
            try:
                eff = QGraphicsOpacityEffect(page)
                page.setGraphicsEffect(eff)
                anim = QPropertyAnimation(eff, b"opacity", self)
                anim.setDuration(150)
                anim.setStartValue(0.25)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.finished.connect(lambda p=page: p.setGraphicsEffect(None))
                anim.start()
                self._page_anim = anim
            except Exception:
                page.setGraphicsEffect(None)
        if idx == 1:                     # 信息与余额页
            self.info_refresh.emit()

    def show_page(self, key: str) -> None:
        mapping = {"api": 0, "info": 1, "theme": 2, "opacity": 3, "alarm": 4,
                   "todos": 5, "character": 6, "toggles": 7, "compress": 8,
                   "invisible": 9, "memory": 10}
        self.nav.setCurrentRow(mapping.get(key, 0))

    def set_info_html(self, html: str) -> None:
        try:
            self.info_view.setHtml(html)
        except Exception:
            pass

    # ------------------------------------------------------------ API
    def _build_api(self) -> None:
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        f.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        f.setSpacing(10)

        tip = QLabel(f"接口地址（固定）：{const.DEFAULT_BASE_URL}")
        tip.setStyleSheet("color:#7a93ad;font-size:12px;")

        self.api_key = QLineEdit(self.cfg.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("在这里粘贴 DeepSeek 的 API Key（sk- 开头）")
        self.api_key.setMinimumWidth(360)
        show = QPushButton("显示")
        show.setObjectName("ghost")
        show.setCheckable(True)
        show.toggled.connect(lambda on: self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row = QHBoxLayout(); key_row.addWidget(self.api_key, 1); key_row.addWidget(show)

        self.temp = QSlider(Qt.Orientation.Horizontal)
        self.temp.setRange(0, 100); self.temp.setValue(int(self.cfg.get("temperature", 0.4) * 100))
        self.temp_label = QLabel(f"{self.temp.value()/100:.2f}")
        self.temp_label.setFixedWidth(40)
        self.temp.valueChanged.connect(lambda v: self.temp_label.setText(f"{v/100:.2f}"))

        self.tick = QSlider(Qt.Orientation.Horizontal)
        self.tick.setRange(1, 5); self.tick.setValue(int(self.cfg.get("tick_interval", 2)))
        self.tick_label = QLabel(str(self.tick.value()))
        self.tick_label.setFixedWidth(40)
        self.tick.valueChanged.connect(lambda v: self.tick_label.setText(str(v)))

        f.addRow(tip)
        f.addRow("API Key", key_row)
        f.addRow("Temperature（随机程度 0~1）", self._row(self.temp, self.temp_label))
        f.addRow("决策间隔（秒 1~5）", self._row(self.tick, self.tick_label))

        btns = QHBoxLayout()
        b_test = QPushButton("测试连接"); b_save = QPushButton("保存")
        b_clear = QPushButton("清除 Key"); b_clear.setObjectName("ghost")
        b_test.clicked.connect(lambda: self.test_requested.emit(self.api_key.text().strip()))
        b_save.clicked.connect(self._save)
        b_clear.clicked.connect(self._clear_key)
        for b in (b_test, b_save, b_clear):
            btns.addWidget(b)
        f.addRow(btns)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        f.addRow(self.test_result)

        about = QLabel(f"{const.APP_NAME} v{const.APP_VERSION}　数据目录：{const.BASE_DIR}")
        about.setStyleSheet("color:#9bb0c6;font-size:11px;")
        f.addRow(about)
        self.stack.addWidget(w)

    def set_test_result(self, ok: bool, msg: str) -> None:
        color = "#1a9e4b" if ok else "#d64545"
        self.test_result.setStyleSheet(f"color:{color};")
        self.test_result.setText(msg)

    def _clear_key(self) -> None:
        self.api_key.clear()
        self.cfg.clear_key(); self.cfg.save()
        self.test_result.setStyleSheet("color:#3a6ea8;")
        self.test_result.setText("已清除 API Key")

    # ------------------------------------------------------------ 信息与余额
    def _build_info(self) -> None:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("大肥鱼的状态与 Token 余额："))
        self.info_view = QTextBrowser()
        self.info_view.setOpenExternalLinks(False)
        self.info_view.setStyleSheet(
            "QTextBrowser{background:#ffffff;color:#173a63;border:1px solid #c3ddf7;"
            "border-radius:8px;padding:8px;font-family:'Microsoft YaHei';font-size:13px;}")
        v.addWidget(self.info_view, 1)
        row = QHBoxLayout()
        b = QPushButton("刷新余额")
        b.clicked.connect(self.info_refresh.emit)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.stack.addWidget(w)

    # ------------------------------------------------------------ 气泡外观
    def _build_theme(self) -> None:
        w = QWidget(); f = QFormLayout(w)
        self._theme = dict(self.cfg.get("theme") or {})
        self.color_btns = {}
        for key, label in (("ai_color", "大肥鱼气泡"), ("user_color", "主人气泡"),
                           ("text_color", "文字颜色")):
            btn = QPushButton(); btn.setFixedSize(70, 26)
            self._paint_btn(btn, self._theme.get(key, "#ffffff"))
            btn.clicked.connect(lambda _, k=key, b=btn: self._pick_color(k, b))
            self.color_btns[key] = btn
            f.addRow(label, btn)

        self.font_spin = QSpinBox(); self.font_spin.setRange(10, 22)
        self.font_spin.setValue(int(self._theme.get("font_size", 13)))
        self.font_spin.valueChanged.connect(self._emit_theme)
        self.radius = QSlider(Qt.Orientation.Horizontal); self.radius.setRange(0, 20)
        self.radius.setValue(int(self._theme.get("radius", 10)))
        self.radius_label = QLabel(str(self.radius.value()))
        self.radius.valueChanged.connect(lambda v: (self.radius_label.setText(str(v)),
                                                    self._emit_theme()))
        self.bub_op = QSlider(Qt.Orientation.Horizontal); self.bub_op.setRange(40, 100)
        self.bub_op.setValue(int(self._theme.get("opacity", 98)))
        self.bub_op_label = QLabel(str(self.bub_op.value()))
        self.bub_op.valueChanged.connect(lambda v: (self.bub_op_label.setText(str(v)),
                                                    self._emit_theme()))
        f.addRow("字号", self.font_spin)
        f.addRow("圆角", self._row(self.radius, self.radius_label))
        f.addRow("气泡透明度", self._row(self.bub_op, self.bub_op_label))
        self.stack.addWidget(w)

    def _paint_btn(self, btn: QPushButton, color: str) -> None:
        btn.setStyleSheet(f"background:{color};border:1px solid #9cc2e8;border-radius:6px;")

    def _pick_color(self, key: str, btn: QPushButton) -> None:
        col = QColorDialog.getColor(QColor(self._theme.get(key, "#ffffff")), self, "选择颜色")
        if col.isValid():
            self._theme[key] = col.name()
            self._paint_btn(btn, col.name())
            self._emit_theme()

    def _emit_theme(self) -> None:
        self._theme.update({
            "font_size": self.font_spin.value(),
            "radius": self.radius.value(),
            "opacity": self.bub_op.value(),
        })
        self.cfg.set("theme", self._theme)
        self.cfg.save()
        self.theme_changed.emit(dict(self._theme))

    # ------------------------------------------------------------ 待办
    def _build_todos(self) -> None:
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("轻量待办（到点大肥鱼会弹窗+动作提醒）："))
        self.todo_list = QListWidget()
        v.addWidget(self.todo_list, 1)
        self._refresh_todos()
        row = QHBoxLayout()
        self.todo_text = QLineEdit("写作业")
        self.todo_time = QLineEdit("20:00"); self.todo_time.setFixedWidth(70)
        add = QPushButton("添加")
        add.clicked.connect(self._add_todo)
        row.addWidget(QLabel("内容")); row.addWidget(self.todo_text, 1)
        row.addWidget(QLabel("时间")); row.addWidget(self.todo_time)
        row.addWidget(add)
        v.addLayout(row)
        self.stack.addWidget(w)

    def _refresh_todos(self) -> None:
        self.todo_list.clear()
        for i, t in enumerate(self.scheduler.todos):
            item = QListWidgetItem(f"{t.get('time')}　{t.get('text')}")
            widget = QWidget(); h = QHBoxLayout(widget); h.setContentsMargins(0, 0, 0, 0)
            h.addStretch(1)
            b = QPushButton("✕"); b.setObjectName("ghost"); b.setFixedWidth(30)
            b.clicked.connect(lambda _, idx=i: self._del_todo(idx))
            h.addWidget(b)
            self.todo_list.addItem(item)
            self.todo_list.setItemWidget(item, widget)

    def _add_todo(self) -> None:
        from .util import parse_hhmm
        if not parse_hhmm(self.todo_time.text()):
            QMessageBox.warning(self, "大肥鱼", "时间格式应为 HH:MM")
            return
        self.scheduler.add_todo(self.todo_text.text().strip() or "待办", self.todo_time.text().strip())
        self._refresh_todos()

    def _del_todo(self, idx: int) -> None:
        if 0 <= idx < len(self.scheduler.todos):
            self.scheduler.todos.pop(idx)
            self.scheduler.save_todos()
            self._refresh_todos()

    # ------------------------------------------------------------ 角色
    def _build_character(self) -> None:
        from . import assets
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("选择或导入角色（一键切换）："))
        self.char_list = QListWidget()
        v.addWidget(self.char_list, 1)
        self._refresh_chars()
        row = QHBoxLayout()
        switch = QPushButton("切换"); imp = QPushButton("导入图片")
        dele = QPushButton("删除"); dele.setObjectName("ghost")
        switch.clicked.connect(self._switch_char)
        imp.clicked.connect(self._import_char)
        dele.clicked.connect(self._delete_char)
        row.addWidget(switch); row.addWidget(imp); row.addWidget(dele)
        v.addLayout(row)
        self.stack.addWidget(w)

    def _refresh_chars(self) -> None:
        from . import assets
        self.char_list.clear()
        current = self.cfg.get("character", "大肥鱼")
        for name in assets.list_characters():
            mark = "（使用中）" if name == current else ""
            self.char_list.addItem(f"{name}{mark}")

    def _switch_char(self) -> None:
        item = self.char_list.currentItem()
        if not item:
            return
        name = item.text().replace("（使用中）", "").strip()
        self.cfg.set("character", name); self.cfg.save()
        self._refresh_chars()
        self.character_switch.emit(name)

    def _import_char(self) -> None:
        from . import assets
        path, _ = QFileDialog.getOpenFileName(self, "选择角色图片", "",
                                              "图片 (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        name, ok = _ask_text(self, "给这个角色起个名字", "角色")
        if not ok or not name.strip():
            return
        if assets.import_character(path, name.strip()):
            self.cfg.set("character", name.strip()); self.cfg.save()
            self._refresh_chars()
            self.character_switch.emit(name.strip())
            self.character_import.emit()

    def _delete_char(self) -> None:
        from . import assets
        item = self.char_list.currentItem()
        if not item:
            return
        name = item.text().replace("（使用中）", "").strip()
        if assets.delete_character(name):
            if self.cfg.get("character") == name:
                self.cfg.set("character", "大肥鱼"); self.cfg.save()
                self.character_switch.emit("大肥鱼")
            self._refresh_chars()
        else:
            QMessageBox.information(self, "大肥鱼", "默认角色不能删除哦")

    # ------------------------------------------------------------ 功能开关
    def _build_toggles(self) -> None:
        w = QWidget(); v = QVBoxLayout(w)
        self._toggles = {}
        items = [
            ("allow_move", "允许大肥鱼在桌面上移动（关闭后只原地待着）"),
            ("use_anim_clips", "使用动作动画片段（idle / 走路 / 点击 / 思考）"),
            ("use_action_refs", "使用「动作行为参考」动作（文字随语境、其余随机）"),
            ("use_movies", "动作视频（投喂吃/囤token开心/闲置做动作，带同步声音）"),
            ("close_documents", "开机自动关闭弹出的「文档」窗口"),
            ("clipboard_helper", "剪贴板助手（复制文字后一键解读/润色/查错/翻译）"),
            ("meal_reminder", "饭点提醒（每天 8/12/18 点讨 TOKEN 与大白饭）"),
            ("mute_fullscreen", "全屏免打扰（全屏程序时静默）"),
            ("smart_downclock", "智能降频（空闲/高负载时降低帧率省电）"),
            ("auto_start", "开机自动启动大肥鱼"),
            ("sound_enabled", "提醒铃声"),
        ]
        for key, label in items:
            cb = QCheckBox(label)
            cb.setChecked(bool(self.cfg.get(key, True)))
            cb.stateChanged.connect(lambda _, k=key, c=cb: self._toggle(k, c))
            v.addWidget(cb)
            self._toggles[key] = cb
        v.addSpacing(6)
        v.addWidget(QLabel("大肥鱼音量（动作声音 / 提醒铃声，0~100）："))
        vrow = QHBoxLayout()
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        try:
            self.vol_slider.setValue(int(self.cfg.get("action_volume", 70)))
        except Exception:
            self.vol_slider.setValue(70)
        self.vol_label = QLabel(str(self.vol_slider.value()))
        self.vol_label.setFixedWidth(36)
        self.vol_slider.valueChanged.connect(self._on_volume)
        vrow.addWidget(self.vol_slider, 1)
        vrow.addWidget(self.vol_label)
        v.addLayout(vrow)
        v.addStretch(1)
        self.stack.addWidget(w)

    def _on_volume(self, val: int) -> None:
        self.vol_label.setText(str(val))
        self.cfg.set("action_volume", int(val))
        self.cfg.save()
        self.saved.emit()

    def _toggle(self, key: str, cb) -> None:
        self.cfg.set(key, cb.isChecked())
        self.cfg.save()
        self.saved.emit()

    # ------------------------------------------------------------ 压缩
    def _build_compress(self) -> None:
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("压缩上下文：只保留很少一部分主人的爱好、习惯，\n大幅增加对话的缓存命中。"))
        b = QPushButton("立即压缩")
        b.clicked.connect(self._do_compress)
        v.addWidget(b)
        v.addStretch(1)
        self.stack.addWidget(w)

    def _do_compress(self) -> None:
        self.compress_now.emit()
        QMessageBox.information(self, "大肥鱼", "上下文已经压缩好啦~ 本鱼的脑袋清爽多了 (๑•̀ㅂ•́)و")

    # ------------------------------------------------------------ 透明度
    def _build_opacity(self) -> None:
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("整体透明度（1~100）："))
        row = QHBoxLayout()
        minus = QPushButton("－"); plus = QPushButton("＋")
        minus.setObjectName("ghost"); plus.setObjectName("ghost")
        self.op_slider = QSlider(Qt.Orientation.Horizontal)
        self.op_slider.setRange(1, 100)
        self.op_slider.setValue(self.cfg.opacity)
        self.op_label = QLabel(str(self.cfg.opacity))
        self.op_label.setFixedWidth(36)
        minus.clicked.connect(lambda: self.op_slider.setValue(self.op_slider.value() - 1))
        plus.clicked.connect(lambda: self.op_slider.setValue(self.op_slider.value() + 1))
        self.op_slider.valueChanged.connect(self._on_opacity)
        row.addWidget(minus); row.addWidget(self.op_slider, 1)
        row.addWidget(plus); row.addWidget(self.op_label)
        v.addLayout(row)

        v.addWidget(QLabel("形象大小："))
        row2 = QHBoxLayout()
        self.sc_slider = QSlider(Qt.Orientation.Horizontal)
        self.sc_slider.setRange(40, 180)
        self.sc_slider.setValue(self.cfg.scale)
        self.sc_label = QLabel(str(self.cfg.scale))
        self.sc_slider.valueChanged.connect(self._on_scale)
        row2.addWidget(self.sc_slider, 1); row2.addWidget(self.sc_label)
        v.addLayout(row2)
        v.addStretch(1)
        self.stack.addWidget(w)

    def _on_opacity(self, v: int) -> None:
        self.op_label.setText(str(v))
        self.cfg.opacity = v
        self.cfg.save()
        self.saved.emit()

    def _on_scale(self, v: int) -> None:
        self.sc_label.setText(str(v))
        self.cfg.set("scale", v)
        self.cfg.save()
        self.saved.emit()

    # ------------------------------------------------------------ 隐形
    def _build_invisible(self) -> None:
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("隐形并关闭程序，直到下次开机自启，\n或点击「大肥鱼」文件夹里的「启动大肥鱼」快捷方式。"))
        b = QPushButton("隐形（关闭大肥鱼）")
        b.clicked.connect(lambda: (self.invisible.emit(), self.accept()))
        v.addWidget(b)
        v.addStretch(1)
        self.stack.addWidget(w)

    # ------------------------------------------------------------ 闹钟
    def _build_alarm(self) -> None:
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("闹钟列表（右侧 ✕ 删除）："))
        self.alarm_list = QListWidget()
        v.addWidget(self.alarm_list, 1)
        self._refresh_alarms()
        row = QHBoxLayout()
        self.alarm_time = QLineEdit("08:00")
        self.alarm_time.setFixedWidth(80)
        self.alarm_label = QLineEdit("起床啦")
        add = QPushButton("添加闹钟")
        add.clicked.connect(self._add_alarm)
        row.addWidget(QLabel("时间")); row.addWidget(self.alarm_time)
        row.addWidget(QLabel("名称")); row.addWidget(self.alarm_label, 1)
        row.addWidget(add)
        v.addLayout(row)
        self.stack.addWidget(w)

    def _refresh_alarms(self) -> None:
        self.alarm_list.clear()
        for i, a in enumerate(self.scheduler.alarms):
            item = QListWidgetItem(f"{a.get('time')}　{a.get('label', '')}")
            widget = QWidget()
            h = QHBoxLayout(widget); h.setContentsMargins(0, 0, 0, 0)
            h.addStretch(1)
            del_btn = QPushButton("✕"); del_btn.setObjectName("ghost")
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(lambda _, idx=i: self._del_alarm(idx))
            h.addWidget(del_btn)
            self.alarm_list.addItem(item)
            self.alarm_list.setItemWidget(item, widget)

    def _add_alarm(self) -> None:
        t = self.alarm_time.text().strip()
        from .util import parse_hhmm
        if not parse_hhmm(t):
            QMessageBox.warning(self, "大肥鱼", "时间格式应为 HH:MM，例如 08:30")
            return
        self.scheduler.add_alarm(t, self.alarm_label.text().strip() or "闹钟")
        self._refresh_alarms()

    def _del_alarm(self, idx: int) -> None:
        self.scheduler.remove_alarm(idx)
        self._refresh_alarms()

    # ------------------------------------------------------------ 删除记忆
    def _build_memory(self) -> None:
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel("删除与这只大肥鱼的所有聊天记录和记忆，\n恢复至最初的状态（不可恢复）。"))
        self.also_art = QCheckBox("同时删除已生成的形象（下次启动重新抠图）")
        v.addWidget(self.also_art)
        b = QPushButton("删除记忆")
        b.clicked.connect(self._do_delete)
        v.addWidget(b)
        v.addStretch(1)
        self.stack.addWidget(w)

    def _do_delete(self) -> None:
        if QMessageBox.question(self, "确认", "真的要删除本鱼的所有记忆吗？(｡•́︿•̀｡)") \
                == QMessageBox.StandardButton.Yes:
            self.delete_memory.emit()
            if self.also_art.isChecked():
                import os
                try:
                    if os.path.exists(const.BODY_PATH):
                        os.remove(const.BODY_PATH)
                    if os.path.exists(const.BODY_META):
                        os.remove(const.BODY_META)
                except OSError:
                    pass
            QMessageBox.information(self, "大肥鱼", "本鱼已经忘记一切啦……初次见面，主人好 (｡･ω･｡)")

    # ------------------------------------------------------------ 保存
    def _save(self) -> None:
        self.cfg.set("base_url", const.DEFAULT_BASE_URL)
        key = self.api_key.text().strip()
        if key and (key != self.cfg.api_key):
            self.cfg.api_key = key
            self.cfg.set("key_verified", False)
        self.cfg.set("temperature", self.temp.value() / 100.0)
        self.cfg.set("tick_interval", self.tick.value())
        self.cfg.set("opacity", self.op_slider.value())
        self.cfg.set("scale", self.sc_slider.value())
        self.cfg.save()
        self.saved.emit()

    @staticmethod
    def _row(widget, label) -> QWidget:
        c = QWidget(); h = QHBoxLayout(c); h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(widget, 1); h.addWidget(label)
        return c
