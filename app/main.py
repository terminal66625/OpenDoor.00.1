# -*- coding: utf-8 -*-
"""大肥鱼桌宠主控制器：串联窗口、对话、LLM、定时、设置。"""
from __future__ import annotations
import ctypes
import json
import math
import os
import random
import time
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import const
from . import actions as actions_mod
from . import movies as movies_mod
from .action_overlay import ActionOverlay
from .assets import first_run_setup
from .behavior import PetState
from .chat_panel import ChatPanel
from .clipboard import ClipboardBar, ClipboardWatcher
from .affinity import Affinity
from .config import Config
from .growth_dialog import GrowthDialog
from .llm import LLMClient
from .productivity import GlobalSelectionHotkey, copy_selection
from .quick_menu import RadialMenu
from .snippets import SnippetStore, SnippetsDialog, prompt_and_add
from .logging_setup import setup_logging
from .memory import Memory
from .persona import RESPONSIBILITY, SCREEN_SYSTEM_FULL, behavior_prompt, chat_system
from .pet_window import PetWindow
from .scheduler import Scheduler
from .screenshot import grab_screen, pixmap_to_data_url
from .settings_dialog import SettingsDialog
from .stickers import StickerLibrary
from .tray import Tray
from .util import mask_key
from .winutil import (brightness_step, ensure_shortcut, set_autostart,
                      volume_step)

log = setup_logging()


@dataclass
class Context:
    cfg: Config
    memory: Memory
    stickers: StickerLibrary
    llm: LLMClient


# 无聊/好奇/想吃/犯困/傲娇 五类自言自语
IDLE_TALK = {
    "无聊": [
        ("好无聊呀……尾巴甩来甩去都没事干 (˘•ω•˘)", "无聊", "look_around"),
        ("（晃尾鳍）主人怎么还不理我嘛", "无聊", "idle_stand"),
        ("发呆ing……数鳞片玩好了 (￣▽￣)", "无聊", "sniff"),
        ("唔……没人陪我玩就自己吐泡泡 ○", "无聊", "idle_sit"),
        ("好闲啊，要不要去扒拉一下主人的鼠标呢", "无聊", "crawl_right"),
    ],
    "好奇": [
        ("主人在噼里啪啦敲什么呀？让本鱼康康 (｀・ω・´)", "不知道", "look_up"),
        ("屏幕上花花绿绿的，是在做好玩的事吗", "不理解主人在干嘛", "look_around"),
        ("忙不忙呀？要不要本鱼搭把手？", "思考", "look_up"),
        ("盯——主人你看屏幕好久了哦", "严肃", "idle_stand"),
        ("这行代码是什么意思呀，看起来好难", "不知道", "idle_sit"),
    ],
    "想吃": [
        ("肚子咕咕叫……想吃大白饭 (´;ω;`)", "要大白饭", "sniff"),
        ("今天的 token 还没囤呢，主人别忘了~", "要TOKEN", "look_up"),
        ("要是现在有一碗热乎大白饭就好了呜", "要大白饭", "idle_sit"),
        ("囤token囤token，囤够了就能换小零食！", "TOKEN好吃", "jump"),
        ("（摸肚子）好像……又饿了", "要大白饭", "idle_stand"),
    ],
    "犯困": [
        ("好困……（打哈欠）就眯一小会儿哦 (๑ᵕ⌓ᵕ)", "困", "idle_sleep"),
        ("眼皮好重……呼……呼……", "困", "idle_sleep"),
        ("懒洋洋的不想动……就趴在这儿歇会儿", "偷懒", "idle_sit"),
        ("好暖和啊……想睡觉", "困", "idle_sleep"),
        ("再睡一分钟……就一分钟……", "困", "idle_sleep"),
    ],
    "傲娇": [
        ("我、我才没有在等你说话哦 (｡•ˇ‸ˇ•｡)", "生气", "idle_stand"),
        ("哼，再不理我我就自己游去玩啦", "生气", "crawl_left"),
        ("才不是无聊呢，就是……随便看看", "无语", "look_around"),
        ("我才不饿！就是……饭点快到了而已", "生气", "idle_sit"),
        ("谁要你陪啊，我自己玩也挺开心的……", "严肃", "idle_stand"),
    ],
}


