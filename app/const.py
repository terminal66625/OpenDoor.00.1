# -*- coding: utf-8 -*-
"""全局常量与路径定义：所有数据均保存在桌宠自己的文件夹内。"""
import os
import sys

APP_NAME = "大肥鱼"
APP_ID = "dafeiyu_pet"
APP_VERSION = "1.1.0"

# 用户称呼 / 自称
MASTER = "主人"
SELF = "本鱼"
PET_NAME = "大肥鱼"


def _base_dir() -> str:
    """源码运行时=项目根目录；打包后=exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _base_dir()


def _impression_dir() -> str:
    """素材目录：优先找桌宠旁边的「大肥鱼印象」，其次桌面，最后旧路径。"""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    cands = [
        os.path.join(os.path.dirname(BASE_DIR), "大肥鱼印象"),
        os.path.join(desktop, "大肥鱼印象"),
        os.path.join(BASE_DIR, "大肥鱼印象"),
    ]
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[1]          # 桌面（找不到时相关功能自动跳过，不影响运行）


# 参考素材目录（只读来源，仅用于首次导入/重新索引）
IMPRESSION_DIR = _impression_dir()
SRC_STICKERS = os.path.join(IMPRESSION_DIR, "表情包")
SRC_ACTIONS = os.path.join(IMPRESSION_DIR, "动作行为参考")
SRC_MOVIES = os.path.join(IMPRESSION_DIR, "动作")
SRC_APPEARANCE = os.path.join(IMPRESSION_DIR, "外表参考")
SRC_LANG = os.path.join(IMPRESSION_DIR, "语言")

# 程序数据目录（读写）
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
PET_ASSETS = os.path.join(ASSETS_DIR, "pet")
CHARACTERS_DIR = os.path.join(ASSETS_DIR, "characters")
STICKER_DIR = os.path.join(ASSETS_DIR, "stickers")
ACTION_DIR = os.path.join(ASSETS_DIR, "actions")
MOVIE_DIR = os.path.join(ASSETS_DIR, "movies")
ICON_DIR = os.path.join(ASSETS_DIR, "icons")

BODY_PATH = os.path.join(PET_ASSETS, "body.png")
BODY_META = os.path.join(PET_ASSETS, "body_meta.json")

MEMORY_DIR = os.path.join(BASE_DIR, "memory")
TRANSCRIPT_DIR = os.path.join(MEMORY_DIR, "transcripts")
LOG_DIR = os.path.join(BASE_DIR, "logs")
TRASH_DIR = os.path.join(BASE_DIR, "trash")  # 无法识别的图片移到这里（而非直接删）

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PROFILE_PATH = os.path.join(MEMORY_DIR, "profile.json")
CHAT_HISTORY_PATH = os.path.join(MEMORY_DIR, "chat_history.json")
BEHAVIOR_MEMORY_PATH = os.path.join(MEMORY_DIR, "behavior_memory.json")
SETTINGS_PATH = os.path.join(MEMORY_DIR, "settings.json")
GREETING_STATE_PATH = os.path.join(MEMORY_DIR, "greeting_state.json")
ALARMS_PATH = os.path.join(MEMORY_DIR, "alarms.json")
STICKER_INDEX_PATH = os.path.join(MEMORY_DIR, "index_stickers.json")
STICKER_RECENT_PATH = os.path.join(MEMORY_DIR, "sticker_recent.json")
ACTION_INDEX_PATH = os.path.join(MEMORY_DIR, "index_actions.json")
TODOS_PATH = os.path.join(MEMORY_DIR, "todos.json")

# 网络与模型默认值
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"        # 官方兜底模型（当 ACTIVE_MODEL 不可用时自动回退）
DEFAULT_REASONER = "deepseek-reasoner"
ACTIVE_MODEL = "DeepSeek V4.1 Flash"   # 固定使用的模型名
DEFAULT_VISION_MODEL = "deepseek-chat"  # 若用户配置了视觉模型可替换
HOLIDAY_URL = "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"

# 行为循环
TICK_MS = 40                 # 动画帧间隔(ms)，约 25fps，动作更顺滑
BASE_SPEED = 80.0            # 基准速度 px/s
SAFE_MARGIN_X = 80
SAFE_MARGIN_Y = 40
MOUSE_FLEE_DIST = 100

ALL_DIRS = [
    ASSETS_DIR, PET_ASSETS, CHARACTERS_DIR, STICKER_DIR, ACTION_DIR, ICON_DIR,
    MOVIE_DIR, MEMORY_DIR, TRANSCRIPT_DIR, LOG_DIR, TRASH_DIR,
]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        os.makedirs(d, exist_ok=True)


# 支持的图片扩展名
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
