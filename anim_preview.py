# -*- coding: utf-8 -*-
"""动作预览入口（独立运行，不影响桌宠主程序）。

用法：
    python anim_preview.py

首次运行会自动由形象生成关键帧并编译 Idle / 走路 / 点击 / 思考 四套动作。
也可把自己的关键帧 PNG 放进 assets/anim_frames/<动作名>/ 后，在窗口里点「生成当前动作」。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.anim import paths          # noqa: E402
from app.anim.bootstrap import compile_all, ensure_keyframes  # noqa: E402


def main() -> int:
    try:
        ensure_keyframes()
        root = paths.compiled_root()
        need = (not os.path.isdir(root)) or (not os.listdir(root))
        if need:
            compile_all()
    except Exception as e:
        print("初始化动画资源出错：", e)
    from app.anim.preview import run_preview
    return run_preview()


if __name__ == "__main__":
    raise SystemExit(main())
