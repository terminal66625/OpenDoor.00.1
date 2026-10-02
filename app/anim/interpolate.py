# -*- coding: utf-8 -*-
"""关键帧插值：在两张 PNG 关键帧之间生成平滑中间帧（纯 CPU）。

模式：
    "dissolve" 淡化：交叉混合，实现简单，快速动作时可能有重影
    "warp"     对齐插值（默认）：先把主体位移/缩放到中间位置再混合，重影更少
    "cut"      不插值：直接切换（保留关键帧原样）

依赖：Pillow（必需）、numpy（推荐，用于防止透明边缘出现黑边/光晕）
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

from PIL import Image

try:
    import numpy as _np
except Exception:                       # numpy 不可用时退化到 Pillow 混合
    _np = None

MODES = ("warp", "dissolve", "cut")


# ---------------------------------------------------------------- 基础工具
def _ease(t: float) -> float:
    """smoothstep 缓入缓出，让补间不那么机械。"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _to_np(img: Image.Image):
    return _np.asarray(img.convert("RGBA"), dtype=_np.float32) / 255.0


def _to_img(arr) -> Image.Image:
    return Image.fromarray((_np.clip(arr, 0.0, 1.0) * 255.0).astype(_np.uint8), "RGBA")


def blend(a: Image.Image, b: Image.Image, t: float) -> Image.Image:
    """按 t 在 a、b 之间做（带透明度的）线性混合，无黑边。"""
    t = max(0.0, min(1.0, t))
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    if _np is None:
        return Image.blend(a.convert("RGBA"), b.convert("RGBA"), t)
    A, B = _to_np(a), _to_np(b)
    aa, ba = A[..., 3:4], B[..., 3:4]
    rgb = (1.0 - t) * (A[..., :3] * aa) + t * (B[..., :3] * ba)
    alpha = (1.0 - t) * aa + t * ba
    out = _np.concatenate([rgb / _np.maximum(alpha, 1e-6), alpha], axis=2)
    return _to_img(out)


def subject_box(img: Image.Image, thr: int = 8) -> Tuple[int, int, int, int]:
    """主体（非透明区域）的包围盒；找不到就返回整张图。"""
    img = img.convert("RGBA")
    if _np is not None:
        a = _np.asarray(img)[..., 3]
        ys, xs = _np.where(a > thr)
        if len(xs) == 0:
            return (0, 0, img.width, img.height)
        return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    bbox = img.getbbox()
    return bbox or (0, 0, img.width, img.height)


def normalize_canvas(images: Sequence[Image.Image]) -> List[Image.Image]:
    """把序列统一到同一画布大小（居中，不缩放），保证可以叠加/打包。"""
    images = [im.convert("RGBA") for im in images]
    w = max(im.width for im in images)
    h = max(im.height for im in images)
    out = []
    for im in images:
        if im.width == w and im.height == h:
            out.append(im)
            continue
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.paste(im, ((w - im.width) // 2, (h - im.height) // 2), im)
        out.append(canvas)
    return out


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _warp_subject(img: Image.Image, src_box, dst_box, size) -> Image.Image:
    """把 img 的主体从 src_box 平移到并缩放到 dst_box。"""
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    crop = img.crop(tuple(int(v) for v in src_box))
    dw = max(1, int(round(dst_box[2] - dst_box[0])))
    dh = max(1, int(round(dst_box[3] - dst_box[1])))
    crop = crop.resize((dw, dh), Image.LANCZOS)
    out.paste(crop, (int(round(dst_box[0])), int(round(dst_box[1]))), crop)
    return out


# ---------------------------------------------------------------- 插值
def interpolate_pair(a: Image.Image, b: Image.Image, count: int,
                     mode: str = "warp") -> List[Image.Image]:
    """在 a、b 之间生成 count 张中间帧（不含首尾）。"""
    if count <= 0 or mode == "cut":
        return []
    a, b = a.convert("RGBA"), b.convert("RGBA")
    size = (max(a.width, b.width), max(a.height, b.height))
    if (a.width, a.height) != size or (b.width, b.height) != size:
        a, b = normalize_canvas([a, b])

    frames: List[Image.Image] = []
    if mode == "warp":
        box_a, box_b = subject_box(a), subject_box(b)
    for i in range(1, count + 1):
        t = _ease(i / (count + 1))
        if mode == "warp":
            box_t = tuple(_lerp(box_a[k], box_b[k], t) for k in range(4))
            wa = _warp_subject(a, box_a, box_t, size)
            wb = _warp_subject(b, box_b, box_t, size)
            frames.append(blend(wa, wb, t))
        else:  # dissolve
            frames.append(blend(a, b, t))
    return frames


def build_sequence(keyframes: Sequence[Image.Image], inbetweens: int = 6,
                   mode: str = "warp", loop: bool = False) -> List[Image.Image]:
    """由关键帧序列生成完整动画帧序列。

    loop=True 时会额外补上「最后一帧 -> 第一帧」的过渡，循环更顺滑。
    """
    if not keyframes:
        return []
    kfs = normalize_canvas(keyframes)
    if len(kfs) == 1:
        return kfs
    out: List[Image.Image] = [kfs[0]]
    for i in range(len(kfs) - 1):
        out.extend(interpolate_pair(kfs[i], kfs[i + 1], inbetweens, mode))
        out.append(kfs[i + 1])
    if loop and inbetweens > 0 and mode != "cut":
        out.extend(interpolate_pair(kfs[-1], kfs[0], inbetweens, mode))
    return out
