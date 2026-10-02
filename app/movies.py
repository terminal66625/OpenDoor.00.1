# -*- coding: utf-8 -*-
"""动作视频库：把「大肥鱼印象/动作」里的 mp4 预处理成透明帧序列 + 音频。

预处理（一次性，后台线程里跑）：
    ffmpeg 拆帧 -> 绿色背景抠图(透明) -> 全片统一裁剪/缩放到固定高度 -> 存 PNG 序列
    同时抽出音频为 wav，运行时用 QSoundEffect 与画面同步播放。

运行时按需读取单帧（LRU 缓存），内存占用只有几 MB。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

from . import const
from .logging_setup import setup_logging

log = setup_logging()

FRAME_FPS = 24.0          # 动作视频统一帧率
TARGET_H = 350            # 抠像后角色高度（接近 body.png 的 360，显示时再按比例缩放）
GREEN_MARGIN = 6          # 绿色背景判定：G 比 max(R,B) 大多少
SAT_MIN = 0.06            # 饱和度下限
BORDER_CUT = 3            # 视频边缘 1~2px 编码黑边，强制透明


# ---------------------------------------------------------------- 工具
def _tool(name: str) -> Optional[str]:
    """优先系统 PATH，其次程序目录 tools/（便于随文件夹一起搬走）。"""
    exe = shutil.which(name)
    if exe:
        return exe
    local = os.path.join(const.BASE_DIR, "tools", name + ".exe")
    return local if os.path.exists(local) else None


def _ffmpeg() -> Optional[str]:
    return _tool("ffmpeg")


def _ffprobe() -> Optional[str]:
    return _tool("ffprobe")


def _run(args: List[str]) -> bool:
    try:
        r = subprocess.run(args, capture_output=True, timeout=600)
        return r.returncode == 0
    except Exception as e:
        log.warning("命令失败 %s：%s", args[0], e)
        return False


def movie_dir(name: str) -> str:
    return os.path.join(const.MOVIE_DIR, name)


def meta_path(name: str) -> str:
    return os.path.join(movie_dir(name), "meta.json")


def list_sources() -> List[Tuple[str, str]]:
    d = const.SRC_MOVIES
    if not os.path.isdir(d):
        return []
    out: List[Tuple[str, str]] = []
    for f in sorted(os.listdir(d)):
        if f.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
            out.append((os.path.splitext(f)[0], os.path.join(d, f)))
    return out


def _signature(path: str) -> str:
    st = os.stat(path)
    return f"{int(st.st_mtime)}-{st.st_size}"


# ---------------------------------------------------------------- 抠图
def _erode(m):
    import numpy as np
    e = m.copy()
    for sh in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        e &= np.roll(m, sh, (0, 1))
    return e


def _dilate(m):
    import numpy as np
    d = m.copy()
    for sh in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d |= np.roll(m, sh, (0, 1))
    return d


def key_image(img):
    """把纯绿背景的帧抠成 RGBA（返回 numpy uint8 HxWx4）。"""
    import numpy as np
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    mx = a.max(2)
    mn = a.min(2)
    sat = (mx - mn) / np.maximum(mx, 1.0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    bg_like = (g - np.maximum(r, b) > GREEN_MARGIN) & (sat > SAT_MIN)
    fg = ~bg_like
    fg = _dilate(_erode(fg))          # 去孤点
    fg = _erode(fg)                   # 收掉 1px 绿边
    fg[:BORDER_CUT] = False
    fg[-BORDER_CUT:] = False
    fg[:, :BORDER_CUT] = False
    fg[:, -BORDER_CUT:] = False
    g2 = np.minimum(g, np.maximum(r, b) + 8)      # 去绿边溢色
    rgb = np.clip(np.dstack([r, g2, b]), 0, 255).astype(np.uint8)
    alpha = (fg * 255).astype(np.uint8)
    return np.dstack([rgb, alpha])


# ---------------------------------------------------------------- 处理
def _process(ffm: str, name: str, src: str) -> Optional[dict]:
    from PIL import Image
    import numpy as np

    out = movie_dir(name)
    tmp = out + "_tmp"
    raw_dir = os.path.join(tmp, "raw")
    keyed_dir = os.path.join(tmp, "keyed")
    final_dir = os.path.join(tmp, "frames")
    shutil.rmtree(tmp, ignore_errors=True)
    for d in (raw_dir, keyed_dir, final_dir):
        os.makedirs(d, exist_ok=True)

    # 1) 拆帧
    if not _run([ffm, "-y", "-v", "error", "-i", src,
                 "-vf", f"fps={FRAME_FPS}", "-pix_fmt", "rgb24",
                 os.path.join(raw_dir, "r%04d.png")]):
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    raws = sorted(f for f in os.listdir(raw_dir) if f.endswith(".png"))
    if not raws:
        shutil.rmtree(tmp, ignore_errors=True)
        return None

    # 2) 抠图
    keyed: List[str] = []
    union = None
    for i, fn in enumerate(raws):
        with Image.open(os.path.join(raw_dir, fn)) as im:
            rgba = key_image(im)
        p = os.path.join(keyed_dir, f"k{i:04d}.png")
        Image.fromarray(rgba, "RGBA").save(p)
        keyed.append(p)
        ys, xs = np.where(rgba[..., 3] > 20)
        if len(xs):
            bb = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            if union is None:
                union = bb
            else:
                union = (min(union[0], bb[0]), min(union[1], bb[1]),
                         max(union[2], bb[2]), max(union[3], bb[3]))
    if union is None:
        shutil.rmtree(tmp, ignore_errors=True)
        return None

    # 3) 全片统一裁剪 + 等比缩放到固定高度
    pad = 6
    with Image.open(keyed[0]) as im0:
        src_w, src_h = im0.size
    x0 = max(0, union[0] - pad)
    y0 = max(0, union[1] - pad)
    x1 = min(src_w, union[2] + 1 + pad)
    y1 = min(src_h, union[3] + 1 + pad)
    cw, ch = x1 - x0, y1 - y0
    tw = max(1, int(round(cw * TARGET_H / max(1, ch))))
    th = TARGET_H
    for i, p in enumerate(keyed):
        with Image.open(p) as im:
            fr = im.crop((x0, y0, x1, y1)).resize((tw, th), Image.LANCZOS)
            fr.save(os.path.join(final_dir, f"f{i:04d}.png"))

    # 4) 音频
    wav = os.path.join(tmp, "audio.wav")
    has_audio = True
    probe = _ffprobe()
    if probe:
        try:
            r = subprocess.run([probe, "-v", "error", "-select_streams", "a",
                                "-show_entries", "stream=codec_type",
                                "-of", "csv=p=0", src],
                               capture_output=True, text=True, timeout=30)
            has_audio = "audio" in (r.stdout or "")
        except Exception:
            has_audio = False
    if has_audio:
        has_audio = _run([ffm, "-y", "-v", "error", "-i", src, "-vn",
                          "-ac", "2", "-ar", "32000", "-c:a", "pcm_s16le", wav])
    if not has_audio and os.path.exists(wav):
        os.remove(wav)

    # 5) 落盘
    count = len(keyed)
    meta = {
        "name": name,
        "sig": _signature(src),
        "fps": FRAME_FPS,
        "count": count,
        "width": tw,
        "height": th,
        "target_h": TARGET_H,
        "duration": count / FRAME_FPS,
        "audio": "audio.wav" if has_audio else "",
        "source": os.path.basename(src),
    }
    with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    # 丢弃中间产物，只保留最终帧 + 音频 + meta
    shutil.rmtree(raw_dir, ignore_errors=True)
    shutil.rmtree(keyed_dir, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    os.replace(tmp, out)
    log.info("动作视频已处理：%s（%d 帧 %dx%d 音频=%s）", name, count, tw, th, has_audio)
    return meta


def ensure_processed(force: bool = False) -> Dict[str, dict]:
    """处理所有源视频（带签名缓存）；返回 {名字: meta}。"""
    result: Dict[str, dict] = {}
    ffm = _ffmpeg()
    if not ffm:
        log.warning("未找到 ffmpeg，无法处理动作视频")
        return result
    for name, src in list_sources():
        try:
            mp = meta_path(name)
            sig = _signature(src)
            if not force and os.path.exists(mp) and os.path.isdir(
                    os.path.join(movie_dir(name), "frames")):
                with open(mp, encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("sig") == sig and meta.get("count"):
                    result[name] = meta
                    continue
            meta = _process(ffm, name, src)
            if meta:
                result[name] = meta
        except Exception as e:
            log.warning("动作视频处理失败 %s：%s", name, e)
            shutil.rmtree(movie_dir(name) + "_tmp", ignore_errors=True)
    return result


# ---------------------------------------------------------------- 运行时
class MovieLibrary:
    """只读缓存：读取已处理好的动作视频元数据，并提供帧路径/音频对象。"""

    def __init__(self) -> None:
        self.clips: Dict[str, dict] = {}
        self.sounds: Dict[str, object] = {}
        self.reload()

    def reload(self) -> None:
        clips: Dict[str, dict] = {}
        root = const.MOVIE_DIR
        if os.path.isdir(root):
            for name in sorted(os.listdir(root)):
                mp = meta_path(name)
                if not os.path.exists(mp):
                    continue
                try:
                    with open(mp, encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("count") and os.path.isdir(
                            os.path.join(movie_dir(name), "frames")):
                        clips[name] = meta
                except Exception:
                    pass
        self.clips = clips

    def has(self, name: str) -> bool:
        return name in self.clips

    def names(self) -> List[str]:
        return list(self.clips)

    def frame_path(self, name: str, idx: int) -> str:
        return os.path.join(movie_dir(name), "frames", f"f{idx:04d}.png")

    def wav_path(self, name: str) -> str:
        meta = self.clips.get(name) or {}
        if not meta.get("audio"):
            return ""
        p = os.path.join(movie_dir(name), meta["audio"])
        return p if os.path.exists(p) else ""

    def sound(self, name: str, volume: float):
        """惰性创建并缓存 QSoundEffect（第一次播放时初始化，省启动时间）。"""
        s = self.sounds.get(name)
        if s is None:
            wav = self.wav_path(name)
            if not wav:
                return None
            try:
                from PyQt6.QtCore import QUrl
                from PyQt6.QtMultimedia import QSoundEffect
                s = QSoundEffect()
                s.setSource(QUrl.fromLocalFile(wav))
                self.sounds[name] = s
            except Exception as e:
                log.warning("动作声音初始化失败：%s", e)
                return None
        try:
            s.setVolume(max(0.0, min(1.0, float(volume))))
        except Exception:
            pass
        return s

    def set_volume(self, volume: float) -> None:
        v = max(0.0, min(1.0, float(volume)))
        for s in self.sounds.values():
            try:
                s.setVolume(v)
            except Exception:
                pass
