# -*- coding: utf-8 -*-
"""角色好感与养成系统（全部本地存储，无云端上传）。

- 好感度 5 级：聊天 / 点击 / 投喂 / 囤 token 都会增加好感
- 投喂大白饭：每日 3 份，提升活力值；活力低会蔫、变慢
- Token 囤储：每日 API 用量可手动囤储，达到阈值解锁成就与特殊动作
- 每日互动报告：记录聊天时长 / 互动次数 / 投喂，首次开机播报
"""
from __future__ import annotations

import datetime
import os
import time
from typing import Dict, List, Optional, Tuple

from . import const
from .logging_setup import setup_logging
from .util import atomic_write_json, read_json

log = setup_logging()

AFFINITY_PATH = os.path.join(const.MEMORY_DIR, "affinity.json")

FREE_RICE_PER_DAY = 3
TOKEN_ACHIEVEMENTS = [100, 500, 2000, 10000]

LEVELS: List[Tuple[int, str, str]] = [
    (0,   "初见", "主人……你好，本鱼叫大肥鱼。"),
    (30,  "熟悉", "主人又来啦，本鱼记住你了哦。"),
    (80,  "亲近", "主人~ 今天也给本鱼带大白饭了吗？"),
    (160, "黏人", "主人主人！本鱼一直在等你呢 (๑•̀ㅂ•́)و"),
    (300, "本命", "主人是本鱼最重要的人，谁都不许抢！"),
]

RANDOM_DAILY = [
    "今天也和本鱼一起加油吧，主人！",
    "本鱼把桌面收拾得干干净净，就等主人回来~",
    "主人今天想先聊聊天，还是先让本鱼看看屏幕？",
    "唔……本鱼今天也想吃大白饭呢。",
    "主人别忘了囤 token 哦，本鱼的小金库要满啦！",
]


