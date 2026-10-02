# -*- coding: utf-8 -*-
"""动画模块用的路径（复用主程序 const.ASSETS_DIR，不修改原有代码）。"""
import os


def anim_root() -> str:
    try:
        from .. import const
        base = const.ASSETS_DIR
    except Exception:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets")
    return os.path.join(base, "anim_frames")


def compiled_root() -> str:
    return os.path.join(anim_root(), "_compiled")
