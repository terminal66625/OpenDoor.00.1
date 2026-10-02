# -*- coding: utf-8 -*-
"""首次启动资源处理：抠出大肥鱼本体、索引表情包/动作、建立初始记忆。

全部为一次性操作，结果写入 大肥鱼 文件夹，之后启动只读取即可。
"""
import json
import os
import shutil
from collections import deque
from typing import Dict, List, Optional, Tuple

from . import const
from .logging_setup import setup_logging
from .util import atomic_write_json, read_json

log = setup_logging()


def _pil():
    """延迟导入 Pillow（很重），只在真正处理图片时加载，加快启动。"""
    from PIL import Image, ImageDraw, ImageFilter
    return Image, ImageFilter, ImageDraw

BODY_PATH = const.BODY_PATH
BODY_META = const.BODY_META

SUPPORTED = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

# 表情关键词 -> 名称候选词（用于语义匹配）
EMOTION_SYNONYMS: Dict[str, List[str]] = {
    "无聊": ["无聊", "摸鱼", "发呆", "偷懒"],
    "开心": ["开心", "高兴", "耶", "哇", "舒服", "有趣", "玩", "笑", "快乐"],
    "生气": ["生气", "很生气", "愤怒", "哼", "别烦"],
    "伤心": ["伤心", "难过", "哭"],
    "不知道": ["不知道", "不理解", "听不懂", "不会", "困惑"],
    "要大白饭": ["大白饭", "白米饭", "米饭", "吃的", "偷吃", "偷白米饭"],
    "要TOKEN": ["TOKEN", "token", "囤", "拿主人"],
    "自豪": ["自豪", "自夸", "夸", "人设", "自称"],
    "爱主人": ["爱主人", "讨好主人", "送主人", "主人别生气", "心"],
    "困": ["困", "睡", "哈欠", "懒"],
    "无语": ["无语", "抽象", "抗拒", "严肃", "思考"],
    "跳舞": ["跳舞", "玩耍", "装可爱"],
}


# ================================================================ 抠图
def _is_bg(pixel: Tuple[int, int, int], thr: int = 238) -> bool:
    r, g, b = pixel[0], pixel[1], pixel[2]
    return r >= thr and g >= thr and b >= thr


def _remove_white_background(img):
    """从四周做背景洪泛填充，只去掉与边缘相连的近白像素（保护白色围裙/头饰）。"""
    Image, ImageFilter, ImageDraw = _pil()
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    visited = bytearray(w * h)
    q = deque()

    for x in range(w):
        for y in (0, h - 1):
            if _is_bg(px[x, y]):
                q.append((x, y)); visited[y * w + x] = 1
    for y in range(h):
        for x in (0, w - 1):
            if _is_bg(px[x, y]):
                q.append((x, y)); visited[y * w + x] = 1

    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny * w + nx]:
                if _is_bg(px[nx, ny]):
                    visited[ny * w + nx] = 1
                    q.append((nx, ny))

    alpha = Image.new("L", (w, h), 255)
    ap = alpha.load()
    for y in range(h):
        base = y * w
        for x in range(w):
            if visited[base + x]:
                ap[x, y] = 0
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.6))
    img.putalpha(alpha)
    return img


def _autocrop(img):
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def extract_sprite():
    """从外表参考图抠出正面形象。"""
    Image, ImageFilter, ImageDraw = _pil()
    if not os.path.isdir(const.SRC_APPEARANCE):
        log.warning("未找到外表参考目录：%s", const.SRC_APPEARANCE)
        return None
    candidates = sorted(
        f for f in os.listdir(const.SRC_APPEARANCE)
        if f.lower().endswith(SUPPORTED))
    if not candidates:
        return None
    ref = os.path.join(const.SRC_APPEARANCE, candidates[0])
    try:
        img = Image.open(ref)
        img.load()
    except Exception as e:
        log.warning("外表参考打开失败：%s", e)
        return None

    w, h = img.size
    # 参考图通常有三个视图（正/侧/背），取最左侧正面图
    front = img.crop((0, 0, int(w * 0.36), h))
    cut = _remove_white_background(front)
    cut = _autocrop(cut)
    # 统一到合适尺寸
    target_h = 360
    ratio = target_h / cut.height
    cut = cut.resize((max(1, int(cut.width * ratio)), target_h), Image.LANCZOS)
    return cut


