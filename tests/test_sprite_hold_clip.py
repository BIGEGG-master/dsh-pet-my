# -*- coding: utf-8 -*-
"""睡觉姿态常驻（v4.7.1）：``hold_clip_provider`` 的续播 / 闸门 / 解除。

口径与 ``test_sprite_behavior.py`` / ``test_sprite_acts_tail.py`` 一致：
offscreen、假 clip/假库、时间由 ``tick(dt)`` 累加，不起 QTimer 不 sleep。

假 clip 的 ``currentFrameNumber()`` 恒为 0 → 末帧接口"缺失"，``_acts_tail_done``
按墙钟语义立即收口（既有测试假库走的就是这条），所以到点那一 tick 就会
走到"续播 or 掷骰"的分叉上——正是本文件要钉的那一处。
"""
from __future__ import annotations

import os
from collections import deque

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPointF, QRect, Signal  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet.pet_sprite import PetSprite  # noqa: E402
from pet.sprite_behavior import (  # noqa: E402
    STATE_ACTS,
    STATE_IDLE,
    BehaviorController,
)

app = QApplication.instance() or QApplication([])

BOUNDS = QRect(0, 0, 2000, 1000)
SLEEP = "sleep_pose"


class FakeClip(QObject):
    """接口对齐 WebMClip 的假 clip：帧号恒 0（末帧接口"缺失"→ 墙钟收口）。"""

    frameChanged = Signal(int)
    finished = Signal()

    def __init__(self, name, frames=12):
        super().__init__()
        self.name = name
        self._frames = frames
        self.image = QImage(640, 360, QImage.Format.Format_ARGB32)
        self.image.fill(0xFF336699)
        self.start_count = 0
        self.started = False

    def currentFrameNumber(self):
        return 0

    def currentImage(self):
        return self.image

    def frameCount(self):
        return self._frames

    def duration(self):
        return self._frames * 42 / 1000.0

    def start(self):
        self.started = True
        self.start_count += 1
        return True

    def stop(self):
        self.started = False


class FakeLibrary:
    """轻量库协议：直接暴露池属性（无 names() → play_once 跳过陌生名守卫）。"""

    def __init__(self, *, idles, turns, moves, clicks, drag=None, extra=(), frames=None):
        self.idles = list(idles)
        self.turns = list(turns)
        self.moves = list(moves)
        self.clicks = list(clicks)
        self.drag = drag
        self.move_strides: dict = {}
        self.move_curves: dict = {}
        self.no_mirror: set = set()
        frames = frames or {}
        self._clips = {}
        for name in [*self.idles, *self.turns, *self.moves, *self.clicks, *extra]:
            self._clips[name] = FakeClip(name, frames.get(name, 12))
        if drag:
            self._clips[drag] = FakeClip(drag, frames.get(drag, 12))

    def movie(self, name, **_kw):
        return self._clips[name]

    def duration(self, name):
        return self._clips[name].duration()

    def clip(self, name):
        return self._clips[name]


class ScriptedRng:
    """确定性随机源：rolls 用完后回落到 0.0（= 走待机分支）。"""

    def __init__(self, rolls=()):
        self.rolls = deque(rolls)

    def random(self):
        return self.rolls.popleft() if self.rolls else 0.0

    def randint(self, a, b):
        return a

    def choice(self, seq):
        return seq[0]


def _library():
    return FakeLibrary(
        idles=["idle1"], turns=["turn1"], moves=["walk"], clicks=["click1"],
        extra=(SLEEP,),
    )


def _spawn(provider):
    """返回 (controller, sprite, library)。``provider`` 是 hold 判据。"""
    lib = _library()
    sprite = PetSprite(lib, pos=QPointF(800, 400), facing="left", scale=0.5)
    ctl = BehaviorController(BOUNDS, rng=ScriptedRng())
    ctl.hold_clip_provider = provider
    return ctl, sprite, lib


def _run(controller, sprite, seconds, dt=0.05):
    for _ in range(int(round(seconds / dt))):
        controller.tick([sprite], dt)
        sprite.advance(dt)


# ---------------------------------------------------------------- 续播
def test_held_clip_repeats_without_rolling():
    ctl, sprite, lib = _spawn(lambda sp: SLEEP)
    assert ctl.play_once(sprite, SLEEP) is True
    st = ctl._states[sprite]
    starts = lib.clip(SLEEP).start_count

    _run(ctl, sprite, 1.2)      # 远超 12 帧（约 0.5s）

    assert st.state == STATE_ACTS
    assert st.anim == SLEEP
    assert lib.clip(SLEEP).start_count > starts, "常驻段必须原地续播"


