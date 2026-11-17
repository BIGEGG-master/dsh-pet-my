# -*- coding: utf-8 -*-
"""「嘟嘟的生活」面板（v4.7.0 新增的等级 / 技能 / 自主开关）。

不起真窗口管理器：offscreen 平台建 Qt 控件，断言"文案 + 按钮状态"，
与 ``test_pet_life_hud.py`` 同一口径。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pet.config import Config  # noqa: E402
from pet.pet_life_dialog import PetLifeDialog  # noqa: E402
from pet.pet_life_service import PetLifeService  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _dialog(tmp_path) -> tuple[PetLifeDialog, PetLifeService]:
    service = PetLifeService(Config(tmp_path))
    dialog = PetLifeDialog(service)
    return dialog, service


def test_dialog_shows_level_in_state_line(app, tmp_path):
    dialog, _service = _dialog(tmp_path)
    assert "Lv.1" in dialog._hint.text()
    dialog.close()


def test_dialog_skill_rows_follow_level(app, tmp_path):
    dialog, service = _dialog(tmp_path)
    assert dialog._skill_rows["self_work"].button.text() == "未解锁"
    service.state["xp"] = 280.0          # Lv5：两个技能都该点亮
    dialog.refresh()
    assert "Lv.5" in dialog._hint.text()
    assert dialog._skill_rows["self_work"].button.text() == "已学会"
    assert dialog._skill_rows["self_shop"].button.text() == "已学会"
    # 技能行只是状态展示，不该让用户点（点也改不了等级）
    assert dialog._skill_rows["self_work"].button.isEnabled() is False
    dialog.close()


def test_dialog_autonomy_toggle_goes_through_service(app, tmp_path):
    dialog, service = _dialog(tmp_path)
    assert service.autonomy() is True
    dialog._toggle_autonomy()
    assert service.autonomy() is False
    assert "已关闭" in dialog._autonomy_btn.text()
    dialog._toggle_autonomy()
    assert service.autonomy() is True
    dialog.close()


def test_dialog_xp_bar_receives_progress(app, tmp_path):
    dialog, service = _dialog(tmp_path)
    service.state["xp"] = 150.0          # Lv3，本级 50/80
    dialog.refresh()
    progress = dialog._xp._progress
    assert progress["level"] == 3
    assert progress["into"] == pytest.approx(50.0)
    assert progress["need"] == pytest.approx(80.0)
    dialog.close()
