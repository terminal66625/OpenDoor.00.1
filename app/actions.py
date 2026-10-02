# -*- coding: utf-8 -*-
"""动作行为参考库：把「动作行为参考」里的图片处理成桌宠可播放的动作。

处理流程（一次性，结果存入 assets/actions/ 与 memory/index_behaviors.json）：
    1. 读取图片；无法识别的格式移入 trash（不删除源文件）
    2. 抠出大肥鱼主体（按边缘颜色做带容差洪泛，兼容纯色/白底）
    3. 统一大小（主体高度归一化），并可做轻量颜色对齐，减小与桌宠的色差
    4. 静态图用插值补成平滑动作；动图抽样为帧序列
    5. 用 Windows OCR 识别图片里的文字（后台线程，识别完回写）
    6. 打包为 GIF 帧序列，供桌宠叠加播放

有文字的动作 → 仅在对话语境匹配时播放（并显示文字）；
无文字的动作 → 每 1~5 分钟随机播放。
"""
from __future__ import annotations

import os  # noqa: F401
import shutil
import subprocess
import threading
from collections import deque
from typing import Dict, List, Optional

from . import const
from .logging_setup import setup_logging
from .util import atomic_write_json, read_json

log = setup_logging()


def _pil():
    """延迟导入 Pillow，加快启动（只在后台处理动作图时加载）。"""
    from PIL import Image
    return Image

BEHAVIOR_INDEX = os.path.join(const.MEMORY_DIR, "index_behaviors.json")
ACTIONS_OUT = os.path.join(const.ASSETS_DIR, "actions")
OCR_PS = os.path.join(const.BASE_DIR, "tools", "ocr.ps1")

TARGET_H = 300              # 主体归一化高度
MAX_FRAMES = 20             # 动图最多抽样帧数
SUPPORTED = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

# 文件名 -> 触发关键词（语境/情绪）
KEYWORD_MAP = {
    "你好": ["你好", "嗨", "在吗", "早上好", "晚上好", "中午好"],
    "开心": ["开心", "高兴", "耶", "快乐", "哈哈", "嘻嘻"],
    "很生气": ["生气", "哼", "讨厌", "愤怒"],
    "生气": ["生气", "哼", "讨厌"],
    "无聊": ["无聊", "好闲", "没事干"],
    "无语": ["无语", "服了", "抽象"],
    "自夸": ["厉害", "聪明", "自夸", "夸自己"],
    "被夸了，开心": ["夸", "厉害", "棒"],
    "伸懒腰": ["困", "累", "睡", "懒"],
    "偷懒": ["偷懒", "摸鱼", "摆烂"],
    "跳舞": ["跳舞", "开心", "庆祝"],
    "刷牙": ["刷牙", "洗漱", "早上"],
    "大肥鱼耍无赖": ["耍赖", "无赖", "就不"],
    "我错了": ["错了", "对不起", "道歉", "原谅"],
    "完了，大肥鱼做错事了": ["完了", "做错", "糟糕"],
    "大肥鱼表面一套背面一套": ["表面", "背地", "两面"],
    "在干嘛": ["在干嘛", "干嘛", "做什么"],
    "要吃大白饭和TOKEN": ["大白饭", "token", "TOKEN", "饭", "饿"],
    "拿到TOKEN了，真好吃": ["token", "TOKEN", "拿到", "好吃"],
    "拿到米饭了，开心": ["米饭", "大白饭", "拿到"],
    "送主人礼物": ["礼物", "送", "主人"],
    "偷TOKEN被抓了": ["偷", "token", "被抓"],
    "偷拿TOKEN": ["偷", "token", "TOKEN"],
    "为什么要为难大肥鱼": ["为难", "欺负", "为什么"],
    "听不懂": ["听不懂", "不懂", "什么"],
    "TOKEN没了，要TOKEN": ["token没了", "要token", "没token"],
}


# ================================================================ 抠图
def _bg_flood_remove(img, tol: int = 58):
    """按四边颜色做带容差洪泛去背景；失败则原样返回。"""
    Image = _pil()
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    def corners():
        pts = [(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3),
               (w // 2, 2), (2, h // 2), (w - 3, h // 2), (w // 2, h - 3)]
        return [px[x, y][:3] for x, y in pts]

    seeds = corners()
    visited = bytearray(w * h)
    q = deque()

    def close(c1, c2):
        return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1]) + abs(c1[2] - c2[2]) <= tol * 3

    for x in range(w):
        for y in (0, h - 1):
            if any(close(px[x, y][:3], s) for s in seeds):
                q.append((x, y)); visited[y * w + x] = 1
    for y in range(h):
        for x in (0, w - 1):
            if any(close(px[x, y][:3], s) for s in seeds):
                q.append((x, y)); visited[y * w + x] = 1

    while q:
        x, y = q.popleft()
        base = px[x, y][:3]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny * w + nx]:
                if any(close(px[nx, ny][:3], s) for s in seeds) and close(px[nx, ny][:3], base):
                    visited[ny * w + nx] = 1
                    q.append((nx, ny))

    alpha = Image.frombytes("L", (w, h),
                            bytes(0 if v else 255 for v in visited))
    img.putalpha(alpha)
    bbox = img.getbbox()
    if not bbox:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    return img


