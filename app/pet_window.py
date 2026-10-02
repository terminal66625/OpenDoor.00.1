# -*- coding: utf-8 -*-
"""桌宠主窗口：透明、无边框、置顶、可拖拽，承载动画与交互。"""
import math
import os
import random
import time
from typing import Dict, Optional

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QCursor, QFont, QIcon, QPainter, QPixmap,
                         QPainterPath, QColor, QPen, QBrush, QTransform)
from PyQt6.QtWidgets import (QApplication, QMenu, QPushButton, QWidget)

from . import const
from .behavior import LocalBrain, PetState, WALK_ACTIONS, validate
from .logging_setup import setup_logging
from .movies import MovieLibrary
from .util import read_json

log = setup_logging()


class PetWindow(QWidget):
    clicked = pyqtSignal()
    request_chat = pyqtSignal()
    request_settings = pyqtSignal(str)
    request_screenshot = pyqtSignal()
    request_balance = pyqtSignal()
    quick_action = pyqtSignal(str)      # vol_up/vol_down/bri_up/bri_down/todos
    say = pyqtSignal(str, str)          # 文本, 表情关键词
    moved = pyqtSignal(int, int)        # 桌宠位移增量，供浮窗跟随
    radial_menu_requested = pyqtSignal(QPoint)   # 请求半圆快捷面板

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.cfg = ctx.cfg
        self.memory = ctx.memory
        self.stickers = ctx.stickers

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)

        self._load_art()
        self._metrics()

        # 状态
        self.state = PetState()
        self.brain = LocalBrain()
        self.heading = self.state.heading
        self.target_heading = self.state.heading
        self._anim_t = 0.0
        self._blink = 0
        self._deform = [1.0, 1.0]         # 捏脸形变
        self._pressing_face = False
        self._press_pos = QPoint()
        self._moving_window = False
        self._win_drag_off = QPoint()
        self._press_started = time.time()
        self._did_drag = False
        self._last_tick = time.time()
        self._paused = False
        self._fullscreen = False
        self._bubble_text = ""
        self._bubble_until = 0.0
        self._zzz = 0.0
        self._cursor_eaten = False
        self._squash = 0.0

        # 动画片段（app/anim 生成的帧序列，预缩放 + 交叉淡化）
        self.clip_cache: Dict[str, list] = {}
        self.current_clip: Optional[str] = None
        self._clip_prev: Optional[str] = None
        self._clip_time = 0.0
        self._prev_clip_time = 0.0
        self._clip_blend = 1.0
        self._forced_clip: Optional[str] = None
        self._clip_forced_until = 0.0
        self._clip_set_at = 0.0          # 当前片段开始时间（限制切换频率）
        self._last_paint_idx = -1        # 上次绘制的帧序号（按帧重绘，避免抖动）
        self._facing = 1                 # 1 面朝右，-1 面朝左（走路镜像）

        # 动作视频（mp4 抠像后的透明帧 + 音频，与画面同步）
        self.movies = MovieLibrary()
        self._movie: Optional[dict] = None
        self._movie_name = ""
        self._movie_t0 = 0.0
        self._movie_end = 0.0
        self._movie_frames: Dict[int, QPixmap] = {}
        self._movie_order: list = []

        # 性能节流
        self._last_fs_check = 0.0
        self._last_idle_check = 0.0
        self._last_paint = 0.0
        self._idle_ms = 0
        self._last_move_pos: Optional[QPoint] = None
        self.vitality_factor = 1.0        # 活力影响移动速度（好感系统）
        self._shadow_pix: Optional[QPixmap] = None
        # 气泡淡入淡出
        self._bubble_shown_at = 0.0

        # 计时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(const.TICK_MS)
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._do_blink)
        self._blink_timer.start(3200)

        self._build_gear()
        self._place_initial()

        ctx.llm.behavior_ready.connect(self.on_behavior)

    # ------------------------------------------------------------ 资源
    def _load_art(self) -> None:
        from .assets import character_body, character_meta
        name = self.cfg.get("character", "大肥鱼")
        path = character_body(name)
        self.pix = QPixmap(path) if path and os.path.exists(path) else QPixmap()
        self.meta = character_meta(name)
        self.face_box = self.meta.get("face_box", [0.18, 0.02, 0.82, 0.30])

    def _metrics(self) -> None:
        scale = self.cfg.scale / 100.0
        base_w = self.pix.width() or 240
        base_h = self.pix.height() or 360
        self.base_w = base_w
        self.base_h = base_h
        self.draw_w = int(base_w * scale)
        self.draw_h = int(base_h * scale)
        self.pad = 40
        self.resize(self.draw_w + self.pad * 2, self.draw_h + self.pad * 2 + 18)
        self._shadow_pix = self._make_shadow(self.draw_w)
        cache = getattr(self, "clip_cache", None)
        if cache is not None and cache:
            cache.clear()
            self.current_clip = None
        if getattr(self, "_movie_frames", None):
            self._movie_frames.clear()
            self._movie_order.clear()
        self._apply_opacity()

    def _make_shadow(self, w: int) -> QPixmap:
        pm = QPixmap(max(1, w), 18)
        pm.fill(Qt.GlobalColor.transparent)
        sp = QPainter(pm)
        sp.setRenderHint(QPainter.RenderHint.Antialiasing)
        sp.setBrush(QColor(20, 40, 90, 60))
        sp.setPen(Qt.PenStyle.NoPen)
        sp.drawEllipse(0, 0, pm.width(), 18)
        sp.end()
        return pm

    def reload_art(self) -> None:
        self._load_art()
        self._metrics()
        self.clip_cache.clear()
        self.current_clip = None
        self._clip_prev = None
        self._clip_blend = 1.0
        self.update()

    def set_character(self, name: str) -> None:
        self.cfg.set("character", name)
        self.cfg.save()
        self.reload_art()
        self.show_bubble(f"本鱼换了个样子，主人喜欢吗？(๑•̀ㅂ•́)و", 4)

    # ------------------------------------------------------------ 动画片段
    CLIP_FOR_ACTION = {
        "crawl_left": "walk", "crawl_right": "walk", "run_away": "walk",
        "jump": "click", "stretch": "click",
        "look_up": "think", "look_around": "idle",   # 张望归入 idle，减少频繁切换
        "idle_stand": "idle", "idle_sit": "idle", "idle_sleep": "idle",
        "sniff": "idle",
    }

    CLIP_FPS = {"idle": 8.0, "walk": 10.0, "click": 12.0, "think": 6.0}
    CLIP_BLEND = 0.12          # 动作切换时的交叉淡化时长(秒)
    CLIP_MIN_HOLD = 0.6        # 同一片段至少保持多久才允许再切换（防闪烁）

    def _anim_enabled(self) -> bool:
        if not self.cfg.get("use_anim_clips", True):
            return False
        return self.cfg.get("character", "大肥鱼") == "大肥鱼"

    def _clip_files(self, name: str) -> list:
        try:
            from .anim import paths as anim_paths
            d = os.path.join(anim_paths.compiled_root(), name)
            if not os.path.isdir(d):
                return []
            return [os.path.join(d, f) for f in sorted(os.listdir(d))
                    if f.startswith("f") and f.endswith(".png")]
        except Exception:
            return []

    def _load_clip(self, name: str) -> list:
        if name in self.clip_cache:
            return self.clip_cache[name]
        files = self._clip_files(name)
        if not files:
            self.clip_cache[name] = []
            return []
        first = QPixmap(files[0])
        if first.isNull():
            self.clip_cache[name] = []
            return []
        # 按当前显示尺寸预缩放，播放时零缩放开销
        kw = max(1, int(self.draw_w * (first.width() / max(1, self.base_w))))
        kh = max(1, int(self.draw_h * (first.height() / max(1, self.base_h))))
        frames = []
        for p in files:
            pm = QPixmap(p)
            if pm.isNull():
                continue
            if pm.width() != kw or pm.height() != kh:
                pm = pm.scaled(kw, kh, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            frames.append(pm)
        self.clip_cache[name] = frames
        self._evict_clips()
        return frames

    def _evict_clips(self) -> None:
        keep = {self.current_clip, self._clip_prev, "idle"}
        for k in list(self.clip_cache.keys()):
            if k not in keep:
                self.clip_cache.pop(k, None)

    def _set_clip(self, name: Optional[str]) -> None:
        if name == self.current_clip:
            return
        # 若上一次交叉淡化还没结束，先直接结束它，避免多次淡化叠加造成闪烁
        if self._clip_prev is not None and self._clip_blend < 1.0:
            self._clip_prev = None
            self._clip_blend = 1.0
        if self.current_clip and name:
            self._clip_prev = self.current_clip
            self._prev_clip_time = self._clip_time
            self._clip_blend = 0.0
        else:
            self._clip_prev = None
            self._clip_blend = 1.0
        self.current_clip = name
        self._clip_time = 0.0
        self._clip_set_at = time.time()
        self._last_paint_idx = -1
        if name:
            self._load_clip(name)
        self.update()

    def _advance_clip(self, dt: float) -> None:
        if self._clip_prev:
            self._clip_blend = min(1.0, self._clip_blend + dt / max(0.01, self.CLIP_BLEND))
            if self._clip_blend >= 1.0:
                self._clip_prev = None
        if not self.current_clip:
            return
        frames = self.clip_cache.get(self.current_clip) or []
        if not frames:
            return
        fps = self.CLIP_FPS.get(self.current_clip, 10.0)
        self._clip_time += dt * fps
        if self._clip_time >= len(frames):
            self._clip_time %= len(frames)

    def _desired_clip(self) -> Optional[str]:
        if not self._anim_enabled():
            return None
        if time.time() < self._clip_forced_until and self._forced_clip:
            return self._forced_clip
        return self.CLIP_FOR_ACTION.get(self.state.action, "idle")

    def _force_clip(self, name: str, seconds: Optional[float] = None) -> None:
        self._forced_clip = name
        if seconds is None:
            frames = self.clip_cache.get(name) or self._load_clip(name)
            fps = self.CLIP_FPS.get(name, 10.0)
            seconds = (len(frames) / fps) if frames else 1.0
        self._clip_forced_until = time.time() + max(0.3, float(seconds))
        self._set_clip(name)

    # ------------------------------------------------------------ 动作视频
    def reload_movies(self) -> None:
        try:
            self.movies.reload()
        except Exception:
            pass

    def has_movie(self, name: str) -> bool:
        return self.movies.has(name)

    @property
    def movie_active(self) -> bool:
        return self._movie is not None

    def play_movie(self, name: str) -> bool:
        """播放一段动作视频（透明帧 + 同步音频）；返回是否成功开始。"""
        if not self.cfg.get("use_movies", True):
            return False
        clip = self.movies.clips.get(name)
        if not clip:
            return False
        self._movie = clip
        self._movie_name = name
        dur = clip.get("count", 0) / max(1.0, clip.get("fps", 24.0))
        self._movie_t0 = time.time()
        self._movie_end = self._movie_t0 + dur + 0.15
        self._movie_frames.clear()
        self._movie_order.clear()
        sound = self.movies.sound(name, self.cfg.get("action_volume", 70) / 100.0)
        if sound is not None:
            try:
                sound.play()
            except Exception:
                pass
        self._last_paint_idx = -1
        self.timer.setInterval(25)          # 视频期间提高重绘频率，保证 24fps 顺滑
        self.update()
        return True

    def stop_movie(self) -> None:
        if self._movie is None:
            return
        self._movie = None
        self._movie_name = ""
        self._movie_frames.clear()
        self._movie_order.clear()
        self.update()

    def apply_volume(self) -> None:
        try:
            self.movies.set_volume(self.cfg.get("action_volume", 70) / 100.0)
        except Exception:
            pass

    def _advance_movie(self, now: float) -> None:
        if self._movie is None:
            return
        if now >= self._movie_end:
            self.stop_movie()
            self.state = PetState(action="idle_stand", heading=self.state.heading,
                                  speed=0.5, remaining=20, memory=self.state.memory)
            self.target_heading = self.state.heading
            if self.timer.interval() != const.TICK_MS:
                self.timer.setInterval(const.TICK_MS)

    def _movie_pixmap(self, idx: int) -> Optional[QPixmap]:
        pm = self._movie_frames.get(idx)
        if pm is not None:
            return pm
        path = self.movies.frame_path(self._movie_name, idx)
        src = QPixmap(path)
        if src.isNull():
            return None
        target_h = max(1, int(self._movie.get("height", 350)))
        scale = self.draw_h / target_h
        # 防止宽幅动作超出桌宠窗口被裁切
        scale = min(scale,
                    max(60, self.width() - 16) / max(1, src.width()),
                    max(60, self.height() - 16) / max(1, src.height()))
        pm = src.scaled(max(1, int(src.width() * scale)),
                        max(1, int(src.height() * scale)),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
        self._movie_frames[idx] = pm
        self._movie_order.append(idx)
        while len(self._movie_order) > 14:
            self._movie_frames.pop(self._movie_order.pop(0), None)
        return pm

    def _apply_opacity(self) -> None:
        op = self.cfg.opacity / 100.0
        if op >= 0.999:
            # 100% 时不做窗口透明处理，减少一次分层合成，降低系统负担
            if getattr(self, "_opacity_set", None) not in (None, 1.0):
                self.setWindowOpacity(1.0)
            self._opacity_set = 1.0
            return
        self.setWindowOpacity(max(0.05, op))
        self._opacity_set = op

    def set_scale(self, value: int) -> None:
        self.cfg.scale = value
        self.cfg.save()
        old = self.geometry().center()
        self._metrics()
        self.move(old.x() - self.width() // 2, old.y() - self.height() // 2)
        self._clamp_to_screen()

    # ------------------------------------------------------------ 位置
    def _bounds(self):
        """所有屏幕可用区域的并集（支持跨屏移动）。"""
        screens = QApplication.screens()
        rects = [s.availableGeometry() for s in screens]
        left = min(r.left() for r in rects)
        right = max(r.right() for r in rects)
        top = min(r.top() for r in rects)
        bottom = max(r.bottom() for r in rects)
        return left, right, top, bottom

    def _work_adjust(self, x: int, y: int) -> tuple:
        """把窗口夹到所在屏幕的可用区域（自动避开任务栏，兼容多屏/高DPI）。"""
        w, h = self.width(), self.height()
        cx, cy = x + w // 2, y + h // 2
        screens = QApplication.screens()
        for s in screens:
            if s.geometry().adjusted(-w, -h, w, h).contains(cx, cy):
                a = s.availableGeometry()
                x = min(max(x, a.left()), a.right() - w)
                y = min(max(y, a.top()), a.bottom() - h)
                return x, y
        # 不在任何屏幕内：夹回最接近的屏幕
        s = QApplication.screenAt(QPoint(cx, cy)) or QApplication.primaryScreen()
        a = s.availableGeometry()
        x = min(max(x, a.left()), a.right() - w)
        y = min(max(y, a.top()), a.bottom() - h)
        return x, y

    def _place_initial(self) -> None:
        pos = self.cfg.get("window_pos")
        if isinstance(pos, list) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))
        else:
            a = QApplication.primaryScreen().availableGeometry()
            self.move(a.right() - self.width() - 20, a.bottom() - self.height() - 10)
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        x, y = self._work_adjust(self.x(), self.y())
        self.move(x, y)

    def center_on_screen(self) -> tuple:
        return (self.x() + self.width() // 2, self.y() + self.height() - 30)

    # ------------------------------------------------------------ 主循环
    def _tick(self) -> None:
        now = time.time()
        dt = min(0.25, now - self._last_tick)
        self._last_tick = now
        self._anim_t += dt

        # 节流：全屏检测每 0.8 秒一次
        if now - self._last_fs_check > 0.8:
            self._last_fs_check = now
            self._check_fullscreen()
        dnd = self._fullscreen and self.cfg.get("mute_fullscreen", True)
        # 动作视频播放中：只推进视频帧，暂停其它行为
        if self._movie is not None:
            if dnd:
                self.stop_movie()
            else:
                self._advance_movie(now)
                if self._movie is not None:
                    if self.timer.interval() != 25:
                        self.timer.setInterval(25)
                    self.update()
                    return
        # 全屏免打扰：降低动画帧率
        want = 250 if dnd else const.TICK_MS
        if self.timer.interval() != want:
            self.timer.setInterval(want)
        if dnd:
            if self.isVisible():
                self.update()  # 保持可见但不动作
            return
        if self._paused:
            return

        # 智能降频：无操作时降低帧率（每 1 秒采样一次，避免频繁 syscall）
        if self.cfg.get("smart_downclock", True):
            if now - self._last_idle_check > 1.0:
                self._last_idle_check = now
                try:
                    import ctypes
                    class LASTINPUTINFO(ctypes.Structure):
                        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
                    li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(LASTINPUTINFO)
                    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
                    self._idle_ms = ctypes.windll.kernel32.GetTickCount() - li.dwTime
                except Exception:
                    self._idle_ms = 0
            slow = 120 if self._idle_ms > 120000 else const.TICK_MS
            if self.timer.interval() != slow:
                self.timer.setInterval(slow)

        # 鼠标信息
        gp = QCursor.pos()
        cx, cy = self.center_on_screen()
        dist = math.hypot(gp.x() - cx, gp.y() - cy)

        move_ok = self.cfg.get("allow_move", True)

        # 关闭移动时：立刻把走/跑切换成原地动作
        if not move_ok and self.state.action in WALK_ACTIONS:
            self.state = PetState(action="idle_stand", heading=self.state.heading,
                                  speed=0.5, remaining=20, memory=self.state.memory)
            self.target_heading = self.state.heading

        # 鼠标太近 -> 逃跑（本地优先，关闭移动时不逃）
        if move_ok and dist < const.MOUSE_FLEE_DIST and self.state.action != "run_away":
            away = math.degrees(math.atan2(cy - gp.y(), cx - gp.x())) % 360
            self.state = PetState(action="run_away", heading=int(away),
                                  speed=max(1.3, self.state.speed), remaining=12,
                                  memory="主人靠太近，溜了溜了")
            self.target_heading = int(away)

        # 倒计时
        self.state.remaining -= 1
        if self.state.remaining <= 0:
            left, right, top, bottom = self._bounds()
            self.state = self.brain.choose(self.state, cx, cy, left, right, top, bottom,
                                           (gp.x(), gp.y()))
            if not move_ok and self.state.action in WALK_ACTIONS:
                self.state = PetState(action=random.choice(["idle_stand", "idle_sit",
                                                            "look_around", "sniff"]),
                                      heading=self.state.heading, speed=0.5, remaining=20,
                                      memory="原地发呆")
            self.target_heading = self.state.heading
            self.memory.save_behavior(self.state.memory)

        # 平滑转向
        self._smooth_heading()

        # 位移
        if self.state.action in WALK_ACTIONS and move_ok:
            spd = const.BASE_SPEED * self.state.speed * max(0.4, self.vitality_factor)
            rad = math.radians(self.heading)
            dx = math.cos(rad) * spd * dt
            dy = math.sin(rad) * spd * dt
            nx = self.x() + dx
            ny = self.y() + dy
            left, right, top, bottom = self._bounds()
            mw, mh = self.width(), self.height()
            margin_x = const.SAFE_MARGIN_X * 0.5
            margin_y = const.SAFE_MARGIN_Y
            if nx < left - self.pad + margin_x:
                nx = left - self.pad + margin_x
                self.target_heading = 0
            if nx + mw > right + self.pad - margin_x:
                nx = right + self.pad - margin_x - mw
                self.target_heading = 180
            if ny < top - self.pad + margin_y:
                ny = top - self.pad + margin_y
                self.target_heading = 90
            if ny + mh > bottom + self.pad - margin_y:
                ny = bottom + self.pad - margin_y - mh
                self.target_heading = 270
            nx, ny = self._work_adjust(int(nx), int(ny))
            self.move(int(nx), int(ny))

        # 动画量
        if self.state.action == "jump":
            self._squash = math.sin((6 - self.state.remaining) / 6 * math.pi)
        else:
            self._squash *= 0.85
        if self.state.action == "idle_sleep":
            self._zzz += dt

        # 选择/切换动作片段（带最小驻留时间，避免频繁切换导致闪烁）
        desired = self._desired_clip()
        forced = bool(self._forced_clip) and now < self._clip_forced_until
        if desired != self.current_clip:
            if (forced or self.current_clip is None
                    or (now - self._clip_set_at) >= self.CLIP_MIN_HOLD):
                self._set_clip(desired)
        self._advance_clip(dt)
        if self.state.action in ("crawl_left", "crawl_right", "run_away"):
            spd_cos = math.cos(math.radians(self.heading))
            if abs(spd_cos) > 0.15:
                self._facing = 1 if spd_cos > 0 else -1

        # 只在实际需要时重绘：按"帧序号变化"重绘，既不抖动也省 CPU
        cur_frames = self.clip_cache.get(self.current_clip) if self.current_clip else None
        clip_idx = (int(self._clip_time) % len(cur_frames)) if cur_frames else -1
        bubble_anim = bool(self._bubble_text) and (
            now - self._bubble_shown_at < 0.2 or self._bubble_until - now < 0.5)
        dynamic = (self._clip_prev is not None
                   or self.state.action in WALK_ACTIONS
                   or self._squash > 0.01
                   or self._deform != [1.0, 1.0]
                   or bubble_anim
                   or not self.current_clip)
        need_interval = 1.0 / max(1.0, self.CLIP_FPS.get(self.current_clip or "", 10.0))
        if (dynamic or clip_idx != self._last_paint_idx
                or (now - self._last_paint) >= need_interval * 1.6):
            self._last_paint = now
            self._last_paint_idx = clip_idx
            self.update()

        # 自适应帧率：按当前动作帧率唤醒，空闲时不空转，减少对其他程序的影响
        if self.state.action in WALK_ACTIONS or self._bubble_text or self._clip_prev is not None:
            want = const.TICK_MS
        elif self.cfg.get("smart_downclock", True) and self._idle_ms > 120000:
            want = 200
        else:
            fps = self.CLIP_FPS.get(self.current_clip or "", 8.0)
            want = max(const.TICK_MS, min(200, int(1000 / max(1.0, fps))))
        if self.timer.interval() != want:
            self.timer.setInterval(want)

    def _smooth_heading(self) -> None:
        diff = (self.target_heading - self.heading + 540) % 360 - 180
        step = max(-12, min(12, diff))
        self.heading = (self.heading + step) % 360

    def _do_blink(self) -> None:
        self._blink = 2
        self.update()

    # ------------------------------------------------------------ 绘画
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 动作视频优先绘制（透明帧序列，帧号按墙上时钟推进，和音频同步）
        if self._movie is not None:
            cx = self.width() / 2
            cy = self.height() / 2 - 6
            if self._shadow_pix is not None:
                p.drawPixmap(int(cx - self._shadow_pix.width() // 2),
                             int(cy + self.base_h // 2 + 6), self._shadow_pix)
            fps = max(1.0, self._movie.get("fps", 24.0))
            idx = int((time.time() - self._movie_t0) * fps)
            idx = max(0, min(int(self._movie.get("count", 1)) - 1, idx))
            pm = self._movie_pixmap(idx)
            if pm is not None:
                p.drawPixmap(int(cx - pm.width() / 2), int(cy - pm.height() / 2), pm)
            p.end()
            if self._bubble_text and time.time() < self._bubble_until:
                self._paint_bubble()
            elif self._bubble_text:
                self._bubble_text = ""
            return

        if self.pix.isNull():
            p.end(); return

        cx = self.width() / 2
        cy = self.height() / 2 - 6

        # 优先使用生成的动画片段（idle / 走路 / 点击 / 思考）
        cur_frames = self.clip_cache.get(self.current_clip) if self.current_clip else None
        prev_frames = self.clip_cache.get(self._clip_prev) if self._clip_prev else None
        use_clip = bool(cur_frames)

        if use_clip:
            bob = 0.0
            tilt = 0.0
        else:
            # 呼吸/摇摆（无片段时的程序化动作）
            bob = math.sin(self._anim_t * 2.2) * 3
            tilt = math.sin(self._anim_t * 1.6) * 2.5
            if self.state.action == "run_away":
                bob = abs(math.sin(self._anim_t * 14)) * 8
                tilt = math.sin(self._anim_t * 14) * 6
            elif self.state.action in ("crawl_left", "crawl_right"):
                bob = abs(math.sin(self._anim_t * 8)) * 5
                tilt = math.sin(self._anim_t * 8) * 3
            elif self.state.action == "idle_sleep":
                bob = math.sin(self._anim_t * 1.2) * 2

        jump = -math.sin(self._squash * math.pi) * 45 if self._squash > 0 else 0
        sx, sy = self._deform
        stretch = 1.0
        if self.state.action == "stretch" and not use_clip:
            stretch = 1.0 + math.sin((self.state.remaining % 10) / 10 * math.pi) * 0.06

        p.translate(cx, cy + bob + jump)
        p.rotate(tilt)
        # 缩放由 draw_w/draw_h 承担（线性），此处只叠加捏脸/伸懒腰形变
        p.scale(sx, sy * stretch)
        if use_clip and self._facing < 0:
            p.scale(-1.0, 1.0)

        # 投影（缓存好的 Pixmap，避免每帧新建）
        if self._shadow_pix is not None:
            p.drawPixmap(-self._shadow_pix.width() // 2,
                         self.base_h // 2 + 6, self._shadow_pix)

        if use_clip:
            # 交叉淡化：旧动作淡出 + 新动作淡入
            if prev_frames and self._clip_blend < 1.0:
                pi = int(self._prev_clip_time) % len(prev_frames)
                pm = prev_frames[pi]
                p.setOpacity(1.0 - self._clip_blend)
                p.drawPixmap(-pm.width() // 2, -pm.height() // 2, pm)
            ci = int(self._clip_time) % len(cur_frames)
            pm = cur_frames[ci]
            p.setOpacity(self._clip_blend if prev_frames else 1.0)
            p.drawPixmap(-pm.width() // 2, -pm.height() // 2, pm)
            p.setOpacity(1.0)
        else:
            target = QRect(-self.draw_w // 2, -self.draw_h // 2, self.draw_w, self.draw_h)
            p.drawPixmap(target, self.pix)

        # 眨眼（仅静态图；片段自带眨眼）
        if not use_clip and self._blink > 0:
            self._blink -= 1
            p.setPen(QPen(QColor(40, 50, 90, 200), 2))
            fx1 = target.left() + target.width() * self.face_box[0]
            fx2 = target.left() + target.width() * self.face_box[2]
            fy = target.top() + target.height() * 0.17
            p.drawLine(int(fx1), int(fy), int(fx2), int(fy))

        # 睡觉 ZZ
        if self.state.action == "idle_sleep":
            p.setPen(QColor(120, 160, 230, 230))
            p.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            for i in range(3):
                zx = -self.draw_w // 3 - 20 - i * 12
                zy = -self.draw_h // 2 - 10 - ((self._zzz * 20 + i * 20) % 60)
                p.drawText(int(zx), int(zy), 16, 16, int(Qt.AlignmentFlag.AlignCenter), "z")

        p.end()

        # 气泡
        if self._bubble_text and time.time() < self._bubble_until:
            self._paint_bubble()
        elif self._bubble_text:
            self._bubble_text = ""

    def _paint_bubble(self) -> None:
        now = time.time()
        age = now - self._bubble_shown_at
        remain = self._bubble_until - now
        alpha = 1.0
        if age < 0.15:
            alpha = age / 0.15
        if remain < 0.4:
            alpha = min(alpha, max(0.0, remain / 0.4))
        alpha = max(0.0, min(1.0, alpha))
        if alpha <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(alpha)
        font = QFont("Microsoft YaHei", 10)
        p.setFont(font)
        fm = p.fontMetrics()
        text = self._bubble_text
        max_w = max(120, min(280, self.width() - 32))
        rect = fm.boundingRect(QRect(0, 0, max_w, 400),
                               int(Qt.TextFlag.TextWordWrap), text)
        bw = min(max_w, rect.width()) + 20
        bw = min(bw, self.width() - 12)
        bh = rect.height() + 18
        bx = max(6, self.width() - bw - 6)
        by = 6
        path = QPainterPath()
        path.addRoundedRect(bx, by, bw, bh, 10, 10)
        p.fillPath(path, QColor(230, 244, 255, 235))
        p.setPen(QPen(QColor(150, 190, 235), 2))
        p.drawPath(path)
        p.setPen(QColor(60, 80, 130))
        p.drawText(QRect(bx + 10, by + 9, bw - 20, bh - 18),
                   int(Qt.TextFlag.TextWordWrap), text)
        p.end()

    # ------------------------------------------------------------ 交互
    def _face_rect(self) -> QRect:
        cx = self.width() / 2
        cy = self.height() / 2 - 6
        w = self.draw_w * (self.face_box[2] - self.face_box[0])
        h = self.draw_h * (self.face_box[3] - self.face_box[1])
        left = cx - self.draw_w / 2 + self.draw_w * self.face_box[0]
        top = cy - self.draw_h / 2 + self.draw_h * self.face_box[1]
        return QRect(int(left), int(top), int(w), int(h))

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._press_pos = e.position().toPoint()
        self._press_started = time.time()
        self._did_drag = False
        if self._movie is not None:
            # 动作视频播放中：只允许拖动窗口，不做捏脸
            self._moving_window = True
            self._win_drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            return
        if self._face_rect().contains(self._press_pos):
            self._pressing_face = True
        else:
            self._moving_window = True
            self._win_drag_off = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        gp = e.globalPosition().toPoint()
        if self._pressing_face:
            self._did_drag = True
            dx = gp.x() - self._press_pos.x() - (self.mapToGlobal(self._press_pos).x() - self.x())
            dy = gp.y() - self._press_pos.y()
            sx = max(0.7, min(1.3, 1.0 + dy / 200.0))
            sy = max(0.7, min(1.3, 1.0 - dy / 200.0))
            self._deform = [sx, sy]
            self.update()
        elif self._moving_window and (e.buttons() & Qt.MouseButton.LeftButton):
            self._did_drag = True
            self.move(gp - self._win_drag_off)
        else:
            # 悬停反馈
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        held = time.time() - self._press_started
        if not self._did_drag and held < 0.35:
            self._force_clip("click", 1.1)   # 点击时播放"点击"动作
        if self._pressing_face:
            self._pressing_face = False
            self._deform = [1.0, 1.0]
            self.update()
            if held > 0.35 and self._did_drag:
                # 捏脸：20% 概率吃掉鼠标箭头
                if random.random() < 0.20:
                    self._eat_cursor()
                    return
            if held > 0.35:
                self.say.emit(random.choice([
                    "呜！别捏本鱼的脸啦 (๑•́ ₃ •̀๑)",
                    "哼，再捏本鱼要生气了哦",
                    "脸、脸要被捏扁了啦！",
                ]), "生气")
            elif not self._did_drag:
                self.clicked.emit()
        elif self._moving_window:
            self._moving_window = False
            if not self._did_drag:
                self.clicked.emit()
            else:
                self._snap_and_bounce()
        self._did_drag = False

    def _snap_and_bounce(self) -> None:
        left, right, top, bottom = self._bounds()
        snap = 24
        x, y = self.x(), self.y()
        if abs(x - left) < snap:
            x = left
        if abs(x + self.width() - right) < snap:
            x = right - self.width()
        self.move(x, y)
        self.cfg.set("window_pos", [x, y])
        self.cfg.save()
        # 回弹
        self._squash = 0.6

    def _eat_cursor(self) -> None:
        if self._cursor_eaten:
            return
        self._cursor_eaten = True
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))
        self._bubble_text = "呜姆…主人的鼠标被本鱼吃掉了 (๑´ڡ`๑)"
        self._bubble_until = time.time() + 3
        self.say.emit("呜姆…啊呜一口，鼠标被本鱼吃掉了！", "自豪")
        QTimer.singleShot(3000, self._spit_cursor)

    def _spit_cursor(self) -> None:
        QApplication.restoreOverrideCursor()
        self._cursor_eaten = False
        self._bubble_text = "呸！还给你啦，不好吃 (｀へ´)"
        self._bubble_until = time.time() + 2.5
        self.say.emit("呸呸，鼠标还给你，一点都不好吃 (｀へ´)", "无语")
        self._squash = 1.0

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.request_chat.emit()

    def contextMenuEvent(self, e) -> None:
        if self.cfg.get("use_radial_menu", True):
            self.radial_menu_requested.emit(e.globalPos())
            return
        self.show_context_menu(e.globalPos())

    def show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        menu.addAction("和本鱼说说话", self.request_chat.emit)
        menu.addAction("让大肥鱼康康", self.request_screenshot.emit)
        menu.addAction("看看余额/信息", self.request_balance.emit)
        menu.addSeparator()
        menu.addAction("摸头（摸摸）", lambda: self.say.emit(
            random.choice(["嘿嘿…主人的手好暖和 (๑˃̵ᴗ˂̵)", "嗯…再摸摸嘛"]), "开心"))
        menu.addSeparator()
        menu.addAction("设置", lambda: self.request_settings.emit("api"))
        menu.addAction("暂停/继续", self._toggle_pause)
        menu.addAction("养成面板", lambda: self.request_settings.emit("growth"))
        menu.addAction("代码收藏夹", lambda: self.request_settings.emit("snippets"))
        menu.addAction("隐形（关闭）", self._hide_forever)
        menu.exec(pos)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.say.emit("本鱼先休息一下…" if self._paused else "本鱼回来啦！", "困")

    def _hide_forever(self) -> None:
        self.hide()
        self.ctx.quit_app()

    # ------------------------------------------------------------ 设置按钮
    def _build_gear(self) -> None:
        self.gear = QPushButton("⚙", self)
        self.gear.setToolTip("大肥鱼设置")
        self.gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear.setFixedSize(24, 24)
        self.gear.setStyleSheet(
            "QPushButton{border:none;color:#7fb2e8;font-size:14px;"
            "background:rgba(200,225,250,0.55);border-radius:12px;}"
            "QPushButton:hover{background:rgba(150,195,240,0.9);color:white;}")
        self.gear.move(self.width() - 28, 4)
        self.gear.raise_()
        self.gear.clicked.connect(self._show_gear_menu)

    def _show_gear_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MENU)
        menu.addAction("让大肥鱼康康", self.request_screenshot.emit)
        menu.addAction("压缩上下文", lambda: self.request_settings.emit("compress"))
        menu.addAction("整体透明度", lambda: self.request_settings.emit("opacity"))
        menu.addAction("隐形", lambda: self.request_settings.emit("invisible"))
        menu.addAction("定闹钟", lambda: self.request_settings.emit("alarm"))
        menu.addAction("待办", lambda: self.request_settings.emit("todos"))
        menu.addAction("切换角色", lambda: self.request_settings.emit("character"))
        menu.addAction("养成面板", lambda: self.request_settings.emit("growth"))
        menu.addAction("代码收藏夹", lambda: self.request_settings.emit("snippets"))
        menu.addSeparator()
        menu.addAction("音量 +", lambda: self.quick_action.emit("vol_up"))
        menu.addAction("音量 −", lambda: self.quick_action.emit("vol_down"))
        menu.addAction("亮度 +", lambda: self.quick_action.emit("bri_up"))
        menu.addAction("亮度 −", lambda: self.quick_action.emit("bri_down"))
        menu.addSeparator()
        menu.addAction("删除记忆", lambda: self.request_settings.emit("memory"))
        menu.addAction("API", lambda: self.request_settings.emit("api"))
        menu.exec(self.gear.mapToGlobal(QPoint(0, self.gear.height())))

    def resizeEvent(self, e) -> None:
        if hasattr(self, "gear"):
            self.gear.move(self.width() - 28, 4)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.timer.stop()            # 隐藏时停止计时器，彻底不占 CPU

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.timer.isActive():
            self._last_tick = time.time()
            self.timer.start(self.timer.interval())

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        pos = self.pos()
        if self._last_move_pos is not None:
            dx = pos.x() - self._last_move_pos.x()
            dy = pos.y() - self._last_move_pos.y()
            if dx or dy:
                self.moved.emit(dx, dy)
        self._last_move_pos = pos

    # ------------------------------------------------------------ 外部
    def on_behavior(self, obj) -> None:
        st = validate(obj, self.state)
        if st is None:
            return
        if not self.cfg.get("allow_move", True) and st.action in WALK_ACTIONS:
            st = PetState(action="idle_stand", heading=st.heading, speed=0.5,
                          remaining=20, memory=st.memory)
        self.state = st
        self.target_heading = st.heading
        self.memory.save_behavior(st.memory)

    def show_bubble(self, text: str, seconds: float = 4.0, sticker: str = "") -> None:
        self._bubble_text = text
        self._bubble_until = time.time() + seconds
        self._bubble_shown_at = time.time()

    def _check_fullscreen(self) -> None:
        if not self.cfg.get("mute_fullscreen", True):
            self._fullscreen = False
            return
        try:
            from .winutil import is_fullscreen
            self._fullscreen = is_fullscreen()
        except Exception:
            self._fullscreen = False


STYLE_MENU = """
QMenu{background:#f3f8ff;border:1px solid #bcd8f5;border-radius:8px;padding:4px;}
QMenu::item{padding:6px 22px;border-radius:6px;color:#33507a;}
QMenu::item:selected{background:#d6e9ff;color:#1b3a66;}
QMenu::separator{height:1px;background:#dce9f7;margin:4px 8px;}
"""
