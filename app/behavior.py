# -*- coding: utf-8 -*-
"""桌宠行为状态机 + 本地兜底引擎。

- 校验大模型返回的 JSON（缺字段自动补全）。
- 模型不可用时，用本地伪随机规则产生同样格式的行为，保证桌宠永远在动。
"""
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from . import const
from .persona import RESPONSIBILITY, VALID_ACTIONS

WALK_ACTIONS = {"crawl_left", "crawl_right", "run_away"}
IDLE_ACTIONS = {"idle_stand", "idle_sit", "idle_sleep"}


@dataclass
class PetState:
    action: str = "idle_stand"
    heading: int = 0
    speed: float = 0.8
    remaining: int = 20              # 剩余 tick
    idle_streak: int = 0
    memory: str = "刚出现在主人的桌面上"
    consecutive_crawl: int = 0
    last_dir: int = 0                # -1 左, 1 右, 0 无


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def validate(obj: Dict[str, Any], prev: PetState) -> Optional[PetState]:
    """把模型输出转成安全的 PetState；非法则返回 None。"""
    if not isinstance(obj, dict):
        return None
    action = str(obj.get("action", "")).strip()
    if action not in VALID_ACTIONS:
        return None
    try:
        heading = int(float(obj.get("heading", prev.heading)))
    except Exception:
        heading = prev.heading
    heading %= 360
    try:
        speed = float(obj.get("speedMultiplier", prev.speed))
    except Exception:
        speed = prev.speed
    speed = _clamp(speed, 0.3, 1.8)
    # 速度平滑：相邻变化 ≤0.3
    if abs(speed - prev.speed) > 0.3:
        speed = prev.speed + 0.3 * (1 if speed > prev.speed else -1)
    try:
        timer = int(float(obj.get("stateTimer", 20)))
    except Exception:
        timer = 20
    lo, hi = RESPONSIBILITY.get(action, (10, 40))
    timer = _clamp(timer, lo, hi)
    if action == "jump":
        timer = 6
    if action == "run_away":
        speed = max(speed, 1.3)

    st = PetState(
        action=action, heading=heading, speed=round(speed, 2),
        remaining=timer, idle_streak=prev.idle_streak,
        memory=str(obj.get("memory", prev.memory))[:80],
        consecutive_crawl=prev.consecutive_crawl, last_dir=prev.last_dir,
    )
    if action in WALK_ACTIONS:
        st.consecutive_crawl = prev.consecutive_crawl + 1
        st.last_dir = 1 if heading < 180 else -1
        st.idle_streak = 0
    elif action in IDLE_ACTIONS:
        st.idle_streak = prev.idle_streak + 1
        st.consecutive_crawl = 0
    else:
        st.consecutive_crawl = 0
    return st


class LocalBrain:
    """本地兜底：完全遵循用户给的随机规则。"""

    def choose(self, prev: PetState, x: float, y: float,
               left: int, right: int, top: int, bottom: int,
               mouse: Optional[Tuple[int, int]]) -> PetState:
        ts = int(__import__("time").time())
        rand = (ts * 7 + prev.remaining * 13) % 100

        # 1) 鼠标太近 -> 逃跑（最高优先级）
        if mouse is not None:
            mx, my = mouse
            if math.hypot(mx - x, my - y) < const.MOUSE_FLEE_DIST:
                away = math.degrees(math.atan2(y - my, x - mx)) % 360
                return self._mk("run_away", away, 1.5, 12, "被主人凑近吓到啦")

        # 2) 贴边 -> 强制转向内侧
        if x - left < const.SAFE_MARGIN_X:
            return self._mk("crawl_right", 0, 0.9, random.randint(25, 45), "撞到左边了，往回游")
        if right - x < const.SAFE_MARGIN_X:
            return self._mk("crawl_left", 180, 0.9, random.randint(25, 45), "右边是墙，掉头")
        if y - top < const.SAFE_MARGIN_Y:
            return self._mk("crawl_left", 0, 0.8, random.randint(20, 35), "上面没路了")
        if bottom - y < const.SAFE_MARGIN_Y:
            return self._mk("look_up", 270, 0.6, random.randint(5, 10), "下面挤挤的")

        # 3) 随机特殊动作
        if rand < 5:
            act = random.choice(["jump", "stretch", "sniff"])
            dur = RESPONSIBILITY[act][0]
            return self._mk(act, prev.heading, 0.8, dur, random.choice(
                ["突然想蹦一下", "伸个懒腰", "闻闻地面"]))
        if 5 <= rand <= 15 and prev.action not in IDLE_ACTIONS:
            return self._mk(random.choice(["idle_stand", "idle_sit"]),
                            prev.heading, 0.5, random.randint(15, 30), "累了歇一会儿")

        # 4) 自然延续
        if prev.remaining > 0:
            return prev

        # 5) 随机选择
        if prev.idle_streak >= 2 and random.random() < 0.4:
            return self._mk("idle_sleep", prev.heading, 0.3, random.randint(30, 70), "困了，眯一会儿")
        if prev.action == "idle_sleep":
            return self._mk("stretch", prev.heading, 0.4, random.randint(10, 16), "睡醒啦，伸懒腰")
        if random.random() < 0.55:
            left_ok = prev.last_dir <= 0
            going_left = random.random() < 0.5 if left_ok else False
            if prev.last_dir > 0:
                going_left = random.random() < 0.7
            act = "crawl_left" if going_left else "crawl_right"
            head = 180 if going_left else 0
            head += random.randint(-20, 20)
            return self._mk(act, head % 360, random.uniform(0.7, 1.0),
                            random.randint(25, 55), "随便游一游")
        return self._mk(random.choice(["idle_stand", "look_around", "look_up", "sniff"]),
                        prev.heading, 0.6, random.randint(8, 20), "发呆中")

    def _mk(self, action, heading, speed, timer, memory) -> PetState:
        lo, hi = RESPONSIBILITY.get(action, (8, 40))
        timer = _clamp(int(timer), lo, hi)
        if action == "jump":
            timer = 6
        if action == "run_away":
            speed = max(speed, 1.3)
        return PetState(action=action, heading=int(heading) % 360,
                        speed=round(float(speed), 2), remaining=timer,
                        memory=memory)
