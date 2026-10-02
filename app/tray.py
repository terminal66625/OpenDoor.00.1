# -*- coding: utf-8 -*-
"""系统托盘图标与菜单。"""
import os

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from . import const

STYLE = """
QMenu{background:#f3f8ff;border:1px solid #bcd8f5;border-radius:8px;padding:4px;}
QMenu::item{padding:6px 22px;border-radius:6px;color:#33507a;}
QMenu::item:selected{background:#d6e9ff;color:#1b3a66;}
QMenu::separator{height:1px;background:#dce9f7;margin:4px 8px;}
"""


class Tray(QSystemTrayIcon):
    def __init__(self, app) -> None:
        icon_path = os.path.join(const.ICON_DIR, "pet.ico")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        super().__init__(icon, app)
        self.app_ctrl = app
        self.setToolTip("大肥鱼桌宠")
        self._build()

    def _build(self) -> None:
        m = QMenu()
        m.setStyleSheet(STYLE)
        m.addAction("显示/隐藏", self.app_ctrl.toggle_pet)
        m.addAction("和本鱼说话", self.app_ctrl.open_chat)
        m.addAction("让大肥鱼康康", self.app_ctrl.do_screenshot)
        m.addSeparator()
        m.addAction("设置", lambda: self.app_ctrl.open_settings("api"))
        m.addAction("暂停/继续", self.app_ctrl.toggle_pause)
        m.addSeparator()
        m.addAction("退出", self.app_ctrl.quit_app)
        self.setContextMenu(m)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.app_ctrl.toggle_pet()

    def set_offline(self, offline: bool) -> None:
        self.setToolTip("大肥鱼桌宠（离线模式）" if offline else "大肥鱼桌宠")
