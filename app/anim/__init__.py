# -*- coding: utf-8 -*-
"""动画帧插值子模块（独立于桌宠主程序，可单独运行）。

工作流程：
    关键帧 PNG 序列 -> 纯 CPU 插值生成中间帧 -> 打包 APNG / GIF -> 预览播放。

- 插值：淡化（dissolve）或 位移+缩放对齐插值（warp，默认，可减少重影）
- 打包：apngasm-python 生成 APNG，Pillow 生成 GIF / PNG 序列
- 说明：本模块不做「大模型生成」，只负责在已有两张关键帧之间补帧。
"""
__all__ = ["interpolate", "png_seq", "clips", "bootstrap", "preview"]
__version__ = "1.0.0"
