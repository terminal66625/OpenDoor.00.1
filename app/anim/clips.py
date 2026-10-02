# -*- coding: utf-8 -*-
"""动作片段定义与动作状态机（Idle / 点击 / 思考 / 走路 ...）。

状态机负责：播放速度、循环、以及动作之间的淡入淡出混合（blending）。
不依赖任何 Qt 绑定，可在 PyQt6 / PySide6 / 无界面环境下复用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ClipSpec:
    name: str
    fps: float = 10.0
    loop: bool = True
    inbetweens: int = 6
    mode: str = "warp"          # warp / dissolve / cut
    next_state: Optional[str] = None   # 非循环播完后自动切到的状态


# 内置动作表（与 assets/anim_frames/<name>/ 对应）
DEFAULT_CLIPS: Dict[str, ClipSpec] = {
    "idle":  ClipSpec("idle",  fps=8.0,  loop=True,  inbetweens=6, mode="warp"),
    "walk":  ClipSpec("walk",  fps=10.0, loop=True,  inbetweens=8, mode="warp"),
    "click": ClipSpec("click", fps=12.0, loop=False, inbetweens=5, mode="warp",
                      next_state="idle"),
    "think": ClipSpec("think", fps=6.0,  loop=True,  inbetweens=8, mode="dissolve"),
}


@dataclass
class FrameState:
    """当前应显示的帧信息（供渲染层使用）。"""
    clip: str = "idle"
    index: int = 0
    count: int = 1
    prev_clip: Optional[str] = None
    prev_index: int = 0
    blend: float = 1.0          # 1=完全当前动作，0=完全上一个动作


class ActionStateMachine:
    """控制动作播放速度、循环、以及动作切换时的混合过渡。"""

    def __init__(self, clips: Optional[Dict[str, ClipSpec]] = None,
                 clip_lengths: Optional[Dict[str, int]] = None,
                 blend_time: float = 0.18) -> None:
        self.clips = dict(clips or DEFAULT_CLIPS)
        self.lengths: Dict[str, int] = dict(clip_lengths or {})
        self.current = "idle" if "idle" in self.clips else next(iter(self.clips))
        self.prev: Optional[str] = None
        self.time = 0.0
        self.prev_time = 0.0
        self.speed = 1.0
        self.blend_time = blend_time
        self._blend_t = blend_time

    # ------------------------------------------------------------ 控制
    def set_length(self, clip: str, count: int) -> None:
        self.lengths[clip] = max(1, int(count))

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.05, float(speed))

    def set_state(self, name: str, restart: bool = False) -> None:
        if name not in self.clips:
            return
        if name == self.current and not restart:
            return
        self.prev = self.current
        self.prev_time = self.time
        self.current = name
        self.time = 0.0
        self._blend_t = 0.0 if self.blend_time <= 0 else 0.0

    # ------------------------------------------------------------ 更新
    def update(self, dt: float) -> FrameState:
        spec = self.clips[self.current]
        length = self.lengths.get(self.current, 1)
        self.time += dt * self.speed * spec.fps

        if self.time >= length:
            if spec.loop:
                self.time %= length
            else:
                if spec.next_state and spec.next_state in self.clips:
                    self.set_state(spec.next_state)
                else:
                    self.time = length - 1
                    spec = self.clips[self.current]
                    length = self.lengths.get(self.current, 1)

        # 过渡混合
        if self.prev is not None:
            self._blend_t += dt
            if self._blend_t >= self.blend_time:
                self.prev = None
            blend = min(1.0, self._blend_t / max(1e-6, self.blend_time))
        else:
            blend = 1.0

        prev_index = 0
        if self.prev is not None:
            plen = self.lengths.get(self.prev, 1)
            prev_index = int(self.prev_time) % max(1, plen)

        return FrameState(
            clip=self.current, index=int(self.time) % max(1, length),
            count=length, prev_clip=self.prev, prev_index=prev_index,
            blend=blend,
        )
