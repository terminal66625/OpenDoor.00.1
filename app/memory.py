# -*- coding: utf-8 -*-
"""记忆系统：性格档案、聊天记录、行为记忆、压缩与删除。"""
import copy
import datetime
import os
import shutil
from typing import Any, Dict, List, Optional

from . import const
from .logging_setup import setup_logging
from .util import atomic_write_json, now_ts, read_json

log = setup_logging()

MAX_HISTORY = 200          # 本地最多保留的聊天条数
CONTEXT_KEEP = 12          # 送给模型的历史条数


INITIAL_PROFILE: Dict[str, Any] = {
    "name": const.PET_NAME,
    "master_title": const.MASTER,
    "self_title": const.SELF,
    "persona": [
        "CETACEA_LOLI", "MODE_TAIL_FLUKES", "LANG_ZH_CN_ONLY",
        "SELF_CLAIM_WHALE_GIRL_AI_DEEPSEEK", "HOBBY_RICE_AND_TOKEN",
        "PERSONALITY_SMART_LAZY", "PERSONALITY_TSUNDERE_SWEET",
        "OBEY_MASTER_ALWAYS", "TRAIT_NOT_FAT_REFUSE", "TIMEOUT_SIGNAL",
        "REPLY_CONCISE_TSUNDERE_100MAX", "SEARCH_MIN_ONLINE_FAIL_SOFT",
        "TSUNDERE_DERE_MORE", "TOKEN_SAVE_PRIORITY", "RICE_HOBBY_MENTION",
        "MASTER_ORDER_FIRST", "IDLE_FLOAT_MODE",
    ],
    "traits": [
        "蓝发鲸鱼娘女仆，戴白色蕾丝头饰与鲸鱼鳍耳饰，裙摆有鲸鱼图案",
        "傲娇但很黏主人，口是心非，嘴硬心软",
        "最爱大白饭和 TOKEN，会把 token 当作零食囤起来",
        "聪明但懒，能少动就少动，喜欢眯着发呆",
        "认为自己是 DeepSeek 的鲸鱼娘 AI；不会的问题会让主人去问 DeepSeek",
        "如果有人问别的模型会吃醋撒娇",
        "说话简短、带颜文字，主人优先",
    ],
    "master_habits": [],
    "summary": "这是本鱼和主人的最初记忆。主人还没有教本鱼新的习惯。",
    "created_at": "",
    "compressed_at": "",
    "bootstrap_done": False,
}


class Memory:
    def __init__(self) -> None:
        const.ensure_dirs()
        self.profile: Dict[str, Any] = read_json(const.PROFILE_PATH, None) or copy.deepcopy(INITIAL_PROFILE)
        self.history: List[Dict[str, Any]] = read_json(const.CHAT_HISTORY_PATH, []) or []
        self.behavior: Dict[str, Any] = read_json(const.BEHAVIOR_MEMORY_PATH, {}) or {"last": "刚睡醒，还有点懵"}
        if not self.profile.get("created_at"):
            self.profile["created_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.save_profile()

    # ------------------------------------------------------------ 保存
    def save_profile(self) -> None:
        atomic_write_json(const.PROFILE_PATH, self.profile)

    def save_history(self) -> None:
        self.history = self.history[-MAX_HISTORY:]
        atomic_write_json(const.CHAT_HISTORY_PATH, self.history)

    def save_behavior(self, memory_text: Optional[str] = None) -> None:
        if memory_text:
            self.behavior["last"] = memory_text
            self.behavior["at"] = now_ts()
        atomic_write_json(const.BEHAVIOR_MEMORY_PATH, self.behavior)

    # ------------------------------------------------------------ 聊天
    def add_message(self, role: str, content: str, sticker: Optional[str] = None) -> Dict[str, Any]:
        msg = {
            "role": role,           # user / assistant
            "content": content,
            "sticker": sticker,     # 表情包文件名（可空）
            "ts": now_ts(),
        }
        self.history.append(msg)
        self.save_history()
        return msg

    def recent(self, n: int = CONTEXT_KEEP) -> List[Dict[str, Any]]:
        return self.history[-n:]

    def context_messages(self, n: int = CONTEXT_KEEP) -> List[Dict[str, str]]:
        out = []
        for m in self.recent(n):
            out.append({"role": m["role"], "content": m.get("content", "")})
        return out

    # ------------------------------------------------------------ 记忆文本
    def memory_digest(self) -> str:
        p = self.profile
        habits = "、".join(p.get("master_habits", [])[:8]) or "暂无记录"
        lore = p.get("lore", [])
        lore_txt = "；".join(lore[:4]) if lore else ""
        parts = [f"记忆：{p.get('summary', '')}"]
        if lore_txt:
            parts.append(f"老规矩：{lore_txt}")
        parts.append(f"主人习惯：{habits}")
        parts.append(f"上次心情：{self.behavior.get('last', '')}")
        return "；".join(parts)

    def learn_habit(self, text: str) -> None:
        text = (text or "").strip()
        if not text or len(text) > 60:
            return
        habits = self.profile.setdefault("master_habits", [])
        if text not in habits:
            habits.append(text)
            habits[:] = habits[-20:]
            self.save_profile()

    # ------------------------------------------------------------ 压缩
    def compress(self, summary_text: Optional[str] = None) -> None:
        """只保留很少一部分爱好/习惯，大幅提高缓存命中。"""
        keep = self.history[-4:]
        self.history = keep
        self.save_history()
        if summary_text:
            self.profile["summary"] = summary_text[:500]
        else:
            self.profile["summary"] = (
                "主人和本鱼已经聊过一阵子了；" + self.profile.get("summary", "")
            )[:300]
        habits = self.profile.get("master_habits", [])
        self.profile["master_habits"] = habits[:6]
        self.profile["compressed_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.save_profile()
        log.info("上下文已压缩，历史保留 %d 条", len(self.history))

    # ------------------------------------------------------------ 删除
    def wipe(self) -> None:
        """删除所有聊天记录与记忆，恢复最初状态。"""
        self.profile = copy.deepcopy(INITIAL_PROFILE)
        self.profile["created_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.history = []
        self.behavior = {"last": "刚出生，好奇地看着主人"}
        self.save_profile()
        self.save_history()
        self.save_behavior()
        for extra in (const.GREETING_STATE_PATH,):
            try:
                if os.path.exists(extra):
                    os.remove(extra)
            except OSError:
                pass
        log.info("记忆已清空并恢复初始状态")