def _cap_size(img: Image.Image, cap: int = 480) -> Image.Image:
    Image = _pil()
    if max(img.width, img.height) <= cap:
        return img
    r = cap / max(img.width, img.height)
    return img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))),
                      Image.LANCZOS)


def _opaque_ratio(img: Image.Image) -> float:
    a = img.convert("RGBA").getchannel("A")
    hist = a.histogram()
    opaque = sum(hist[16:])
    total = max(1, img.width * img.height)
    return opaque / total


def _subject_ok(img: Image.Image, orig: Optional[Image.Image] = None) -> bool:
    """判断抠图是否合理：主体占比不能太大，也不能被抠没了。"""
    bbox = img.getbbox()
    if not bbox:
        return False
    area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if area >= 0.92 * img.width * img.height:
        return False
    kept = _opaque_ratio(img)
    if kept < 0.08:                      # 抠得太狠，主体没了
        return False
    if orig is not None and kept < 0.25 * _opaque_ratio(orig):
        return False
    return True


def _color_match(img: Image.Image, ref: Image.Image, strength: float = 0.45) -> Image.Image:
    """把主体颜色统计向桌宠形象对齐，减小色差。"""
    try:
        import numpy as np
        Image = _pil()
        a = np.asarray(img.convert("RGBA"), dtype=np.float32)
        r = np.asarray(ref.convert("RGBA"), dtype=np.float32)
        am, rm = a[..., 3] > 16, r[..., 3] > 16
        if am.sum() < 50 or rm.sum() < 50:
            return img
        out = a.copy()
        for c in range(3):
            av, rv = a[..., c][am], r[..., c][rm]
            out[..., c][am] = np.clip(
                (av - av.mean()) * (rv.std() / max(1.0, av.std())) * strength + av.mean()
                + (rv.mean() - av.mean()) * strength, 0, 255)
        return Image.fromarray(out.astype(np.uint8), "RGBA")
    except Exception:
        return img


def _normalize(img: Image.Image, target_h: int = TARGET_H) -> Image.Image:
    Image = _pil()
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    if img.height <= 0:
        return img
    ratio = target_h / img.height
    return img.resize((max(1, int(img.width * ratio)), target_h), Image.LANCZOS)


def _canvas(imgs: List[Image.Image], pad: int = 24) -> List[Image.Image]:
    Image = _pil()
    w = max(i.width for i in imgs) + pad * 2
    h = max(i.height for i in imgs) + pad * 2
    out = []
    for im in imgs:
        c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        c.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
        out.append(c)
    return out


# ================================================================ OCR
_NOISE = ("已思考", "用时", "秒）", "秒)", "秒〕", "分析", "搜索", "参考资料",
          "让我", "用户", "回答", "最终", "因此")


def clean_ocr(txt: str) -> str:
    """清洗 OCR 结果：去 BOM/空格/UI 噪音，仅保留中英数字。"""
    if not txt:
        return ""
    t = txt.replace("\ufeff", "").strip()
    for n in _NOISE:
        t = t.replace(n, "")
    t = "".join(ch for ch in t if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return t[:16]


def _ocr_image(path: str) -> str:
    if not os.path.exists(OCR_PS):
        return ""
    tmp = os.path.join(const.MEMORY_DIR, "_ocr_one")
    try:
        os.makedirs(tmp, exist_ok=True)
        for f in os.listdir(tmp):
            try:
                os.remove(os.path.join(tmp, f))
            except OSError:
                pass
        shutil.copyfile(path, os.path.join(tmp, "one.png"))
        out_txt = os.path.join(tmp, "one.txt")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", OCR_PS, "-Dir", tmp, "-Out", out_txt],
                       capture_output=True, text=True, timeout=60)
        txt = ""
        if os.path.exists(out_txt):
            txt = open(out_txt, encoding="utf-8").read().strip()
        return clean_ocr(txt)
    except Exception:
        return ""