class Affinity:
    def __init__(self) -> None:
        self.data: Dict = read_json(AFFINITY_PATH, None) or self._defaults()
        self._dirty = False
        self._last_save = 0.0
        self._rollover()

    # ------------------------------------------------------------ 写盘节流
    def _touch(self) -> None:
        """高频事件（聊天/互动）不立刻写盘，最多每 5 秒写一次。"""
        self._dirty = True
        if time.time() - self._last_save > 5.0:
            self.flush()

    def flush(self) -> None:
        if self._dirty:
            self.save()
            self._dirty = False
            self._last_save = time.time()

    # ------------------------------------------------------------ 基础
    def _defaults(self) -> Dict:
        return {
            "points": 0, "vitality": 80,
            "rice_date": "", "rice_used": 0,
            "tokens_stored": 0, "daily_used": 0, "daily_date": "",
            "chat_seconds": 0.0, "messages": 0, "interactions": 0, "feeds": 0,
            "report_date": "", "achievements": [], "created_at": "",
        }

    def save(self) -> None:
        atomic_write_json(AFFINITY_PATH, self.data)

    def _today(self) -> str:
        return datetime.date.today().isoformat()

    def _rollover(self) -> None:
        today = self._today()
        changed = False
        if self.data.get("rice_date") != today:
            self.data["rice_date"] = today
            self.data["rice_used"] = 0
            changed = True
        if self.data.get("daily_date") != today:
            self.data["daily_date"] = today
            self.data["daily_used"] = 0
            self.data["chat_seconds"] = 0.0
            self.data["messages"] = 0
            self.data["interactions"] = 0
            self.data["feeds"] = 0
            changed = True
        if not self.data.get("created_at"):
            self.data["created_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            changed = True
        if changed:
            self.save()

    # ------------------------------------------------------------ 等级
    def level(self) -> int:
        pts = self.data.get("points", 0)
        idx = 0
        for i, (th, _n, _c) in enumerate(LEVELS):
            if pts >= th:
                idx = i
        return idx

    def level_name(self) -> str:
        return LEVELS[self.level()][1]

    def level_catchphrase(self) -> str:
        return LEVELS[self.level()][2]

    def progress(self) -> Tuple[int, int, int]:
        """(当前等级, 当前分, 升级所需分)"""
        pts = self.data.get("points", 0)
        idx = self.level()
        nxt = LEVELS[idx + 1][0] if idx + 1 < len(LEVELS) else LEVELS[idx][0]
        return idx, pts, nxt

    # ------------------------------------------------------------ 好感
    def add_points(self, n: int, reason: str = "") -> List[str]:
        """增加好感，返回新解锁的成就列表。"""
        self.data["points"] = self.data.get("points", 0) + int(n)
        self.save()
        return self._check_achievements()

    def _check_achievements(self) -> List[str]:
        got = self.data.setdefault("achievements", [])
        new = []
        for th in TOKEN_ACHIEVEMENTS:
            key = f"囤token_{th}"
            if self.data.get("tokens_stored", 0) >= th and key not in got:
                got.append(key); new.append(f"囤到 {th} token")
        for lv, (th, name, _c) in enumerate(LEVELS):
            key = f"好感_{name}"
            if self.data.get("points", 0) >= th and key not in got and th > 0:
                got.append(key); new.append(f"好感达到「{name}」")
        if new:
            self.save()
        return new

    # ------------------------------------------------------------ 活力
    def vitality(self) -> int:
        return int(max(0, min(100, self.data.get("vitality", 80))))

    def vitality_tick(self, minutes: float) -> None:
        """随时间缓慢下降。"""
        if minutes <= 0:
            return
        v = self.data.get("vitality", 80) - minutes * 0.35
        self.data["vitality"] = max(0, min(100, v))
        self._touch()

    def speed_factor(self) -> float:
        """活力影响移动/动作速度 0.55~1.0。"""
        return 0.55 + 0.45 * (self.vitality() / 100.0)

    def is_tired(self) -> bool:
        return self.vitality() < 35

    # ------------------------------------------------------------ 投喂
    def rice_left(self) -> Optional[int]:
        """剩余份数；None 表示不限量。"""
        return None

    def feed(self) -> Optional[int]:
        """投喂一份大白饭（不限次数），返回今日已喂份数。"""
        self.data["rice_used"] = int(self.data.get("rice_used", 0)) + 1
        self.data["feeds"] = int(self.data.get("feeds", 0)) + 1
        self.data["vitality"] = min(100, self.data.get("vitality", 80) + 18)
        self.data["points"] = self.data.get("points", 0) + 5
        self.save()
        self._check_achievements()
        return int(self.data["rice_used"])

    # ------------------------------------------------------------ 囤 token
    def add_usage(self, n: int = 1) -> None:
        self.data["daily_used"] = int(self.data.get("daily_used", 0)) + int(n)
        self._touch()

    def pending_tokens(self) -> int:
        return int(self.data.get("daily_used", 0))

    def store_tokens(self) -> Tuple[int, List[str]]:
        """把手头的每日用量囤进小金库（不限次数），返回 (本次囤入, 新成就)。"""
        n = max(1, self.pending_tokens())
        self.data["tokens_stored"] = int(self.data.get("tokens_stored", 0)) + n
        self.data["daily_used"] = 0
        self.data["vitality"] = min(100, self.data.get("vitality", 80) + 6)
        self.data["points"] = self.data.get("points", 0) + 2
        self.save()
        return n, self._check_achievements()

    # ------------------------------------------------------------ 记录
    def record_message(self) -> None:
        self.data["messages"] = int(self.data.get("messages", 0)) + 1
        self.data["points"] = self.data.get("points", 0) + 1
        self._touch()

    def record_interaction(self) -> None:
        self.data["interactions"] = int(self.data.get("interactions", 0)) + 1
        self.data["points"] = self.data.get("points", 0) + 1
        self._touch()

    def record_chat_time(self, seconds: float) -> None:
        self.data["chat_seconds"] = float(self.data.get("chat_seconds", 0.0)) + seconds
        self._touch()

    # ------------------------------------------------------------ 日报
    def daily_report(self) -> Optional[str]:
        """每日首次调用返回一条简短总结（否则 None）。"""
        today = self._today()
        if self.data.get("report_date") == today:
            return None
        self.data["report_date"] = today
        self.save()
        mins = int(self.data.get("chat_seconds", 0) // 60)
        msg = f"今天本鱼陪主人聊了 {mins} 分钟、互动 {self.data.get('interactions', 0)} 次"
        feeds = self.data.get("feeds", 0)
        if feeds:
            msg += f"，还吃了 {feeds} 碗大白饭"
        msg += f"。好感「{self.level_name()}」，活力 {self.vitality()}~"
        import random
        if random.random() < 0.8:
            msg += "\n" + random.choice(RANDOM_DAILY)
        return msg

    def summary_lines(self) -> List[str]:
        idx, pts, nxt = self.progress()
        nxt_txt = f"（距下一级还差 {max(0, nxt - pts)}）" if idx + 1 < len(LEVELS) else "（已满级）"
        return [
            f"好感等级：{self.level_name()}　好感值 {pts} {nxt_txt}",
            f"活力值：{self.vitality()} / 100",
            f"今日大白饭：不限量（已喂 {self.data.get('rice_used', 0)} 份）",
            f"囤 token：待囤 {self.pending_tokens()}，已囤 {self.data.get('tokens_stored', 0)}",
            f"今日：消息 {self.data.get('messages', 0)} 条 · 互动 {self.data.get('interactions', 0)} 次 "
            f"· 投喂 {self.data.get('feeds', 0)} 次",
            "成就：" + ("、".join(self.data.get("achievements", [])) or "暂无"),
        ]