class DafeiyuApp(QObject):
    movies_built = pyqtSignal()

    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self.qapp = qapp
        self.cfg = Config()

        # 首启资源处理（一次性）
        first_run_setup()
        self.memory = Memory()
        self._ensure_history_memory()
        self.stickers = StickerLibrary()
        self.llm = LLMClient(self.cfg)
        self.llm.start()
        self.ctx = Context(self.cfg, self.memory, self.stickers, self.llm)

        self.offline = not self.cfg.has_key()
        self._last_behavior = time.time()
        self._settings: SettingsDialog | None = None
        self._info = None
        self._petched_autostart()

        # 窗口
        self.pet = PetWindow(self.ctx)
        self.chat = ChatPanel(self.stickers, theme=self.cfg.get("theme"))
        self.clip_watcher = ClipboardWatcher(lambda: self.cfg.get("clipboard_helper", True))
        self.clip_bar = ClipboardBar()
        self.tray = Tray(self)
        self.tray.show()
        self.tray.set_offline(self.offline)
        self.scheduler = Scheduler(self.cfg, self.memory)

        # 动作行为参考库：读缓存，后台构建/识别（不阻塞启动）
        self.actions = actions_mod.ActionLibrary()
        self.action_overlay = ActionOverlay()
        # 延迟到窗口显示后再后台构建/识别，避免拖慢启动
        QTimer.singleShot(1500, self._start_action_bg)
        self.action_timer = QTimer(self)
        self.action_timer.setSingleShot(True)
        self.action_timer.timeout.connect(self._random_action)
        self._schedule_action()

        # 动作视频：后台预处理（首启/文件变更时），完成后刷新
        self.movies_built.connect(self.pet.reload_movies)
        QTimer.singleShot(3500, self._start_movies_bg)
        self._recent_movies: list = []
        self._last_interaction = time.time()
        self._last_idle_movie = time.time()
        self._idle_movie_timer = QTimer(self)
        self._idle_movie_timer.timeout.connect(self._check_idle_movie)
        self._idle_movie_timer.start(5000)

        # 好感养成 / 代码收藏 / 半圆快捷面板 / 全局划词快捷键
        self.affinity = Affinity()
        self.snippets = SnippetStore()
        self.focus_mode = False
        self.radial = RadialMenu()
        self.radial.action.connect(self._on_radial_action)
        self._recent_actions: list = []      # 最近两次互动动作（避免重复）
        self._growth = None
        self._snippets_dlg = None
        self.hotkey = GlobalSelectionHotkey(self.qapp, self.cfg.get("hotkey", "Ctrl+Alt+D"))
        if not self.hotkey.install(self._on_selection_hotkey):
            log.info("全局划词快捷键未生效（可能被占用）")
        self._vitality_timer = QTimer(self)
        self._vitality_timer.timeout.connect(self._vitality_tick)
        self._vitality_timer.start(60000)

        # 开机后持续检查并自动关闭被 Windows 还原出来的「文档」窗口
        if self.cfg.get("close_documents", True):
            self._doc_timer = QTimer(self)
            self._doc_timer.timeout.connect(self._close_documents_once)
            self._doc_timer.start(7000)          # 首次 7 秒，之后每 20 秒一次
        else:
            self._doc_timer = None

        # 诊断：记录是谁打开了「文档」窗口（查清后可关掉 boot_watch_debug）
        if self.cfg.get("boot_watch_debug", True):
            QTimer.singleShot(2500, self._start_boot_watch)

        self._wire()
        self.pet.show()

        # 行为循环（向模型要决策）
        self.behavior_timer = QTimer(self)
        self.behavior_timer.timeout.connect(self._behavior_tick)
        self.behavior_timer.start(self.cfg.get("tick_interval", 2) * 1000)

        # 自言自语循环
        self.talk_timer = QTimer(self)
        self.talk_timer.setSingleShot(True)
        self.talk_timer.timeout.connect(self._idle_talk)
        self._schedule_talk()

        # 问候
        QTimer.singleShot(1200, self._greet)

        self.chat.load_history(self.memory.recent(30))
        log.info("大肥鱼启动完成；模型=%s，Key=%s", self.cfg.model, mask_key(self.cfg.api_key))

    # ------------------------------------------------------------ 连接
    def _wire(self) -> None:
        self.llm.verified.connect(self._on_verified)
        self.llm.behavior_ready.connect(self.pet.on_behavior)
        self.llm.chat_delta.connect(self.chat.append_delta)
        self.llm.chat_done.connect(self._on_chat_done)
        self.llm.chat_failed.connect(self._on_chat_failed)
        self.llm.balance_ready.connect(self._on_balance)
        self.llm.balance_failed.connect(self._on_balance_failed)
        self.llm.failures.connect(self._on_failures)

        self.pet.clicked.connect(self._on_pet_clicked)
        self.pet.request_chat.connect(self.open_chat)
        self.pet.request_settings.connect(self.open_settings)
        self.pet.request_screenshot.connect(self.do_screenshot)
        self.pet.request_balance.connect(self._on_pet_clicked)
        self.pet.quick_action.connect(self._on_quick_action)
        self.pet.moved.connect(self._on_pet_moved)
        self.pet.radial_menu_requested.connect(self._show_radial)
        self.pet.say.connect(self._pet_say)

        self.chat.send_message.connect(self._on_user_message)
        self.chat.request_screenshot.connect(self.do_screenshot)
        self.chat.save_code.connect(self._save_chat_code)

        self.clip_watcher.copied.connect(self._on_clipboard)
        self.clip_bar.action.connect(self._on_clip_action)

        self.scheduler.notify.connect(self._on_notify)
        self.scheduler.request_compress.connect(self.compress_context)
        self.scheduler.alarm_fired.connect(lambda a: self.pet.show_bubble(
            f"⏰ {a.get('label', '闹钟')}！", 6))

    def _ensure_history_memory(self) -> None:
        """若已 OCR 的历史转写存在但记忆未写入，则补写（重启只读记忆）。"""
        try:
            if self.memory.profile.get("history_ingested"):
                return
            if os.path.isdir(const.TRANSCRIPT_DIR) and os.listdir(const.TRANSCRIPT_DIR):
                from .chat_ingest import apply_curated_memory
                apply_curated_memory()
                self.memory = Memory()
        except Exception as e:
            log.info("历史记忆补写跳过：%s", e)

    def _petched_autostart(self) -> None:
        try:
            if self.cfg.get("auto_start", True):
                set_autostart(True)
                # 文件夹搬到新电脑/换了路径时，自动修复快捷方式指向
                ensure_shortcut()
        except Exception as e:
            log.info("自启设置跳过：%s", e)

    # ------------------------------------------------------------ 行为
    def _behavior_tick(self) -> None:
        if self.offline or not self.cfg.has_key():
            return
        now = time.time()
        delta_ms = int((now - self._last_behavior) * 1000)
        self._last_behavior = now
        left, right, top, bottom = self.pet._bounds()
        cx, cy = self.pet.center_on_screen()
        gp = self.pet.cursor().pos()
        prompt = behavior_prompt(
            screenWidth=right - left, screenHeight=bottom - top,
            safeLeft=left, safeRight=right, safeTop=top, safeBottom=bottom,
            currentX=cx, currentY=cy, deltaMs=delta_ms,
            mouseX=gp.x(), mouseY=gp.y(),
            mouseDist=int(math.hypot(gp.x() - cx, gp.y() - cy)),
            timestamp=int(now), lastMemory=self.memory.memory_digest(),
        )
        self.llm.request_behavior(prompt)

    def _on_failures(self, count: int, reason: str) -> None:
        if count >= 3 and not self.offline:
            self.offline = True
            self.tray.set_offline(True)
            self.pet.show_bubble("网络好像不通…本鱼先自己玩啦", 5)
            log.warning("连续失败 %d 次，切换离线兜底：%s", count, reason)

    # ------------------------------------------------------------ 聊天
    def _on_user_message(self, text: str) -> None:
        self._last_interaction = time.time()
        self.chat.add_user(text)
        self.memory.add_message("user", text)
        try:
            self.affinity.record_message()
            self.affinity.add_usage(1)
            self.pet.vitality_factor = self.affinity.speed_factor()
        except Exception:
            pass
        # 学习简短习惯
        if any(k in text for k in ("我喜欢", "我习惯", "我叫", "我是")):
            self.memory.learn_habit(text[:40])
        if not self.cfg.has_key():
            self.chat.add_system("本鱼还没有钥匙(API Key)呢，主人去右上角设置里给本鱼填一下吧~ (๑•́ ₃ •̀๑)")
            return
        msgs = [{"role": "system", "content": chat_system(self.memory.memory_digest())}]
        msgs += self.memory.context_messages()
        self.chat.begin_stream()
        self.llm.chat(msgs)

    def _on_chat_done(self, text: str, keyword: str) -> None:
        sticker = self.stickers.pick(keyword, text)
        self.chat.end_stream(text, sticker)
        self.memory.add_message("assistant", text,
                                os.path.basename(sticker) if sticker else None)
        self.offline = False
        self.tray.set_offline(False)
        # 文字驱动的行为：命中情绪时做动作
        self._react_action(keyword or text)

    def _on_chat_failed(self, msg: str) -> None:
        self.chat.end_stream(f"呜…{msg}", self.stickers.pick("不知道", msg))

    # ------------------------------------------------------------ 截图
    def do_screenshot(self) -> None:
        """「让大肥鱼康康」：直接全屏截图（无需手动框选）。"""
        # 先藏起桌宠与浮窗，避免把自己拍进去，再截全屏
        self._shot_hidden = []
        for w in (self.pet, self.chat, self.clip_bar, self.action_overlay):
            try:
                if w is not None and w.isVisible():
                    self._shot_hidden.append(w)
                    w.hide()
            except Exception:
                pass
        QTimer.singleShot(260, self._finish_screenshot)

    def _finish_screenshot(self) -> None:
        try:
            self._on_captured(grab_screen())
        except Exception as e:
            log.info("截图失败：%s", e)
        finally:
            for w in getattr(self, "_shot_hidden", []):
                try:
                    w.show()
                except Exception:
                    pass
            self._shot_hidden = []

    def _on_captured(self, pixmap) -> None:
        self.open_chat()
        data_url = pixmap_to_data_url(pixmap)
        if not data_url:
            return
        self.chat.add_user("（让大肥鱼康康屏幕）")
        self.chat.begin_stream()
        if not self.cfg.has_key():
            self.chat.end_stream("本鱼的眼睛需要钥匙才能睁开哦~ 先去设置里填 API Key 吧", None)
            return
        self.llm.see_screen(data_url, SCREEN_SYSTEM_FULL)

    # ------------------------------------------------------------ 余额/信息
    def _on_pet_clicked(self) -> None:
        """点击桌宠：只冒一句小气泡，不再弹大卡片。"""
        self._last_interaction = time.time()
        try:
            self.affinity.record_interaction()
        except Exception:
            pass
        if not self.cfg.has_key():
            self.pet.show_bubble("本鱼还没填 API Key 呢~ (๑•́ ₃ •̀๑)", 3)
            return
        self.pet.show_bubble("本鱼去数数小金库…", 2.5)
        self.llm.query_balance()

    def _on_balance(self, data: dict) -> None:
        try:
            infos = data.get("balance_infos", [])
            parts = []
            for bi in infos:
                parts.append(f"{bi.get('currency', 'CNY')} {bi.get('total_balance', '?')}")
            text = "；".join(parts) or "余额信息为空"
        except Exception:
            text = "余额读取失败"
        self._balance_text = text
        self.pet.show_bubble(f"小金库：{text}", 4)
        self._refresh_info_page(loading=False)

    def _on_balance_failed(self, msg: str) -> None:
        self._balance_text = f"查询失败：{msg}"
        self.pet.show_bubble("查不到余额啦…可能没联网 (´･_･`)", 3)
        self._refresh_info_page(loading=False)

    def _info_html(self, loading: bool = False) -> str:
        def row(k, v):
            return (f"<tr><td style='color:#7a93ad;padding:3px 12px 3px 0;'>{k}</td>"
                    f"<td style='color:#173a63;'>{v}</td></tr>")
        if loading:
            bal = "查询中…"
        else:
            bal = getattr(self, "_balance_text", "未查询")
        rows = [
            row("模型", self.cfg.model),
            row("思考强度", self.cfg.get("reasoning", "low")),
            row("透明度 / 大小", f"{self.cfg.opacity} / {self.cfg.scale}"),
            row("网络", "离线兜底" if self.offline else "在线"),
            row("心情", self.memory.behavior.get("last", "")),
            row("Token 余额", bal),
        ]
        habits = self.memory.profile.get("master_habits", [])
        if habits:
            rows.append(row("主人习惯", "、".join(habits[-3:])))
        return ("<div style=\"font-family:'Microsoft YaHei';\">"
                "<table cellspacing='0' cellpadding='0'>" + "".join(rows) + "</table></div>")

    def _refresh_info_page(self, loading: bool = True) -> None:
        if self._settings is None:
            return
        self._settings.set_info_html(self._info_html(loading=loading))
        if loading and self.cfg.has_key():
            self.llm.query_balance()

    # ------------------------------------------------------------ 设置
    def open_settings(self, page: str = "api") -> None:
        if page == "growth":
            self.open_growth(); return
        if page == "snippets":
            self.open_snippets(); return
        if self._settings is None:
            self._settings = SettingsDialog(self.cfg, self.scheduler)
            self._settings.test_requested.connect(self._on_test)
            self._settings.saved.connect(self._on_settings_saved)
            self._settings.compress_now.connect(self.compress_context)
            self._settings.invisible.connect(self.quit_app)
            self._settings.delete_memory.connect(self._on_delete_memory)
            self._settings.theme_changed.connect(self.chat.apply_theme)
            self._settings.character_switch.connect(self.pet.set_character)
            self._settings.info_refresh.connect(self._refresh_info_page)
            self.llm.verified.connect(self._settings.set_test_result)
        if page == "info":
            self._refresh_info_page(loading=True)
        self._settings.show_page(page)
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()
        # 居中到屏幕，防止出现在屏幕外
        try:
            scr = QApplication.primaryScreen().availableGeometry()
            fg = self._settings.frameGeometry()
            fg.moveCenter(scr.center())
            self._settings.move(fg.topLeft())
        except Exception:
            pass

    def _on_test(self, api_key: str) -> None:
        self.cfg.set("base_url", const.DEFAULT_BASE_URL)
        if api_key:
            self.cfg.api_key = api_key
        self.cfg.save()
        self._settings.set_test_result(True, "正在测试…")
        self.llm.verify()

    def _on_verified(self, ok: bool, msg: str) -> None:
        self.cfg.mark_verified(ok)
        if ok:
            self.offline = False
            self.tray.set_offline(False)
        else:
            self.offline = True
            self.tray.set_offline(True)

    def _on_settings_saved(self) -> None:
        self.pet._apply_opacity()
        self.pet.apply_volume()
        try:
            s = getattr(self.scheduler, "_sound", None)
            if s is not None:
                s.setVolume(max(0.0, min(1.0,
                    float(self.cfg.get("action_volume", 70)) / 100.0)))
        except Exception:
            pass
        self.behavior_timer.setInterval(int(self.cfg.get("tick_interval", 2)) * 1000)
        try:
            set_autostart(bool(self.cfg.get("auto_start", True)))
        except Exception:
            pass

    # ------------------------------------------------------------ 快捷工具
    def _on_quick_action(self, key: str) -> None:
        if key == "vol_up":
            volume_step(True); self.pet.show_bubble("音量 + ~ (๑•̀ㅂ•́)و", 2)
        elif key == "vol_down":
            volume_step(False); self.pet.show_bubble("音量 − ~", 2)
        elif key == "bri_up":
            v = brightness_step(10)
            self.pet.show_bubble(f"亮度 {v}%" if v is not None else "这个屏幕本鱼调不了亮度啦 (´･_･`)", 2.5)
        elif key == "bri_down":
            v = brightness_step(-10)
            self.pet.show_bubble(f"亮度 {v}%" if v is not None else "这个屏幕本鱼调不了亮度啦 (´･_･`)", 2.5)
        elif key == "todos":
            self.open_settings("todos")

    # ------------------------------------------------------------ 关文档窗口
    def _close_documents_once(self) -> None:
        try:
            from .winutil import close_documents_windows
            close_documents_windows()
        except Exception:
            pass
        if self._doc_timer is not None and self._doc_timer.interval() != 20000:
            self._doc_timer.setInterval(20000)

    def _start_boot_watch(self) -> None:
        """诊断用：后台记录新进程与资源管理器窗口，找出「文档」窗口的打开者。"""
        import subprocess
        lock = os.path.join(const.LOG_DIR, "boot_watch.pid")
        try:
            if os.path.exists(lock):
                with open(lock, "r", encoding="ascii", errors="ignore") as f:
                    pid = int((f.read() or "0").strip() or 0)
                if pid > 0:
                    k32 = ctypes.windll.kernel32
                    h = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
                    if h:
                        k32.CloseHandle(h)
                        return                                 # 已有监视器在跑
        except Exception:
            pass
        script = os.path.join(const.BASE_DIR, "tools", "boot_watch.ps1")
        if not os.path.exists(script):
            return
        try:
            with open(os.path.join(const.LOG_DIR, "boot_watch.log"), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} === 大肥鱼启动，开始查找「文档」窗口的打开者 ===\n")
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                creationflags=0x08000000,                     # CREATE_NO_WINDOW
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            log.info("已启动「文档」窗口来源监视（20 分钟）")
        except Exception as e:
            log.warning("启动窗口监视失败：%s", e)

    # ------------------------------------------------------------ 浮窗跟随
    def _on_pet_moved(self, dx: int, dy: int) -> None:
        """桌宠移动时，对话框等浮窗一起移动（连在一起）。"""
        for w in (self.chat, self.clip_bar, self.action_overlay):
            try:
                if w is not None and w.isVisible() and not w.isMinimized():
                    w.move(w.x() + dx, w.y() + dy)
            except Exception:
                pass

    # ------------------------------------------------------------ 快捷面板
    def _show_radial(self, pos) -> None:
        try:
            self.radial.show_at(pos.x(), self.pet.y())
        except Exception:
            pass

    def _on_radial_action(self, key: str) -> None:
        self._last_interaction = time.time()
        if key == "vision":
            self.do_screenshot()
        elif key == "clip":
            self._radial_clip()
        elif key == "clear":
            self._clear_session()
        elif key == "mode":
            self._toggle_mode()
        elif key == "hide":
            # 隐藏 = 彻底停止：停掉所有动画/计时器并退出进程
            self.pet.show_bubble("本鱼先藏起来啦，想本鱼就再启动哦~", 0.8)
            QTimer.singleShot(700, self.quit_app)
        elif key == "feed":
            self.feed_rice()
        elif key == "store":
            self.store_tokens()
        elif key == "more":
            from PyQt6.QtGui import QCursor
            self.pet.show_context_menu(QCursor.pos())

    def _radial_clip(self) -> None:
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if not text:
            self.pet.show_bubble("剪贴板空空的，先复制点东西吧~", 3)
            return
        cx, _ = self.pet.center_on_screen()
        self.clip_bar.popup_near(cx, self.pet.y(), text)

    def _clear_session(self) -> None:
        self.chat.clear()
        self.memory.history = []
        self.memory.save_history()
        self.pet.show_bubble("会话清空啦，重新开始吧~ (๑•̀ㅂ•́)و", 3)

    def _toggle_mode(self) -> None:
        self.focus_mode = not self.focus_mode
        if self.focus_mode:
            self.talk_timer.stop()
            self.pet.show_bubble("专注模式：本鱼安静陪着你 (｡•ᴗ•｡)", 3)
        else:
            self._schedule_talk()
            self.pet.show_bubble("聊天模式：本鱼回来啦！", 3)

    # ------------------------------------------------------------ 养成
    # 互动动作池（可随时替换/新增类似动作）
    FEED_POOL = ["拿到米饭了，开心", "要吃大白饭和TOKEN", "开心", "送主人礼物"]
    STORE_POOL = ["拿到TOKEN了，真好吃", "偷拿TOKEN", "自夸", "偷TOKEN被抓了"]

    def _pick_interaction_action(self, pool) -> Optional[str]:
        """从池中挑一个与前两次互动动作不重合的（找不到就宽松处理）。"""
        cands = [p for p in pool if p not in self._recent_actions]
        if not cands:
            cands = [p for p in pool]
        name = random.choice(cands) if cands else None
        if name:
            self._recent_actions.append(name)
            self._recent_actions = self._recent_actions[-2:]
        return name

    def feed_rice(self) -> None:
        self._last_interaction = time.time()
        count = self.affinity.feed()
        if count is None:
            self.pet.show_bubble("呜…大白饭暂时喂不了呢 (´;ω;`)", 4)
            return
        if not self.pet.play_movie("开心"):
            self.pet._force_clip("click")
            self._play_action_by_name(self._pick_interaction_action(self.FEED_POOL))
        self.pet.show_bubble(f"呜姆！大白饭真好吃~ 今天第 {count} 碗 🍚", 4)
        self.pet.vitality_factor = self.affinity.speed_factor()
        self._toast_achievements()
        if self._growth:
            self._growth.refresh()

    def store_tokens(self) -> None:
        self._last_interaction = time.time()
        n, ach = self.affinity.store_tokens()
        if n <= 0:
            self.pet.show_bubble("呜…这次没囤到 token，再点一次试试~", 4)
            return
        if not self.pet.play_movie("开心"):
            self.pet._force_clip("click")
            self._play_action_by_name(self._pick_interaction_action(self.STORE_POOL))
        self.pet.show_bubble(f"囤进小金库 {n} 枚 token！本鱼越来越富啦 🪙", 4)
        self._toast_achievements(ach)
        if self._growth:
            self._growth.refresh()

    def _toast_achievements(self, ach=None) -> None:
        for a in (ach or []):
            self.pet.show_bubble(f"🎖 解锁成就：{a}！", 4.5)
            self.chat.add_system(f"（解锁成就：{a}）")

    def _vitality_tick(self) -> None:
        self.affinity.vitality_tick(1.0)
        self.pet.vitality_factor = self.affinity.speed_factor()
        if self.affinity.is_tired() and random.random() < 0.15:
            self.pet.show_bubble("肚子饿了…活力好低，本鱼蔫了 (ᵕ̣̣̣̣̣̣﹏ᵕ̣̣̣̣̣̣)", 4)

    def _play_action_by_name(self, name: str) -> None:
        item = self.actions.by_name(name)
        if item:
            self._play_action(item, name)

    # ------------------------------------------------------------ 收藏代码
    def _save_chat_code(self, code: str, lang: str) -> None:
        if prompt_and_add(self.snippets, code, lang, parent=self._snippets_dlg):
            self.pet.show_bubble("代码收进本鱼的小库房啦~ 📚", 3)

    def open_snippets(self) -> None:
        if self._snippets_dlg is None:
            self._snippets_dlg = SnippetsDialog(self.snippets)
        self._snippets_dlg.show()
        self._snippets_dlg.raise_()
        self._snippets_dlg._refresh()

    def open_growth(self) -> None:
        if self._growth is None:
            self._growth = GrowthDialog(self.affinity)
            self._growth.feed_requested.connect(self.feed_rice)
            self._growth.store_requested.connect(self.store_tokens)
        self._growth.refresh()
        self._growth.show()
        self._growth.raise_()
        self._growth.activateWindow()

    # ------------------------------------------------------------ 划词召唤
    def _on_selection_hotkey(self) -> None:
        copy_selection()
        QTimer.singleShot(220, self._after_selection_copy)

    def _after_selection_copy(self) -> None:
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if not text:
            self.pet.show_bubble("没有选中文字哦~ 先选中再按快捷键", 3)
            return
        pos = QCursor.pos()
        self.clip_bar.popup_near(pos.x(), pos.y(), text)

    # ------------------------------------------------------------ 剪贴板助手
    def _on_clipboard(self, text: str) -> None:
        if self.pet._fullscreen and self.cfg.get("mute_fullscreen", True):
            return
        cx, cy = self.pet.center_on_screen()
        self.clip_bar.popup_near(cx, cy, text)

    def _on_clip_action(self, action: str, text: str) -> None:
        self.open_chat()
        snippet = text[:60] + ("..." if len(text) > 60 else "")
        self.chat.add_user(f"【{action}】{snippet}")
        self.memory.add_message("user", f"【{action}】{text[:120]}")
        instr = {
            "解读": "用大肥鱼的语气，通俗地给主人解读下面这段内容，简短一点：",
            "润色": "帮主人把下面这段话润色得更通顺自然，保留原意：",
            "查错": "帮主人看看下面这段内容有没有错误，简短指出就好：",
            "翻译": "把下面的内容翻译一下（中文译英文，英文译中文）：",
        }.get(action, "看看下面这段：")
        self.chat.begin_stream()
        if not self.cfg.has_key():
            self.chat.end_stream("本鱼还没有钥匙(API Key)呢~ 先去设置里填一下吧", None)
            return
        msgs = [{"role": "system",
                 "content": chat_system(self.memory.memory_digest()) + "\n" + instr},
                {"role": "user", "content": text[:1500]}]
        self.llm.chat(msgs)

    def compress_context(self) -> None:
        self.memory.compress()
        self.pet.show_bubble("本鱼把记忆压缩啦，脑袋清清爽爽~ (๑•̀ㅂ•́)و", 4)

    def _on_delete_memory(self) -> None:
        from .assets import bootstrap_memory
        self.memory.wipe()
        bootstrap_memory(force=True)
        try:
            if os.path.isdir(const.TRANSCRIPT_DIR) and os.listdir(const.TRANSCRIPT_DIR):
                from .chat_ingest import apply_curated_memory
                apply_curated_memory()
        except Exception:
            pass
        self.memory = Memory()
        self.ctx.memory = self.memory
        self.chat.clear()

    # ------------------------------------------------------------ 通知/自言自语
    def _on_notify(self, text: str, keyword: str) -> None:
        sticker = self.stickers.pick(keyword, text)
        self.chat.add_system(text, sticker)
        self.memory.add_message("assistant", text,
                                os.path.basename(sticker) if sticker else None)
        self.pet.show_bubble(text, 6)
        self._react_action(keyword)
        self._show_unread()

    def _schedule_talk(self) -> None:
        lo, hi = self.cfg.get("idle_talk_interval", [5, 10])
        self.talk_timer.start(random.randint(int(lo * 60), int(hi * 60)) * 1000)

    def _idle_talk(self) -> None:
        try:
            if self.focus_mode or self.pet.movie_active:
                return
            if not self.pet._fullscreen:
                category = random.choice(list(IDLE_TALK.keys()))
                text, keyword, action = random.choice(IDLE_TALK[category])
                sticker = self.stickers.pick(keyword, text)
                self.chat.add_system(text, sticker)
                self.memory.add_message("assistant", text,
                                        os.path.basename(sticker) if sticker else None)
                self.pet.show_bubble(text, 6)
                self.pet.say.emit(text, keyword)
                # 做出相应动作
                self.pet.state = PetState(action=action if action in RESPONSIBILITY
                                          else "idle_stand", heading=self.pet.heading,
                                          speed=0.6, remaining=RESPONSIBILITY.get(action, (10, 20))[0],
                                          memory=category)
                self.pet.target_heading = self.pet.state.heading
                self._show_unread()
        finally:
            self._schedule_talk()

    def _show_unread(self) -> None:
        if not self.chat.isVisible():
            self.pet.show_bubble("有新消息哦~ 点本鱼看看 (๑•̀ㅂ•́)و", 3)

    # ------------------------------------------------------------ 动作反应
    # 语境命中时，让「桌宠本体」做动作（不再在桌面单独贴一张表情图片）
    MOTION_HINTS = [
        ("吃", "sniff"), ("饭", "sniff"), ("TOKEN", "jump"), ("token", "jump"),
        ("开心", "jump"), ("耶", "jump"), ("夸", "jump"), ("蹦", "jump"),
        ("礼物", "jump"), ("跳舞", "jump"), ("你好", "look_up"),
        ("生气", "look_around"), ("哼", "look_around"),
        ("困", "idle_sleep"), ("睡", "idle_sleep"), ("懒", "idle_sit"),
    ]

    def _react_action(self, text: str) -> None:
        if not text:
            return
        # 1) 语境命中「动作行为参考」里带文字的动作 → 播放该动作并显示文字
        if self.cfg.get("use_action_refs", True):
            item = self.actions.match_text(text)
            if item:
                self._play_action(item, item.get("name"))
                return
        # 2) 否则让桌宠本体做个动作
        from .behavior import PetState
        for key, act in self.MOTION_HINTS:
            if key in text:
                lo = RESPONSIBILITY.get(act, (10, 20))[0]
                self.pet.state = PetState(action=act, heading=self.pet.heading,
                                          speed=0.7, remaining=lo, memory=text[:20])
                self.pet.target_heading = self.pet.heading
                break

    # ------------------------------------------------------------ 动作行为参考
    def _start_action_bg(self) -> None:
        import threading as _th
        _th.Thread(target=self._build_actions_bg, daemon=True,
                   name="action-build").start()

    def _build_actions_bg(self) -> None:
        try:
            actions_mod.build_library()
            self.actions.reload()
        except Exception as e:
            log.info("动作库构建跳过：%s", e)
        actions_mod.start_ocr_pass(on_done=self._on_action_ocr_done)

    def _on_action_ocr_done(self) -> None:
        try:
            self.actions.reload()
            log.info("动作库文字识别完成，已刷新")
        except Exception:
            pass

    # ------------------------------------------------------------ 动作视频
    def _start_movies_bg(self) -> None:
        import threading as _th
        _th.Thread(target=self._build_movies_bg, daemon=True,
                   name="movie-build").start()

    def _build_movies_bg(self) -> None:
        try:
            result = movies_mod.ensure_processed()
            if result:
                self.movies_built.emit()
                log.info("动作视频库就绪：%s", "、".join(result.keys()))
        except Exception as e:
            log.warning("动作视频构建失败：%s", e)

    def _check_idle_movie(self) -> None:
        """3 分钟没互动：随机做 发呆/困/无聊/在干嘛（不与前 3 次重复）。"""
        try:
            if not self.cfg.get("use_movies", True):
                return
            if self.pet.movie_active or self.focus_mode:
                return
            if self.pet._fullscreen and self.cfg.get("mute_fullscreen", True):
                return
            gap = int(self.cfg.get("idle_movie_interval", 180))
            if time.time() - max(self._last_interaction, self._last_idle_movie) < gap:
                return
            pool = [n for n in ("发呆", "困", "无聊", "在干嘛") if self.pet.has_movie(n)]
            if not pool:
                return
            cands = [n for n in pool if n not in self._recent_movies]
            if not cands:
                cands = pool
            name = random.choice(cands)
            if self.pet.play_movie(name):
                self._recent_movies.append(name)
                self._recent_movies = [n for n in self._recent_movies if n in pool][-3:]
                self._last_idle_movie = time.time()
        except Exception as e:
            log.info("闲置动作跳过：%s", e)

    def _schedule_action(self) -> None:
        lo, hi = self.cfg.get("action_ref_interval", [1, 5])
        self.action_timer.start(random.randint(int(lo * 60), int(hi * 60)) * 1000)

    def _random_action(self) -> None:
        try:
            if self.pet.movie_active:
                return
            if self.cfg.get("use_action_refs", True) and not self.pet._fullscreen:
                item = self.actions.random_no_text()
                if item:
                    self._play_action(item, item.get("text") or None)
        finally:
            self._schedule_action()

    def _play_action(self, item: dict, caption=None) -> None:
        if not self.cfg.get("use_action_refs", True) or not item:
            return
        if self.pet.movie_active:
            return
        if self.pet._fullscreen and self.cfg.get("mute_fullscreen", True):
            return
        cx, _ = self.pet.center_on_screen()
        target_h = max(140, int(self.pet.draw_h * 1.05))
        self.action_overlay.play(item, cx, self.pet.y(), target_h,
                                 caption=(caption or "").strip() or None, cycles=2)
        # 动作层不能盖住对话框：把对话框（和剪贴板条）重新置顶
        try:
            if self.chat.isVisible():
                self.chat.raise_()
            if self.clip_bar.isVisible():
                self.clip_bar.raise_()
        except Exception:
            pass

    def _pet_say(self, text: str, keyword: str) -> None:
        self.pet.show_bubble(text, 4.5)

    # ------------------------------------------------------------ 托盘
    def toggle_pet(self) -> None:
        if self.pet.isVisible():
            self._deactivate_pet()
        else:
            self._activate_pet()

    def _deactivate_pet(self) -> None:
        """隐藏桌宠：停止一切与桌宠相关的计时器/动画/浮窗，不再有任何动作。"""
        try:
            self.pet.timer.stop()
            self.pet.stop_movie()
            self.pet.hide()
        except Exception:
            pass
        for t in (self.action_timer, self.talk_timer, self._vitality_timer,
                  self.clip_watcher.timer, self.behavior_timer, self._doc_timer,
                  self._idle_movie_timer):
            try:
                t.stop()
            except Exception:
                pass
        try:
            self.scheduler.timer.stop()
        except Exception:
            pass
        try:
            self.action_overlay.timer.stop()
            self.action_overlay.hide()
        except Exception:
            pass
        for w in (self.chat, self.clip_bar, self.radial):
            try:
                w.hide()
            except Exception:
                pass
        try:
            if getattr(self.hotkey, "ok", False):
                self.hotkey.uninstall()
        except Exception:
            pass
        log.info("桌宠已隐藏：动画/计时器/浮窗/快捷键全部停止")

    def _activate_pet(self) -> None:
        self.pet.show()
        try:
            self.pet.timer.start(self.pet.timer.interval())
        except Exception:
            pass
        self.behavior_timer.start(int(self.cfg.get("tick_interval", 2)) * 1000)
        self._schedule_action()
        self._schedule_talk()
        try:
            self.scheduler.timer.start(20000)
        except Exception:
            pass
        self._vitality_timer.start(60000)
        if self.cfg.get("clipboard_helper", True):
            self.clip_watcher.timer.start(2000)
        if getattr(self, "_doc_timer", None) is not None:
            self._doc_timer.start(20000)
        self._idle_movie_timer.start(5000)
        try:
            if not self.hotkey.ok:
                self.hotkey.install(self._on_selection_hotkey)
        except Exception:
            pass
        log.info("桌宠已恢复显示")

    def toggle_pause(self) -> None:
        self.pet._paused = not self.pet._paused
        self.pet.show_bubble("本鱼先休息会儿~" if self.pet._paused else "本鱼回来啦！", 3)

    def open_chat(self) -> None:
        cx, cy = self.pet.center_on_screen()
        self.chat.show_near(cx, cy)

    def _greet(self) -> None:
        hour = __import__("datetime").datetime.now().hour
        if hour < 6:
            greet = "主人这么晚还不睡呀…本鱼陪你 (｡•ᴗ•｡)"
        elif hour < 11:
            greet = "主人早上好~ 今天也要记得囤 token 哦！"
        elif hour < 14:
            greet = "主人中午好，吃饭了吗？本鱼想吃大白饭…"
        elif hour < 18:
            greet = "主人下午好呀，本鱼在这儿看着你呢 (๑•̀ㅂ•́)و"
        else:
            greet = "主人晚上好~ 忙了一天辛苦啦"
        self.pet.show_bubble(greet, 6)
        # 每日首次开机：互动报告 + 随机日常对话
        try:
            report = self.affinity.daily_report()
            if report:
                QTimer.singleShot(2800, lambda: (self.pet.show_bubble(report, 9),
                                                 self.chat.add_system(report)))
        except Exception:
            pass

    # ------------------------------------------------------------ 退出
    def quit_app(self) -> None:
        # 退出前停掉所有计时器，保证进程内不再有任何桌宠活动
        for t in (getattr(self, "behavior_timer", None), getattr(self, "talk_timer", None),
                  getattr(self, "action_timer", None), getattr(self, "_vitality_timer", None),
                  getattr(self, "clip_watcher", None) and self.clip_watcher.timer,
                  getattr(self, "scheduler", None) and self.scheduler.timer,
                  getattr(self, "_doc_timer", None),
                  getattr(self, "_idle_movie_timer", None),
                  getattr(self, "pet", None) and self.pet.timer,
                  getattr(self, "action_overlay", None) and self.action_overlay.timer):
            try:
                if t:
                    t.stop()
            except Exception:
                pass
        try:
            if getattr(self, "pet", None):
                self.pet.stop_movie()
                self.pet.hide()
            if getattr(self, "action_overlay", None):
                self.action_overlay.hide()
            self.cfg.set("window_pos", [self.pet.x(), self.pet.y()])
            self.cfg.save()
            if getattr(self, "hotkey", None):
                self.hotkey.uninstall()
            if getattr(self, "affinity", None):
                self.affinity.flush()
            self.llm.stop()
        except Exception:
            pass
        self.tray.hide()
        self.qapp.quit()


def detail_duration(path: str) -> int:
    return 2600