def test_gate_brings_pose_back_after_other_animation():
    """播完别的动画后必须回到姿态——不回到姿态，睡着的下一步就是"乱走"。

    v4.7.5 起常驻期间的普通 play_once 会被闸门拒绝，所以这里用 ``force=True``
    模拟"被允许插播的那一段"（入睡过渡就是这种），断言播完仍回到常驻姿态。
    """
    ctl, sprite, _lib = _spawn(lambda sp: SLEEP)
    assert ctl.play_once(sprite, "click1", force=True) is True

    _run(ctl, sprite, 1.0)

    st = ctl._states[sprite]
    assert st.state == STATE_ACTS
    assert st.anim == SLEEP


def test_no_provider_keeps_legacy_chain():
    """没有判据（= 旧行为）：播完照旧掷骰，不该常驻。"""
    ctl, sprite, _lib = _spawn(None)
    assert ctl.play_once(sprite, SLEEP) is True

    _run(ctl, sprite, 1.5)

    st = ctl._states[sprite]
    assert not (st.state == STATE_ACTS and st.anim == SLEEP)


# ---------------------------------------------------------------- 解除 / 判据健壮性
def test_release_hold_switches_back_to_idle():
    ctl, sprite, _lib = _spawn(lambda sp: SLEEP)
    ctl.play_once(sprite, SLEEP)
    _run(ctl, sprite, 0.3)

    assert ctl.release_hold(sprite) is True
    assert ctl._states[sprite].state == STATE_IDLE


def test_release_hold_is_noop_on_idle():
    ctl, sprite, _lib = _spawn(lambda sp: SLEEP)
    ctl.play_once(sprite, "idle1")
    _run(ctl, sprite, 1.2)      # 已被闸门拉回姿态？
    # 无论如何：从待机态调用不该抛错、也不该被判成切走
    ctl._enter_idle(sprite, ctl._states[sprite], ctl._categories(sprite.library))
    assert ctl.release_hold(sprite) is False


def test_provider_exception_falls_back_to_legacy_chain():
    def boom(_sprite):
        raise RuntimeError("判据炸了")

    ctl, sprite, _lib = _spawn(boom)
    ctl.play_once(sprite, SLEEP)

    _run(ctl, sprite, 1.5)      # 不该抛

    st = ctl._states[sprite]
    assert not (st.state == STATE_ACTS and st.anim == SLEEP)


def test_provider_sees_the_sprite():
    """常驻是**逐只**的：判据必须能看见是哪只（主宠睡，副宠不该跟着躺）。"""
    seen: list = []
    ctl, sprite, _lib = _spawn(lambda sp: (seen.append(sp), SLEEP)[1])
    ctl.play_once(sprite, SLEEP)

    _run(ctl, sprite, 1.2)      # 跨过 12 帧（约 0.5s）才会走到续播判据

    assert sprite in seen


def test_hold_survives_empty_return_value():
    """判据返回空串 = 没有常驻（壳侧按"挑不到素材"这么做）。"""
    ctl, sprite, _lib = _spawn(lambda sp: "")
    ctl.play_once(sprite, SLEEP)

    _run(ctl, sprite, 1.5)

    st = ctl._states[sprite]
    assert not (st.state == STATE_ACTS and st.anim == SLEEP)


# ---------------------------------------------------------------- 常驻期间的播放闸门
def test_play_once_blocked_while_holding():
    """睡着时，外部想播别的段（agent 联动塞"被吓一跳"、自说自话、菜单播放）一律拒绝。

    用户实测：睡着以后突然一脸惊恐——就是因为这些入口绕过了 hold 闸门。
    """
    ctl, sprite, _lib = _spawn(lambda sp: SLEEP)
    assert ctl.play_once(sprite, SLEEP, force=True) is True

    assert ctl.play_once(sprite, "click1") is False
    assert ctl.play_once(sprite, "walk") is False
    # 自己那一段仍允许（幂等），否则"重新进入姿态"也会被自己挡住
    assert ctl.play_once(sprite, SLEEP) is True


def test_force_bypasses_hold_for_transition():
    """入睡过渡必须能穿透闸门（它要在常驻判据已生效之后播）。"""
    ctl, sprite, _lib = _spawn(lambda sp: SLEEP)
    assert ctl.play_once(sprite, "click1", force=True) is True
    assert ctl._states[sprite].anim == "click1"


def test_hold_gate_releases_after_hold_cleared():
    ctl, sprite, _lib = _spawn(lambda sp: SLEEP)
    ctl.play_once(sprite, SLEEP, force=True)
    assert ctl.play_once(sprite, "click1") is False

    ctl.hold_clip_provider = None          # 醒来：判据撤销
    assert ctl.play_once(sprite, "click1") is True
