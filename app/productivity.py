# -*- coding: utf-8 -*-
"""生产力助手：全局划词快捷键（选中文本后按快捷键，直接弹出快捷选项）。"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional, Tuple

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, pyqtSignal

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
KEYUP = 0x0002

IS_WIN = sys.platform == "win32"


def parse_hotkey(text: str) -> Tuple[int, int]:
    """'Ctrl+Alt+D' -> (mods, vk)。"""
    mods = MOD_NOREPEAT
    vk = 0
    parts = [p.strip().lower() for p in (text or "").split("+") if p.strip()]
    for p in parts:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif len(p) == 1:
            vk = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit():
            vk = 0x70 + int(p[1:]) - 1
    if not vk:
        vk = ord("D")
    return mods, vk


def register_hotkey(hotkey_id: int, mods: int, vk: int) -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.user32.RegisterHotKey(None, hotkey_id, mods, vk))
    except Exception:
        return False


def unregister_hotkey(hotkey_id: int) -> None:
    if not IS_WIN:
        return
    try:
        ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
    except Exception:
        pass


def copy_selection() -> None:
    """模拟 Ctrl+C，把当前选中的文本复制到剪贴板。"""
    if not IS_WIN:
        return
    try:
        u = ctypes.windll.user32
        VK_CONTROL, VK_C = 0x11, 0x43
        u.keybd_event(VK_CONTROL, 0, 0, 0)
        u.keybd_event(VK_C, 0, 0, 0)
        u.keybd_event(VK_C, 0, KEYUP, 0)
        u.keybd_event(VK_CONTROL, 0, KEYUP, 0)
    except Exception:
        pass


class HotkeyFilter(QObject, QAbstractNativeEventFilter):
    """Qt 原生事件过滤器，捕获 WM_HOTKEY。"""
    triggered = pyqtSignal()

    def __init__(self, hotkey_id: int = 0xA1F1) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self.hotkey_id = hotkey_id

    def nativeEventFilter(self, etype, message):
        try:
            if etype in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and int(msg.wParam) == self.hotkey_id:
                    self.triggered.emit()
                    return True, 0
        except Exception:
            pass
        return False, 0


class GlobalSelectionHotkey:
    """安装/卸载全局划词快捷键。"""

    def __init__(self, app, hotkey: str = "Ctrl+Alt+D") -> None:
        self.app = app
        self.hotkey = hotkey
        self.filter: Optional[HotkeyFilter] = None
        self.ok = False

    def install(self, callback) -> bool:
        if not IS_WIN:
            return False
        self.filter = HotkeyFilter()
        self.filter.triggered.connect(callback)
        try:
            self.app.installNativeEventFilter(self.filter)
        except Exception:
            pass
        mods, vk = parse_hotkey(self.hotkey)
        self.ok = register_hotkey(self.filter.hotkey_id, mods, vk)
        return self.ok

    def uninstall(self) -> None:
        if self.filter is not None:
            unregister_hotkey(self.filter.hotkey_id)
            try:
                self.app.removeNativeEventFilter(self.filter)
            except Exception:
                pass
        self.filter = None
        self.ok = False
