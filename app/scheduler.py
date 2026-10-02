# -*- coding: utf-8 -*-
"""定时任务：8/12/18 讨 TOKEN 与米饭、节假日祝福、凌晨 2 点压缩、闹钟、待办。"""
import datetime
import math
import os
import struct
import threading
import wave
from typing import List

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from . import const
from .logging_setup import setup_logging
from .util import atomic_write_json, read_json

log = setup_logging()

MEAL_TIMES = {8: "早上", 12: "中午", 18: "晚上"}


class Scheduler(QObject):
    notify = pyqtSignal(str, str)        # 文本, 表情关键词
    request_compress = pyqtSignal()
    alarm_fired = pyqtSignal(dict)

    def __init__(self, cfg, memory) -> None:
        super().__init__()
        self.cfg = cfg
        self.memory = memory
        self._last_minute = ""
        self._last_date = ""
        self.alarms: List[dict] = read_json(const.ALARMS_PATH, []) or []
        self.todos: List[dict] = read_json(const.TODOS_PATH, []) or []
        self._sound = None
        self._init_sound()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check)
        self.timer.start(20000)
        self._boot_greeting()

    # ------------------------------------------------------------ 铃声
    def _init_sound(self) -> None:
        """只准备铃声文件（stdlib）；Qt 播放器延迟到第一次响铃再建，加快启动。"""
        path = os.path.join(const.ASSETS_DIR, "chime.wav")
        if not os.path.exists(path):
            _make_cute_chime(path)
        self._chime_path = path

    def _ensure_sound(self):
        if self._sound is not None:
            return self._sound
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtMultimedia import QSoundEffect
            if os.path.exists(self._chime_path):
                self._sound = QSoundEffect()
                self._sound.setSource(QUrl.fromLocalFile(self._chime_path))
                self._sound.setVolume(max(0.0, min(1.0,
                    float(self.cfg.get("action_volume", 70)) / 100.0)))
        except Exception as e:
            log.warning("铃声初始化失败：%s", e)
        return self._sound

    def play_ring(self) -> None:
        if not self.cfg.get("sound_enabled", True):
            return
        try:
            s = self._ensure_sound()
            if s:
                s.play()
        except Exception:
            pass

    # ------------------------------------------------------------ 闹钟
    def save_alarms(self) -> None:
        atomic_write_json(const.ALARMS_PATH, self.alarms)

    def add_alarm(self, time_str: str, label: str = "闹钟") -> None:
        self.alarms.append({"time": time_str, "label": label, "enabled": True})
        self.save_alarms()

    def remove_alarm(self, index: int) -> None:
        if 0 <= index < len(self.alarms):
            self.alarms.pop(index)
            self.save_alarms()

    def save_todos(self) -> None:
        atomic_write_json(const.TODOS_PATH, self.todos)

    def add_todo(self, text: str, time_str: str) -> None:
        self.todos.append({"text": text, "time": time_str, "enabled": True,
                           "date": datetime.date.today().isoformat()})
        self.save_todos()

    # ------------------------------------------------------------ 检查
    def _check(self) -> None:
        now = datetime.datetime.now()
        minute = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")
        if minute == self._last_minute and today == self._last_date:
            return
        self._last_minute = minute
        self._last_date = today

        # 饭点提醒
        if self.cfg.get("meal_reminder", True) and now.hour in MEAL_TIMES and now.minute == 0:
            part = MEAL_TIMES[now.hour]
            self.notify.emit(
                f"{part}到啦主人！该给本鱼投喂 TOKEN 和大白饭了~ (๑´ㅂ`๑)", "要大白饭")

        # 凌晨 2 点压缩
        if now.hour == 2 and now.minute == 0:
            self.request_compress.emit()

        # 闹钟
        for a in list(self.alarms):
            if a.get("enabled") and a.get("time") == minute:
                self.play_ring()
                self.alarm_fired.emit(a)
                self.notify.emit(f"叮铃铃！{a.get('label', '闹钟')}时间到啦~ ⏰", "哇")

        # 待办
        for t in list(self.todos):
            if t.get("enabled") and t.get("time") == minute and t.get("date") == today:
                self.notify.emit(f"主人别忘了：{t.get('text')} ✅", "思考")

    # ------------------------------------------------------------ 节假日
    def _boot_greeting(self) -> None:
        threading.Thread(target=self._holiday_worker, daemon=True).start()

    def _holiday_worker(self) -> None:
        try:
            import requests  # 延迟导入，加快启动
            state = read_json(const.GREETING_STATE_PATH, {}) or {}
            today = datetime.date.today().isoformat()
            if state.get("date") == today:
                return
            year = datetime.date.today().year
            url = const.HOLIDAY_URL.format(year=year)
            r = requests.get(url, timeout=8)
            r.raise_for_status()
            data = r.json()
            name, off = None, False
            for d in data.get("days", []):
                if d.get("date") == today:
                    name = d.get("name")
                    off = bool(d.get("isOffDay"))
                    break
            if name and off:
                self.notify.emit(f"今天是中国{name}哦，{const.MASTER}节日快乐！本鱼陪你一起过~ 🎉", "开心")
            state["date"] = today
            state["holiday"] = name or ""
            atomic_write_json(const.GREETING_STATE_PATH, state)
        except Exception as e:
            log.info("节假日获取失败（不影响使用）：%s", e)


def _make_cute_chime(path: str) -> None:
    """合成一段固定的可爱铃声（叮咚~）。"""
    try:
        rate = 22050
        notes = [(880, 0.12), (1174, 0.12), (987, 0.18), (1318, 0.22)]
        frames = bytearray()
        for freq, dur in notes:
            n = int(rate * dur)
            for i in range(n):
                env = min(1.0, i / (rate * 0.02)) * math.exp(-3.0 * i / n)
                sample = int(12000 * env * math.sin(2 * math.pi * freq * i / rate))
                frames += struct.pack("<h", sample)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(bytes(frames))
        log.info("已生成可爱铃声：%s", path)
    except Exception as e:
        log.warning("铃声生成失败：%s", e)
