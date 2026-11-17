# -*- coding: utf-8 -*-
"""随 DSH 退出（pet/app.py :: _follow_dsh_lifecycle）的纯逻辑测试。

不构造整个 AppShell（那要拉起 Qt 窗口与共享子系统）：只把方法绑到一个带
``_dsh_quit_timer`` / ``config`` 的替身对象上跑。这样测的是**决策**，不是窗口。
"""
from __future__ import annotations

from types import SimpleNamespace

from pet.app import AppShell


class FakeTimer:
    def __init__(self):
        self.started = None
        self.active = False

    def isActive(self):
        return self.active

    def start(self, ms):
        self.started = ms
        self.active = True

    def stop(self):
        self.active = False


def _shell(*, enabled=True, grace=20):
    shell = SimpleNamespace(
        _dsh_seen_online=False,
        _dsh_quit_timer=FakeTimer(),
        _quitting=False,
        config={"dsh_quit_with_dsh": enabled, "dsh_quit_grace_seconds": grace},
        _quit_calls=[],
    )
    shell._quit_for_dsh_exit = lambda: shell._quit_calls.append(True)
    return shell


def _run(shell, state):
    AppShell._follow_dsh_lifecycle(shell, state)


def test_offline_without_ever_being_online_never_arms():
    shell = _shell()
    _run(shell, "offline")
    assert shell._dsh_quit_timer.active is False
    assert shell._dsh_seen_online is False


def test_offline_after_online_arms_with_grace():
    shell = _shell(grace=20)
    _run(shell, "working")
    assert shell._dsh_seen_online is True
    _run(shell, "offline")
    assert shell._dsh_quit_timer.active is True
    assert shell._dsh_quit_timer.started == 20_000


def test_recovery_cancels_countdown():
    shell = _shell()
    _run(shell, "working")
    _run(shell, "offline")
    assert shell._dsh_quit_timer.active is True
    _run(shell, "thinking")
    assert shell._dsh_quit_timer.active is False


def test_disabled_switch_never_arms():
    shell = _shell(enabled=False)
    _run(shell, "working")
    _run(shell, "offline")
    assert shell._dsh_quit_timer.active is False


def test_bad_grace_falls_back_to_default():
    shell = _shell(grace="abc")
    _run(shell, "working")
    _run(shell, "offline")
    assert shell._dsh_quit_timer.started == 20_000


def test_grace_zero_is_clamped_to_one_second():
    shell = _shell(grace=0)
    _run(shell, "working")
    _run(shell, "offline")
    assert shell._dsh_quit_timer.started == 1000


def test_quit_is_skipped_while_already_quitting():
    shell = _shell()
    shell._quitting = True
    AppShell._quit_for_dsh_exit(shell)
    assert shell._quit_calls == []


def test_quit_is_skipped_when_switch_off():
    shell = _shell(enabled=False)
    AppShell._quit_for_dsh_exit(shell)
    assert shell._quit_calls == []