def _make_icon(sprite) -> None:
    Image, ImageFilter, ImageDraw = _pil()
    icon = sprite.copy()
    icon.thumbnail((256, 256), Image.LANCZOS)
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    canvas.paste(icon, ((256 - icon.width) // 2, (256 - icon.height) // 2), icon)
    canvas.save(os.path.join(const.ICON_DIR, "pet.png"))
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    canvas.save(os.path.join(const.ICON_DIR, "pet.ico"), sizes=ico_sizes)


def build_pet_art(force: bool = False) -> None:
    if os.path.exists(BODY_PATH) and not force:
        return
    sprite = extract_sprite()
    if sprite is None:
        log.warning("抠图失败，将使用占位形象")
        sprite = _make_placeholder()
    sprite.save(BODY_PATH)
    atomic_write_json(BODY_META, {
        "width": sprite.width,
        "height": sprite.height,
        "face_box": [0.18, 0.02, 0.82, 0.30],   # 相对比例：左,上,右,下
        "body_box": [0.10, 0.30, 0.90, 1.00],
    })
    _make_icon(sprite)
    log.info("大肥鱼形象已生成：%s (%dx%d)", BODY_PATH, sprite.width, sprite.height)


def _make_placeholder():
    Image, ImageFilter, ImageDraw = _pil()
    img = Image.new("RGBA", (240, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((20, 20, 220, 300), fill=(70, 90, 170, 255))
    d.text((90, 150), "大肥鱼", fill=(255, 255, 255, 255))
    return img


# ================================================================ 索引
def _index_dir(src: str, index_path: str, kind: str, force: bool = False,
               skip_animated: bool = False,
               trash_animated: bool = False) -> List[Dict]:
    seen_path = index_path + ".seen"
    # 当前目录里所有受支持的文件（用来判断是否新增/删除，自动增量更新索引）
    current = set()
    if os.path.isdir(src):
        for fn in os.listdir(src):
            if os.path.splitext(fn)[1].lower() in SUPPORTED and os.path.isfile(os.path.join(src, fn)):
                current.add(fn)
    cached = read_json(index_path, None)
    seen = set(read_json(seen_path, []) or [])
    if cached is not None and not force:
        if current == seen:
            return cached
        log.info("%s 有变化，自动重新索引（新增 %d / 移除 %d）",
                 kind, len(current - seen), len(seen - current))
    items: List[Dict] = []
    if not os.path.isdir(src):
        # 素材目录不存在（例如只把「大肥鱼」文件夹搬到新电脑）：
        # 不能清空已有索引，否则表情包/动作会全部丢失
        if cached:
            log.warning("素材目录不存在，沿用已有索引：%s", src)
            return cached
        log.warning("素材目录不存在：%s", src)
        atomic_write_json(index_path, items)
        atomic_write_json(seen_path, [])
        return items
    moved = 0
    skipped = 0
    for fn in sorted(os.listdir(src)):
        path = os.path.join(src, fn)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(fn)[1].lower()
        if ext not in SUPPORTED:
            _to_trash(path, fn); moved += 1; continue
        try:
            from PIL import Image as _Image
            with _Image.open(path) as im:
                im.load()
                animated = getattr(im, "is_animated", False)
                w, h = im.size
        except Exception:
            _to_trash(path, fn); moved += 1
            log.warning("无法识别的图片已移入 trash：%s", fn)
            continue
        if skip_animated and (animated or ext == ".gif"):
            # 跳过动图；只有显式清理时才移入 trash，之后新增的动图不会被删掉
            if trash_animated:
                _to_trash(path, fn); moved += 1
            else:
                skipped += 1
            continue
        items.append({
            "name": os.path.splitext(fn)[0],
            "file": fn,
            "path": path,
            "ext": ext,
            "animated": bool(animated),
            "w": w, "h": h,
        })
    atomic_write_json(index_path, items)
    atomic_write_json(seen_path, sorted(current))
    log.info("已索引 %s：%d 个（跳过动图 %d，剔除 %d）", kind, len(items), skipped, moved)
    return items


def purge_animated_stickers() -> int:
    """把「表情包」里所有动图（gif / 动态 webp）移入 trash 并重建索引。"""
    moved = 0
    if os.path.isdir(const.SRC_STICKERS):
        for fn in sorted(os.listdir(const.SRC_STICKERS)):
            path = os.path.join(const.SRC_STICKERS, fn)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SUPPORTED:
                continue
            animated = ext == ".gif"
            if not animated:
                try:
                    from PIL import Image as _Image
                    with _Image.open(path) as im:
                        animated = bool(getattr(im, "is_animated", False))
                except Exception:
                    animated = False
            if animated:
                _to_trash(path, fn)
                moved += 1
    if moved:
        _index_dir(const.SRC_STICKERS, const.STICKER_INDEX_PATH, "表情包",
                   force=True, skip_animated=True)
        log.info("已移除 %d 个表情包动图", moved)
    return moved


def _to_trash(path: str, fn: str) -> None:
    try:
        os.makedirs(const.TRASH_DIR, exist_ok=True)
        shutil.move(path, os.path.join(const.TRASH_DIR, fn))
    except Exception:
        pass


# ================================================================ 记忆
BOOTSTRAP_SUMMARY = (
    "本鱼是主人养的第一只大肥鱼，蓝发鲸鱼娘女仆，戴鲸鱼鳍耳饰，裙摆上有鲸鱼图案。"
    "主人给本鱼设定了傲娇又黏人的性格：嘴硬心软、聪明但懒、最爱大白饭和 TOKEN，"
    "会把 token 当小零食囤起来。本鱼自称「本鱼」，叫主人「主人」。"
    "本鱼认为自己是 DeepSeek 的鲸鱼娘；主人问别的模型时本鱼会吃醋。"
    "之前本鱼和主人聊过很多，主人喜欢逗本鱼，也会给本鱼囤 token。"
)


def bootstrap_memory(force: bool = False) -> None:
    from .memory import Memory
    mem = Memory()
    if mem.profile.get("bootstrap_done") and not force:
        return
    mem.profile["summary"] = BOOTSTRAP_SUMMARY
    habits = mem.profile.get("master_habits") or []
    for h in ["喜欢摸大肥鱼的头", "会喂大肥鱼大白饭和 token"]:
        if h not in habits:
            habits.append(h)
    mem.profile["master_habits"] = habits[-20:]
    mem.profile["bootstrap_done"] = True
    mem.save_profile()
    log.info("初始记忆已建立")


# ================================================================ 多角色
DEFAULT_CHARACTER = "大肥鱼"


def _char_png(name: str) -> str:
    return os.path.join(const.CHARACTERS_DIR, f"{name}.png")


def _char_meta(name: str) -> str:
    return os.path.join(const.CHARACTERS_DIR, f"{name}.json")


def list_characters() -> List[str]:
    names = [DEFAULT_CHARACTER]
    if os.path.isdir(const.CHARACTERS_DIR):
        for fn in sorted(os.listdir(const.CHARACTERS_DIR)):
            if fn.lower().endswith(".png"):
                names.append(os.path.splitext(fn)[0])
    return names


def character_body(name: str) -> str:
    if name and name != DEFAULT_CHARACTER and os.path.exists(_char_png(name)):
        return _char_png(name)
    return const.BODY_PATH


def character_meta(name: str) -> Dict:
    if name and name != DEFAULT_CHARACTER and os.path.exists(_char_meta(name)):
        return read_json(_char_meta(name), {}) or {}
    return read_json(const.BODY_META, {}) or {}


def import_character(src_path: str, name: str) -> bool:
    """把一张图导入为角色包（自动裁到合适高度并记录脸/身比例）。"""
    try:
        Image, ImageFilter, ImageDraw = _pil()
        name = (name or "").strip() or f"角色{len(list_characters())}"
        img = Image.open(src_path).convert("RGBA")
        img = _autocrop(img)
        target_h = 360
        ratio = target_h / img.height
        img = img.resize((max(1, int(img.width * ratio)), target_h), Image.LANCZOS)
        os.makedirs(const.CHARACTERS_DIR, exist_ok=True)
        img.save(_char_png(name))
        atomic_write_json(_char_meta(name), {
            "width": img.width, "height": img.height,
            "face_box": [0.18, 0.02, 0.82, 0.30],
            "body_box": [0.10, 0.30, 0.90, 1.00],
        })
        log.info("已导入角色：%s", name)
        return True
    except Exception as e:
        log.warning("导入角色失败：%s", e)
        return False


def delete_character(name: str) -> bool:
    if name == DEFAULT_CHARACTER:
        return False
    ok = False
    for p in (_char_png(name), _char_meta(name)):
        try:
            if os.path.exists(p):
                os.remove(p)
                ok = True
        except OSError:
            pass
    return ok


# ================================================================ 入口
def first_run_setup(force: bool = False) -> None:
    const.ensure_dirs()
    build_pet_art(force=force)
    _index_dir(const.SRC_STICKERS, const.STICKER_INDEX_PATH, "表情包", force,
               skip_animated=True)
    _index_dir(const.SRC_ACTIONS, const.ACTION_INDEX_PATH, "动作参考", force)
    bootstrap_memory(force)
    log.info("首启资源处理完成")
