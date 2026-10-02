# -*- coding: utf-8 -*-
"""PNG 序列读写与动画打包：apngasm-python（APNG）+ Pillow（GIF / 兜底 APNG）。"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from PIL import Image

from .interpolate import build_sequence, normalize_canvas


# ---------------------------------------------------------------- 读写
def load_pngs(paths: Sequence[str]) -> List[Image.Image]:
    out = []
    for p in paths:
        with Image.open(p) as im:
            out.append(im.convert("RGBA").copy())
    return out


def list_keyframes(action_dir: str, prefix: Optional[str] = None) -> List[str]:
    if not os.path.isdir(action_dir):
        return []
    files = [f for f in os.listdir(action_dir)
             if f.lower().endswith(".png") and (prefix is None or f.startswith(prefix))]
    return [os.path.join(action_dir, f) for f in sorted(files)]


def save_png_sequence(frames: Sequence[Image.Image], out_dir: str,
                      prefix: str = "f") -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):
        if old.lower().endswith(".png"):
            try:
                os.remove(os.path.join(out_dir, old))
            except OSError:
                pass
    paths = []
    for i, im in enumerate(frames):
        p = os.path.join(out_dir, f"{prefix}{i:04d}.png")
        im.convert("RGBA").save(p)
        paths.append(p)
    return paths


# ---------------------------------------------------------------- APNG
def assemble_apng(frame_paths: Sequence[str], out_path: str,
                  fps: float = 10.0, loops: int = 0) -> bool:
    """优先 apngasm-python；不可用时用 Pillow 保存 APNG。"""
    delay_ms = max(1, int(round(1000.0 / max(0.1, fps))))
    try:
        from apngasm_python.apngasm import APNGAsm  # type: ignore
        asm = APNGAsm()
        for p in frame_paths:
            asm.add_frame_from_file(p, delay_ms, 1000)
        asm.set_loops(loops)
        if asm.assemble(out_path) and os.path.exists(out_path):
            return True
    except Exception:
        pass
    # Pillow 兜底（Pillow >= 8 原生支持 APNG）
    try:
        frames = load_pngs(frame_paths)
        frames[0].save(out_path, format="PNG", save_all=True,
                       append_images=frames[1:], duration=delay_ms,
                       loop=loops, disposal=1, blend=0)
        return os.path.exists(out_path)
    except Exception:
        return False


# ---------------------------------------------------------------- GIF
def assemble_gif(frames: Sequence[Image.Image], out_path: str,
                 fps: float = 10.0, loops: int = 0,
                 alpha_threshold: int = 128) -> bool:
    """输出带透明通道的 GIF（索引 255 作为透明色，保留角色背景透明）。"""
    try:
        delay_ms = max(20, int(round(1000.0 / max(0.1, fps))))
        rgba_frames = [im.convert("RGBA") for im in frames]
        # 用第一帧建立统一调色板（预留 255 号索引给透明色）
        base = rgba_frames[0].convert("RGB").quantize(
            colors=255, method=Image.Quantize.MEDIANCUT)
        pal = list(base.getpalette() or [])
        if len(pal) < 256 * 3:
            pal += [0, 0, 0] * (256 - len(pal) // 3)
        base.putpalette(pal)

        converted = []
        for rgba in rgba_frames:
            p = rgba.convert("RGB").quantize(palette=base, dither=Image.Dither.NONE)
            p.putpalette(pal)
            alpha = rgba.getchannel("A")
            mask = alpha.point(lambda a: 255 if a < alpha_threshold else 0)
            p.paste(255, mask=mask)          # 透明像素 -> 255 号索引
            converted.append(p)

        converted[0].save(
            out_path, save_all=True, append_images=converted[1:],
            duration=delay_ms, loop=loops, disposal=2,
            transparency=255, optimize=False)
        return os.path.exists(out_path)
    except Exception:
        return False


# ---------------------------------------------------------------- 编译
def compile_clip(name: str, keyframe_paths: Sequence[str], out_root: str,
                 fps: float = 10.0, inbetweens: int = 6, mode: str = "warp",
                 loop: bool = True, loops: int = 0) -> Dict[str, object]:
    """把某个动作的关键帧编译为完整动画（PNG 序列 + APNG + GIF）。"""
    kfs = load_pngs(keyframe_paths)
    if not kfs:
        return {"name": name, "ok": False, "reason": "没有关键帧"}
    seq = build_sequence(kfs, inbetweens=inbetweens, mode=mode, loop=loop)
    clip_dir = os.path.join(out_root, name)
    frame_paths = save_png_sequence(seq, clip_dir, prefix="f")
    apng = os.path.join(clip_dir, f"{name}.png")
    gif = os.path.join(clip_dir, f"{name}.gif")
    ok_apng = assemble_apng(frame_paths, apng, fps=fps, loops=loops)
    ok_gif = assemble_gif(seq, gif, fps=fps, loops=loops)
    return {
        "name": name, "ok": True, "frames": len(seq),
        "png_dir": clip_dir, "apng": apng if ok_apng else None,
        "gif": gif if ok_gif else None, "fps": fps,
        "inbetweens": inbetweens, "mode": mode,
    }
