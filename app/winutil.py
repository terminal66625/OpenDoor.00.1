# -*- coding: utf-8 -*-
"""Windows 平台工具：全屏检测、开机自启、创建快捷方式、音量。"""
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

from . import const
from .logging_setup import setup_logging

log = setup_logging()

IS_WIN = sys.platform == "win32"

if IS_WIN:
    user32 = ctypes.windll.user32
    RECT = wintypes.RECT


def get_foreground_rect_and_monitor():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    monitor = user32.MonitorFromWindow(hwnd, 2)  # NEAREST
    info = ctypes.c_ulong()
    return (rect, monitor, hwnd)


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def is_fullscreen() -> bool:
    """前景窗口是否铺满整块显示器（且不是桌面/本程序）。"""
    if not IS_WIN:
        return False
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        # 自己的窗口不判为全屏（通过进程 id 粗判）
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        mon = user32.MonitorFromWindow(hwnd, 2)
        if not mon:
            return False
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return False
        mr = info.rcMonitor
        full = (abs(rect.left - mr.left) < 3 and abs(rect.top - mr.top) < 3
                and abs(rect.right - mr.right) < 3 and abs(rect.bottom - mr.bottom) < 3)
        if not full:
            return False
        # 过滤桌面/任务栏
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        # 过滤最小化
        if user32.IsIconic(hwnd):
            return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 自启
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "大肥鱼桌宠"


def _launch_parts():
    """(可执行文件, 参数, 工作目录)。打包后=exe 自身；源码运行=pythonw + run.py。"""
    if getattr(sys, "frozen", False):
        return sys.executable, "", const.BASE_DIR
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pythonw if os.path.exists(pythonw) else sys.executable
    return exe, f'"{os.path.join(const.BASE_DIR, "run.py")}"', const.BASE_DIR


def _launch_command() -> str:
    exe, args, _ = _launch_parts()
    return f'"{exe}"' + (f" {args}" if args else "")


def set_autostart(enable: bool) -> bool:
    if not IS_WIN:
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        log.info("开机自启已%s", "开启" if enable else "关闭")
        return True
    except Exception as e:
        log.warning("设置开机自启失败：%s", e)
        return False


def _portable(p: str) -> str:
    """把用户目录替换成 %USERPROFILE%，整个文件夹搬到别的电脑也能用。"""
    if not p:
        return p
    try:
        import re
        up = os.path.expanduser("~")
        if up:
            return re.sub(re.escape(up), "%USERPROFILE%", p, flags=re.IGNORECASE)
    except Exception:
        pass
    return p


def create_shortcut() -> str:
    """在 大肥鱼 文件夹中生成/更新“启动大肥鱼.lnk”（用 %USERPROFILE% 保持可搬移）。"""
    if not IS_WIN:
        return ""
    lnk = os.path.join(const.BASE_DIR, "启动大肥鱼.lnk")
    target, args, workdir = _launch_parts()
    target = _portable(target)
    args = _portable(args)
    workdir = _portable(workdir)
    icon = _portable(os.path.join(const.ICON_DIR, "pet.ico"))
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{lnk}'); "
        f"$sc.TargetPath = '{target}'; "
        f"$sc.Arguments = '{args}'; "
        f"$sc.WorkingDirectory = '{workdir}'; "
        f"$sc.IconLocation = '{icon}'; "
        "$sc.Description = '启动大肥鱼桌宠'; "
        "$sc.Save()"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=20)
        if os.path.exists(lnk):
            log.info("已创建快捷方式：%s", lnk)
            return lnk
    except Exception as e:
        log.warning("创建快捷方式失败：%s", e)
    return ""


def ensure_shortcut() -> str:
    """快捷方式指向不对（例如整个文件夹搬到新电脑后）就自动重建。"""
    if not IS_WIN:
        return ""
    lnk = os.path.join(const.BASE_DIR, "启动大肥鱼.lnk")
    target, args, workdir = _launch_parts()
    sig = f"{_portable(target)}|{_portable(args)}|{_portable(workdir)}"
    sig_path = os.path.join(const.MEMORY_DIR, "launcher.sig")
    try:
        old = open(sig_path, "r", encoding="utf-8").read().strip()
    except OSError:
        old = ""
    if os.path.exists(lnk) and old == sig:
        return lnk
    made = create_shortcut()
    if made:
        try:
            os.makedirs(const.MEMORY_DIR, exist_ok=True)
            with open(sig_path, "w", encoding="utf-8") as f:
                f.write(sig)
        except OSError as e:
            log.warning("写入快捷方式签名失败：%s", e)
    return made


# ---------------------------------------------------------------- 自动关文档窗口
WM_CLOSE = 0x0010


def close_documents_windows() -> int:
    """关闭标题为「文档 / Documents」的资源管理器窗口，返回关闭数量。

    用于对付 Windows 开机自动还原文件夹窗口的问题。
    """
    if not IS_WIN:
        return 0
    closed = 0
    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, lparam):
            nonlocal closed
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                if cls.value != "CabinetWClass":     # 资源管理器文件夹窗口
                    return True
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                title = buf.value
                if ("文档" in title) or ("Documents" in title):
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                    closed += 1
            except Exception:
                pass
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
    except Exception:
        pass
    if closed:
        log.info("已自动关闭 %d 个「文档」窗口", closed)
    return closed


# ---------------------------------------------------------------- 音量
def volume_step(up: bool) -> bool:
    """通过模拟媒体按键调节系统音量（无需额外依赖）。"""
    if not IS_WIN:
        return False
    try:
        VK_VOLUME_UP, VK_VOLUME_DOWN = 0xAF, 0xAE
        vk = VK_VOLUME_UP if up else VK_VOLUME_DOWN
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 亮度
def get_brightness():
    """返回当前亮度(0~100)，不支持则 None。"""
    if not IS_WIN:
        return None
    ps = ("(Get-CimInstance -Namespace root/WMI -ClassName "
          "WmiMonitorBrightness).CurrentBrightness")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=15)
        val = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        return int(val) if val.isdigit() else None
    except Exception:
        return None


def set_brightness(value: int) -> bool:
    """设置亮度；台式显示器通常不支持，返回 False。"""
    if not IS_WIN:
        return False
    value = max(0, min(100, int(value)))
    ps = (f"(Get-CimInstance -Namespace root/WMI -ClassName "
          f"WmiMonitorBrightnessMethods).WmiSetBrightness(1,{value})")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=15)
        return get_brightness() is not None
    except Exception:
        return False


def brightness_step(delta: int):
    cur = get_brightness()
    if cur is None:
        return None
    new = max(0, min(100, cur + delta))
    set_brightness(new)
    return new


def open_folder(path: str) -> None:
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        pass
