# -*- coding: utf-8 -*-
"""配置持久化：读写 config.json（Key 加密保存，绝不明文）。"""
import copy
import datetime
import os
from typing import Any, Dict

from . import const
from .logging_setup import setup_logging
from .util import atomic_write_json, decrypt_secret, encrypt_secret, read_json

log = setup_logging()

DEFAULTS: Dict[str, Any] = {
    "api_key_enc": "",              # 加密后的 Key（不明文）
    "base_url": const.DEFAULT_BASE_URL,
    "model": const.ACTIVE_MODEL,    # 固定：DeepSeek V4.1 Flash
    "reasoning": "low",             # 固定：low（思考强度）
    "temperature": 0.4,
    "tick_interval": 2,             # 行为决策间隔(秒)
    "key_verified": False,
    "last_verify_at": "",
    "window_pos": None,
    "opacity": 100,                 # 1~100
    "scale": 72,                    # 形象大小 40~180（初始 = 当前大小的 80%）
    "auto_start": True,
    "sound_enabled": True,
    "mute_fullscreen": True,        # 全屏免打扰
    "smart_downclock": True,        # 高负载/空闲时智能降频
    "clipboard_helper": True,       # 剪贴板助手
    "meal_reminder": True,          # 8/12/18 讨 TOKEN 与米饭
    "allow_move": False,            # 允许桌宠在桌面上移动（默认静止）
    "use_anim_clips": True,         # 使用 app/anim 生成的动作动画片段
    "use_action_refs": True,        # 使用「动作行为参考」动作（含文字）
    "use_radial_menu": True,        # 右键呼出半圆快捷面板
    "use_movies": True,             # 动作视频（投喂/囤token/闲置时的透明动作+声音）
    "action_volume": 70,            # 大肥鱼音量（动作声音 / 提醒铃声）0~100
    "idle_movie_interval": 180,     # 无互动多久后做闲置动作（秒）
    "close_documents": True,        # 开机自动关闭弹出的「文档」窗口
    "boot_watch_debug": False,      # 诊断：记录「文档」窗口是被谁打开的（默认关闭）
    "hotkey": "Ctrl+Alt+D",         # 全局划词召唤快捷键
    "action_ref_interval": [1, 5],  # 无文字动作随机间隔(分钟)
    "character": "大肥鱼",           # 当前角色
    "move_interval": [5, 10],       # 随机移动间隔(分钟)
    "idle_talk_interval": [5, 10],  # 自言自语间隔(分钟)
    "action_interval": [1, 5],      # 无文字动作随机启动间隔(分钟)
    "theme": {                      # 对话气泡外观
        "ai_color": "#dcecff",
        "user_color": "#c8f0c8",
        "text_color": "#22364f",
        "font_size": 13,
        "radius": 10,
        "opacity": 98,
    },
    "version": 1,
}


class Config:
    def __init__(self) -> None:
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    # -------------------------------------------------- 读写
    def load(self) -> None:
        const.ensure_dirs()
        data = read_json(const.CONFIG_PATH, None)
        if isinstance(data, dict):
            for k, v in data.items():
                self._data[k] = v
        else:
            self.save()
            log.info("首次运行：已生成默认配置 %s", const.CONFIG_PATH)

    def save(self) -> None:
        atomic_write_json(const.CONFIG_PATH, self._data)

    # -------------------------------------------------- 属性
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    @property
    def raw(self) -> Dict[str, Any]:
        return self._data

    # -------------------------------------------------- Key
    @property
    def api_key(self) -> str:
        return decrypt_secret(self._data.get("api_key_enc", ""))

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._data["api_key_enc"] = encrypt_secret((value or "").strip())

    def has_key(self) -> bool:
        return bool(self.api_key)

    def clear_key(self) -> None:
        self._data["api_key_enc"] = ""
        self._data["key_verified"] = False

    def mark_verified(self, ok: bool) -> None:
        self._data["key_verified"] = bool(ok)
        self._data["last_verify_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        self.save()

    # -------------------------------------------------- 便捷
    @property
    def base_url(self) -> str:
        # 固定使用 DeepSeek 官方地址，不对外暴露、不可修改
        return const.DEFAULT_BASE_URL

    @property
    def model(self) -> str:
        return self._data.get("model") or const.DEFAULT_MODEL

    @property
    def opacity(self) -> int:
        return int(self._data.get("opacity", 100))

    @opacity.setter
    def opacity(self, v: int) -> None:
        self._data["opacity"] = max(1, min(100, int(v)))

    @property
    def scale(self) -> int:
        return int(self._data.get("scale", 72))

    @scale.setter
    def scale(self, v: int) -> None:
        self._data["scale"] = max(40, min(180, int(v)))
