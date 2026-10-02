# -*- coding: utf-8 -*-
"""为桌宠准备动作关键帧并编译动画。

由于当前没有可用的本地图像生成模型，这里以「现有形象 body.png」为基础，
用平移/旋转/挤压拉伸生成每个动作的关键帧（真实可用的动作，而非凭空生成）。
用户也可以把自己的关键帧直接放进 assets/anim_frames/<动作名>/ 覆盖生成结果。
"""
from __future__ import annotations

import os
from typing import Dict, List, Tuple

from PIL import Image

from . import paths, png_seq

# 每个动作的关键帧变换：(dx, dy, 角度, 横向缩放, 纵向缩放)
# dx/dy 为像素位移，正数向右/向下
KEYFRAME_TRANSFORMS: Dict[str, List[Tuple[float, float, float, float, float]]] = {
    "idle":  [(0, 0, 0, 1.0, 1.0), (0, -6, 0, 1.0, 1.0),
              (0, 0, 0, 1.0, 1.0), (0, 4, 0, 1.0, 1.0)],
    "walk":  [(5, 0, 5, 1.0, 1.0), (0, -4, 0, 1.0, 1.0),
              (-5, 0, -5, 1.0, 1.0), (0, -4, 0, 1.0, 1.0)],
    "click": [(0, 0, 0, 1.0, 1.0), (0, 9, 0, 1.14, 0.86),
              (0, -7, 0, 0.95, 1.06), (0, 0, 0, 1.0, 1.0)],
    "think": [(0, 0, 0, 1.0, 1.0), (4, -2, 6, 1.0, 1.0),
              (-4, -2, -6, 1.0, 1.0)],
}

PAD = 56


def _render(base: Image.Image, size, dx=0.0, dy=0.0,
            angle=0.0, sx=1.0, sy=1.0) -> Image.Image:
    w = max(1, int(round(base.width * sx)))
    h = max(1, int(round(base.height * sy)))
    img = base.resize((w, h), Image.LANCZOS)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (size[0] - img.width) // 2 + int(round(dx))
    y = (size[1] - img.height) // 2 + int(round(dy))
    canvas.paste(img, (x, y), img)
    return canvas


def _base_image() -> Image.Image:
    try:
        from .. import const
        path = const.BODY_PATH
        if os.path.exists(path):
            with Image.open(path) as im:
                return im.convert("RGBA").copy()
    except Exception:
        pass
    # 占位
    img = Image.new("RGBA", (240, 360), (0, 0, 0, 0))
    return img


def ensure_keyframes(force: bool = False, root: str = None) -> Dict[str, List[str]]:
    """生成各动作关键帧到 assets/anim_frames/<动作>/。"""
    root = root or paths.anim_root()
    os.makedirs(root, exist_ok=True)
    base = _base_image()
    size = (base.width + PAD * 2, base.height + PAD * 2)
    result: Dict[str, List[str]] = {}
    for action, transforms in KEYFRAME_TRANSFORMS.items():
        d = os.path.join(root, action)
        os.makedirs(d, exist_ok=True)
        existing = png_seq.list_keyframes(d)
        if existing and not force:
            result[action] = existing
            continue
        for old in os.listdir(d):
            if old.lower().endswith(".png"):
                try:
                    os.remove(os.path.join(d, old))
                except OSError:
                    pass
        made = []
        for i, (dx, dy, ang, sx, sy) in enumerate(transforms):
            frame = _render(base, size, dx, dy, ang, sx, sy)
            p = os.path.join(d, f"{i:02d}.png")
            frame.save(p)
            made.append(p)
        result[action] = made
    return result


def compile_all(root: str = None, fps: float = 10.0, force: bool = False) -> Dict[str, dict]:
    """生成关键帧并编译为完整动画（PNG 序列 + APNG + GIF）。"""
    root = root or paths.anim_root()
    compiled_root = paths.compiled_root()
    clips = {
        "idle":  dict(fps=8.0,  inbetweens=6, mode="warp",  loop=True),
        "walk":  dict(fps=10.0, inbetweens=8, mode="warp",  loop=True),
        "click": dict(fps=12.0, inbetweens=5, mode="warp",  loop=False),
        "think": dict(fps=6.0,  inbetweens=8, mode="dissolve", loop=True),
    }
    kf = ensure_keyframes(force=force, root=root)
    results: Dict[str, dict] = {}
    for name, spec in clips.items():
        keyframes = kf.get(name, [])
        if not keyframes:
            continue
        res = png_seq.compile_clip(name, keyframes, compiled_root, **spec)
        results[name] = res
    return results


if __name__ == "__main__":
    for k, v in compile_all(force=True).items():
        print(k, "->", v.get("frames"), "frames", v.get("apng"), v.get("gif"))
