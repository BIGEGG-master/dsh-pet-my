# -*- coding: utf-8 -*-
"""状态条交互（拖动 / 贴边 / 悬停展开 / 移开缩回）的行为测试。

不起真窗口管理器：用 offscreen 平台建 QWidget，直接调事件处理函数，
断言"几何 + 状态机"，而不是像素。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet import pet_life_data as D  # noqa: E402
from pet.pet_life_hud import (  # noqa: E402
    AUTO_COLLAPSE_MS,
    COLLAPSED_THICKNESS,
    HUD_WIDTH,
    SNAP_DISTANCE,
    PetLifeHud,
)


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _rows():
    return [(key, D.STATUS_LABELS[key], 50.0) for key in D.STATUS_KEYS]


def _hud(app) -> PetLifeHud:
    hud = PetLifeHud()
    hud.update_state(_rows(), 120)
    hud.set_anchor(QRect(100, 100, 120, 120))
    return hud


def _press(hud: PetLifeHud, global_point: QPoint) -> None:
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(global_point),
        Qt_LeftButton(),
        Qt_LeftButton(),
        _no_modifier(),
    )
    hud.mousePressEvent(event)


def _move(hud: PetLifeHud, global_point: QPoint) -> None:
    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(5, 5),
        QPointF(global_point),
        _no_button(),
        Qt_LeftButton(),
        _no_modifier(),
    )
    hud.mouseMoveEvent(event)


def _release(hud: PetLifeHud, global_point: QPoint) -> None:
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(5, 5),
        QPointF(global_point),
        Qt_LeftButton(),
        _no_button(),
        _no_modifier(),
    )
    hud.mouseReleaseEvent(event)


def Qt_LeftButton():  # noqa: N802 - 测试辅助
    from PySide6.QtCore import Qt

    return Qt.MouseButton.LeftButton


def _no_button():
    from PySide6.QtCore import Qt

    return Qt.MouseButton.NoButton


def _no_modifier():
    from PySide6.QtCore import Qt

    return Qt.KeyboardModifier.NoModifier


def test_hud_is_expanded_by_default(app):
    hud = _hud(app)
    assert hud.width() == HUD_WIDTH
    assert hud._collapsed is False  # noqa: SLF001 - 断言状态机
    hud.deleteLater()


def test_drag_moves_and_detaches_from_anchor(app):
    hud = _hud(app)
    start = hud.pos()
    _press(hud, start + QPoint(5, 5))
    _move(hud, start + QPoint(120, 60))
    _release(hud, start + QPoint(120, 60))
    assert hud.pos() != start, "拖动必须真的移动窗口"
    assert hud._free_pos is not None, "拖动后应脱离跟随锚点"  # noqa: SLF001
    hud.deleteLater()


def test_release_near_edge_snaps_and_reports(app):
    hud = _hud(app)
    seen: list[tuple] = []
    hud.position_changed.connect(lambda x, y, edge: seen.append((x, y, edge)))
    # 拖到屏幕左上角附近 -> 应吸附 left 或 top
    _press(hud, hud.pos() + QPoint(5, 5))
    _move(hud, QPoint(2, 2))
    _release(hud, QPoint(2, 2))
    assert seen, "松手必须上报位置（AppShell 靠它落盘）"
    _x, _y, edge = seen[-1]
    assert edge in ("left", "top"), f"贴边吸附失败：{edge}"
    assert hud._edge == edge  # noqa: SLF001
    hud.deleteLater()


def test_release_far_from_edge_keeps_floating(app):
    hud = _hud(app)
    seen: list[tuple] = []
    hud.position_changed.connect(lambda x, y, edge: seen.append((x, y, edge)))
    area = hud.screen().availableGeometry()
    middle = QPoint(area.center().x() - hud.width() // 2, area.center().y() - hud.height() // 2)
    _press(hud, hud.pos() + QPoint(5, 5))
    _move(hud, middle)
    _release(hud, middle)
    assert seen and seen[-1][2] == "none", f"屏幕中间不该吸附：{seen}"
    hud.deleteLater()


def test_hover_expands_and_leave_collapses(app):
    hud = _hud(app)
    # 先贴左边并缩回
    _press(hud, hud.pos() + QPoint(5, 5))
    _move(hud, QPoint(2, 200))
    _release(hud, QPoint(2, 200))
    hud._hover = False  # noqa: SLF001
    hud._collapse()  # noqa: SLF001 - 直接把状态机推到缩回态
    assert hud._collapsed is True  # noqa: SLF001
    collapsed_width = hud.width()
    assert collapsed_width == COLLAPSED_THICKNESS, "缩回后应变成细条"

    hud.enterEvent(_enter())
    assert hud._collapsed is False, "鼠标移上去必须展开"  # noqa: SLF001
    assert hud.width() == HUD_WIDTH
    hud.deleteLater()


def test_collapse_timeout_only_when_docked(app):
    hud = _hud(app)
    # 没贴边：计时器即使触发也不缩回
    hud._edge = "none"  # noqa: SLF001
    hud._maybe_collapse()  # noqa: SLF001
    assert hud._collapsed is False  # noqa: SLF001


def test_collapse_timeout_respects_hover(app):
    hud = _hud(app)
    hud._edge = "left"  # noqa: SLF001
    hud._hover = True  # noqa: SLF001
    hud._maybe_collapse()  # noqa: SLF001
    assert hud._collapsed is False, "鼠标还在上面就不能缩回"  # noqa: SLF001
    hud._hover = False  # noqa: SLF001
    hud._maybe_collapse()  # noqa: SLF001
    assert hud._collapsed is True  # noqa: SLF001
    hud.deleteLater()


def test_restore_position_keeps_free_pos(app):
    hud = PetLifeHud()
    hud.restore_position(300, 200, "right")
    assert hud._free_pos is not None  # noqa: SLF001
    assert hud._edge == "right"  # noqa: SLF001
    hud.deleteLater()


def test_restore_position_ignores_negative(app):
    hud = PetLifeHud()
    hud.restore_position(-1, -1, "none")
    assert hud._free_pos is None, "-1 表示从未拖动过，应继续跟随"  # noqa: SLF001
    hud.deleteLater()


def _enter():
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QEnterEvent

    return QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1))