# ================================================================ 构建
def _safe(name: str) -> str:
    return "".join(ch for ch in name if ch not in r'\/:*?"<>|').strip() or "action"


def _keywords_for(name: str) -> List[str]:
    keys = set()
    for k, words in KEYWORD_MAP.items():
        if k in name or name in k:
            keys.add(k)
            keys.update(words)
    keys.add(name)
    return [k for k in keys if k]


def _src_sig(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{int(st.st_mtime)}-{st.st_size}"
    except OSError:
        return ""


def _current_sources() -> Dict[str, str]:
    """源目录里受支持的文件 -> 修改签名。"""
    out: Dict[str, str] = {}
    if os.path.isdir(const.SRC_ACTIONS):
        for fn in sorted(os.listdir(const.SRC_ACTIONS)):
            p = os.path.join(const.SRC_ACTIONS, fn)
            if os.path.isfile(p) and os.path.splitext(fn)[1].lower() in SUPPORTED:
                out[fn] = _src_sig(p)
    return out


def _fix_item_paths(it: Optional[Dict]) -> Optional[Dict]:
    """动作帧路径不存在时，按 safe 名回退到本地 assets/actions（换电脑/换盘符也能播）。"""
    if not it:
        return it
    d = it.get("dir", "")
    if not d or not os.path.isdir(d):
        safe = it.get("safe", "")
        if safe:
            cand = os.path.join(ACTIONS_OUT, safe)
            if os.path.isdir(cand):
                it["dir"] = cand
    ff = it.get("first_frame", "")
    if ff and not os.path.exists(ff):
        cand2 = os.path.join(it.get("dir", ""), os.path.basename(ff))
        if os.path.exists(cand2):
            it["first_frame"] = cand2
    return it


def build_library(force: bool = False) -> List[Dict]:
    cached = read_json(BEHAVIOR_INDEX, None) or []
    current = _current_sources()
    # 源文件集合/内容没变化 -> 直接用缓存
    if cached and not force:
        old_files = {it.get("file") for it in cached if it.get("file")}
        if old_files and set(current) == old_files and all(
                it.get("src_sig") == current.get(it.get("file")) for it in cached):
            return [_fix_item_paths(it) for it in cached]
    const.ensure_dirs()
    os.makedirs(ACTIONS_OUT, exist_ok=True)
    items: List[Dict] = []
    if not os.path.isdir(const.SRC_ACTIONS):
        # 只搬走「大肥鱼」文件夹时，素材目录不在：沿用已生成的动作，不能清空
        if cached:
            log.info("动作素材目录不存在，沿用已生成的 %d 个动作", len(cached))
            return [_fix_item_paths(it) for it in cached]
        atomic_write_json(BEHAVIOR_INDEX, items)
        return items

    old_by_file = {it.get("file"): it for it in cached if it.get("file")}

    # 参考形象（用于颜色对齐）
    Image = _pil()
    try:
        ref = Image.open(const.BODY_PATH).convert("RGBA")
    except Exception:
        ref = None

    for fn in sorted(current):
        sig = current[fn]
        path = os.path.join(const.SRC_ACTIONS, fn)
        prev = old_by_file.get(fn)
        if prev:
            _fix_item_paths(prev)          # 换电脑/换路径后先修正帧目录
        # 未改动的动作直接复用（保留已 OCR 的文字，避免重复识别）
        if prev and prev.get("src_sig") == sig and prev.get("dir") \
                and os.path.isdir(prev["dir"]):
            items.append(prev)
            continue
        ext = os.path.splitext(fn)[1].lower()
        name = os.path.splitext(fn)[0]
        if ext not in SUPPORTED:
            _to_trash(path, fn)
            continue
        try:
            src = Image.open(path)
            src.load()
            animated = bool(getattr(src, "is_animated", False))
        except Exception:
            _to_trash(path, fn)
            log.warning("无法识别的动作图片已移入 trash：%s", fn)
            continue

        frames: List[Image.Image] = []
        used_bg = False
        try:
            if animated:
                n = getattr(src, "n_frames", 1)
                step = max(1, n // MAX_FRAMES)
                for i in range(0, n, step):
                    src.seek(i)
                    f = _cap_size(src.convert("RGBA"))
                    cut = _bg_flood_remove(f)
                    if _subject_ok(cut, f):
                        f = cut
                    else:
                        used_bg = True
                    frames.append(_normalize(f))
            else:
                f = _cap_size(src.convert("RGBA"))
                cut = _bg_flood_remove(f)
                if _subject_ok(cut, f):
                    f = cut
                else:
                    used_bg = True
                f = _normalize(f)
                # 静态图 -> 用插值补成"呼吸"动作
                from .anim.interpolate import build_sequence
                kfs = [f, _shift(f, dy=-8, scale=1.02), f, _shift(f, dy=5, scale=0.99)]
                frames = build_sequence(kfs, inbetweens=3, mode="warp", loop=True)
        except Exception as e:
            log.warning("处理动作失败 %s：%s", fn, e)
            continue
        if not frames:
            continue
        if ref is not None:
            frames = [_color_match(fr, ref) for fr in frames]
        frames = _canvas(frames)

        safe = _safe(name)
        if any(it.get("safe") == safe for it in items):
            safe = f"{safe}_{len(items)}"
        out_dir = os.path.join(ACTIONS_OUT, safe)
        os.makedirs(out_dir, exist_ok=True)
        for old in os.listdir(out_dir):
            if old.endswith(".png"):
                try:
                    os.remove(os.path.join(out_dir, old))
                except OSError:
                    pass
        frame_paths = []
        for i, im in enumerate(frames):
            p = os.path.join(out_dir, f"f{i:03d}.png")
            im.save(p)
            frame_paths.append(p)

        items.append({
            "name": name,
            "file": fn,
            "src_sig": sig,
            "safe": safe,
            "dir": out_dir,
            "frames": len(frame_paths),
            "animated": animated,
            "background": used_bg,     # True=抠图失败，播放时套一张干净卡片
            "keywords": _keywords_for(name),
            "text": "",
            "has_text": None,      # OCR 完成后填 True/False
            "first_frame": frame_paths[0],
        })

    # 清理源文件已删除的旧动作输出目录
    keep = {it.get("safe") for it in items}
    try:
        for d in os.listdir(ACTIONS_OUT):
            p = os.path.join(ACTIONS_OUT, d)
            if os.path.isdir(p) and d not in keep:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass

    atomic_write_json(BEHAVIOR_INDEX, items)
    new_cnt = sum(1 for it in items if it not in cached)
    log.info("动作行为库已更新：%d 个（新增/变更 %d 个）", len(items), new_cnt)
    return items


def _shift(img: Image.Image, dy: int = 0, dx: int = 0, scale: float = 1.0) -> Image.Image:
    Image = _pil()
    w = max(1, int(img.width * scale))
    h = max(1, int(img.height * scale))
    im = img.resize((w, h), Image.LANCZOS)
    c = Image.new("RGBA", img.size, (0, 0, 0, 0))
    c.paste(im, ((img.width - w) // 2 + dx, (img.height - h) // 2 + dy), im)
    return c


def _to_trash(path: str, fn: str) -> None:
    try:
        os.makedirs(const.TRASH_DIR, exist_ok=True)
        dst = os.path.join(const.TRASH_DIR, fn)
        if not os.path.exists(dst):
            shutil.move(path, dst)
    except Exception:
        pass


# ================================================================ OCR 后台
def start_ocr_pass(on_done=None) -> None:
    """后台识别每个动作首帧的文字，识别完写回索引。"""
    def worker():
        items = read_json(BEHAVIOR_INDEX, []) or []
        changed = False
        for it in items:
            if it.get("has_text") is not None:
                continue
            txt = _ocr_image(it.get("first_frame", ""))
            it["text"] = txt
            it["has_text"] = bool(txt)
            changed = True
            log.info("动作文字识别：%s -> %s", it.get("name"), txt or "(无)")
        if changed:
            atomic_write_json(BEHAVIOR_INDEX, items)
        if on_done:
            try:
                on_done()
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True, name="action-ocr").start()


# ================================================================ 匹配
class ActionLibrary:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        items = read_json(BEHAVIOR_INDEX, []) or []
        self.items = [_fix_item_paths(it) for it in items]

    def by_name(self, name: str) -> Optional[Dict]:
        for it in self.items:
            if it.get("name") == name or it.get("safe") == name:
                return it
        return None

    def match_text(self, text: str) -> Optional[Dict]:
        """对话语境命中：优先匹配 OCR 文字，其次匹配关键词。"""
        if not text or not self.items:
            return None
        best, best_len = None, 0
        for it in self.items:
            if it.get("has_text") is False:
                continue
            cands = [it.get("text", "")] + list(it.get("keywords") or [])
            for c in cands:
                c = (c or "").strip()
                if len(c) >= 2 and c in text and len(c) > best_len:
                    best, best_len = it, len(c)
        return best

    def random_no_text(self) -> Optional[Dict]:
        pool = [it for it in self.items if it.get("has_text") is False]
        if not pool:
            return None
        import random
        return random.choice(pool)
