# -*- coding: utf-8 -*-
"""大肥鱼桌宠 · 入口文件。

用法：
    python run.py
或双击「启动大肥鱼.lnk」/「启动大肥鱼.bat」。
"""
import os
import sys

# 让脚本无论从哪里启动都能 import app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app import const
from app.const import ensure_dirs
from app.logging_setup import setup_logging

log = setup_logging()


def main() -> int:
    ensure_dirs()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(const.APP_NAME)
    qapp.setApplicationDisplayName(const.APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)

    # 强制浅色主题：避免系统深色模式导致白底输入框出现“白字看不见”
    try:
        from PyQt6.QtGui import QColor, QPalette
        qapp.setStyle("Fusion")
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#eef6ff"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#173a63"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f3f8ff"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#173a63"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#173a63"))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#173a63"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#9ccbf3"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#173a63"))
        qapp.setPalette(pal)
        from app.ui_theme import GLOBAL_QSS
        qapp.setStyleSheet(GLOBAL_QSS)
    except Exception:
        pass
    icon_path = os.path.join(const.ICON_DIR, "pet.ico")
    if os.path.exists(icon_path):
        qapp.setWindowIcon(QIcon(icon_path))

    from app.main import DafeiyuApp
    controller = DafeiyuApp(qapp)

    # 没有 Key 就先弹出设置（不阻塞桌宠本地兜底行为）
    if not controller.cfg.has_key() or not controller.cfg.get("key_verified", False):
        QTimer.singleShot(600, lambda: controller.open_settings("api"))

    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
