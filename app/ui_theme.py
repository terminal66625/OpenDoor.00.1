# -*- coding: utf-8 -*-
"""统一视觉设计系统：颜色、圆角、渐变、鲸鱼娘元素、全局样式表。

所有界面均引用这里的样式，保证风格一致、有设计感，且互不冲突。
"""
from __future__ import annotations

# 主色板（鲸鱼蓝 + 奶油白 + 傲娇粉）
PRIMARY = "#6fb2ea"
PRIMARY_DARK = "#2c5c92"
PRIMARY_LIGHT = "#a5d0f7"
BG_TOP = "#f6fbff"
BG_BOTTOM = "#e4f1ff"
CARD = "#ffffff"
CARD_BORDER = "#c3ddf7"
TEXT = "#173a63"
TEXT_SUB = "#8aa2bb"
ACCENT_PINK = "#ff9ec4"
ACCENT_MINT = "#8fe3c8"

FONT = "Microsoft YaHei"

# 全局（菜单/提示/滚动条）样式，装一次即可
GLOBAL_QSS = f"""
QMenu{{background:#f6fbff;border:1px solid {CARD_BORDER};border-radius:10px;padding:5px;}}
QMenu::item{{padding:7px 22px;border-radius:7px;color:#33507a;}}
QMenu::item:selected{{background:#d6e9ff;color:{TEXT};}}
QMenu::separator{{height:1px;background:#dce9f7;margin:4px 8px;}}
QToolTip{{background:#ffffff;color:{TEXT};border:1px solid {CARD_BORDER};
 border-radius:7px;padding:5px 9px;font-family:'{FONT}';}}
QScrollBar:vertical{{background:transparent;width:9px;margin:2px;}}
QScrollBar::handle:vertical{{background:#c9dcf2;border-radius:4px;min-height:26px;}}
QScrollBar::handle:vertical:hover{{background:#a9c8ea;}}
QScrollBar::add-line,QScrollBar::sub-line{{height:0;}}
QScrollBar:horizontal{{background:transparent;height:9px;margin:2px;}}
QScrollBar::handle:horizontal{{background:#c9dcf2;border-radius:4px;min-width:26px;}}
"""

# 对话框/面板统一样式（渐变底 + 圆角卡片 + 渐变按钮）
DIALOG_QSS = f"""
QDialog{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
 stop:0 {BG_TOP}, stop:1 {BG_BOTTOM});
 font-family:'{FONT}';font-size:13px;color:{TEXT};}}
QLabel{{color:#33608f;background:transparent;}}
QLabel#h1{{font-size:17px;font-weight:bold;color:{PRIMARY_DARK};}}
QLabel#sub{{color:{TEXT_SUB};font-size:12px;}}
QLabel#card{{background:rgba(255,255,255,0.85);border:1px solid {CARD_BORDER};
 border-radius:14px;padding:10px;}}
QListWidget{{background:rgba(255,255,255,0.78);border:1px solid #d6e8fa;border-radius:12px;
 padding:7px;color:#33608f;outline:none;}}
QListWidget::item{{padding:11px 12px;margin:2px 1px;border-radius:9px;}}
QListWidget::item:hover{{background:#e8f3ff;}}
QListWidget::item:selected{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
 stop:0 #bcdcff, stop:1 #d8ecff);color:{TEXT};}}
QLineEdit{{background:#ffffff;color:{TEXT};border:1px solid {CARD_BORDER};
 border-radius:9px;padding:6px 9px;selection-background-color:#9ccbf3;selection-color:{TEXT};}}
QLineEdit:focus{{border:1px solid {PRIMARY};}}
QComboBox{{background:#ffffff;color:{TEXT};border:1px solid {CARD_BORDER};
 border-radius:9px;padding:6px 9px;}}
QComboBox QAbstractItemView{{background:#ffffff;color:{TEXT};border:1px solid {CARD_BORDER};
 selection-background-color:#bcdcff;selection-color:{TEXT};outline:none;}}
QSpinBox{{background:#ffffff;color:{TEXT};border:1px solid {CARD_BORDER};
 border-radius:9px;padding:4px 6px;}}
QCheckBox{{color:#33608f;spacing:8px;}}
QPushButton{{border:none;border-radius:11px;padding:8px 14px;color:white;
 background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {PRIMARY_LIGHT}, stop:1 #86bdf0);}}
QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
 stop:0 #93c6f5, stop:1 {PRIMARY});}}
QPushButton:pressed{{background:#6aa8e0;}}
QPushButton#ghost{{background:#e6f1fd;color:#33608f;}}
QPushButton#ghost:hover{{background:#d3e7fb;}}
QSlider::groove:horizontal{{height:6px;background:#cfe2f7;border-radius:3px;}}
QSlider::handle:horizontal{{width:16px;margin:-6px 0;border-radius:8px;
 background:qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #9ccbf3, stop:1 {PRIMARY});}}
QTextBrowser{{background:#ffffff;color:{TEXT};border:1px solid {CARD_BORDER};
 border-radius:12px;padding:8px;}}
QProgressBar{{background:#e1eefc;border:none;border-radius:9px;height:18px;
 text-align:center;color:{PRIMARY_DARK};}}
QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
 stop:0 {PRIMARY_LIGHT}, stop:1 {ACCENT_PINK});border-radius:9px;}}
"""

# 傲娇鲸鱼娘台词池（用于界面点缀，避免生硬）
SUBTITLES = [
    "哼，本鱼才不是特意给你做的界面呢……随便用用吧。",
    "看什么看，本鱼只是顺便优化了一下而已！",
    "主人要是敢说不好看，本鱼就游走啦 (๑•̀ㅂ•́)و",
    "这可是本鱼熬夜（并没）做出来的，夸夸本鱼嘛~",
]

PLACEHOLDERS = [
    "和本鱼说点什么吧…（Tab 补全，↑↓ 翻历史）",
    "哼，主人才不会不理本鱼的对吧？",
    "想让本鱼做什么？（试试「帮我看看屏幕」）",
    "本鱼在听哦，快说快说~",
    "有问题尽管问，答不上来就……让主人去问 DeepSeek！",
]


def header(title: str, subtitle: str = "") -> str:
    sub = (f"<div style='color:{TEXT_SUB};font-size:12px;margin-top:3px;'>{subtitle}</div>"
           if subtitle else "")
    return (f"<div style='font-size:17px;font-weight:bold;color:{PRIMARY_DARK};'>"
            f"🐳 {title}</div>{sub}")


def random_subtitle() -> str:
    import random
    return random.choice(SUBTITLES)


def random_placeholder() -> str:
    import random
    return random.choice(PLACEHOLDERS)
