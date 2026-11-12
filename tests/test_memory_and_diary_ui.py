# -*- coding: utf-8 -*-
"""记忆卡面板 / 日记窗 / 照片备注：UI 行为与后台备注写入（不联网、不打真窗口）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pet import memory_card as cards_mod


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _png(path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return path


# ---------------------------------------------------------------- 记忆卡面板


def test_memory_card_dialog_lists_searches_and_filters(tmp_path):
    _app()
    from pet.memory_card_dialog import MemoryCardDialog

    dialog = MemoryCardDialog(tmp_path)
    assert dialog.item_count == 0  # 空目录：列表空、空状态可见

    cards_mod.add_text(tmp_path, "哥哥喜欢鲸鱼", note="哥哥说的")
    cards_mod.add_photo(tmp_path, _png(tmp_path / "w.png"), note="哥哥画的鲸鱼")
    dialog.reload()
    assert dialog.item_count == 2

    dialog._search.setText("鲸鱼")
    assert dialog.item_count == 2
    dialog._kind.setCurrentIndex(1)  # 只看文字
    assert dialog.item_count == 1
    dialog._search.setText("不存在的词")
    assert dialog.item_count == 0
    dialog._kind.setCurrentIndex(0)
    dialog._search.clear()
    assert dialog.item_count == 2
    dialog.deleteLater()
    _app().processEvents()


def test_memory_card_detail_saves_note_and_deletes(tmp_path, monkeypatch):
    _app()
    from pet.memory_card_dialog import CardDetailDialog

    card = cards_mod.add_text(tmp_path, "正文", note="旧备注")
    assert card is not None
    dialog = CardDetailDialog(tmp_path, card)
    dialog._note_edit.setText("新备注")
    dialog._save_note()
    assert cards_mod.load_cards(tmp_path)[0]["note"] == "新备注"

    # conftest 把 QMessageBox.question 默认成 No（安全拒绝），这里显式放行一次
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    dialog._delete()
    assert cards_mod.load_cards(tmp_path) == []
    dialog.deleteLater()
    _app().processEvents()


# ---------------------------------------------------------------- 日记窗


def _write_session(root, messages):
    folder = root / "sessions" / "shenshen"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": "s1",
        "character_id": "shenshen",
        "messages": messages,
    }
    (folder / "s1.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _utc(day, hour, minute):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc).isoformat()


def test_diary_dialog_shows_day_and_searches(tmp_path):
    _app()
    from pet import diary as diary_mod
    from pet.diary_dialog import DiaryDialog

    diary_mod.clear_cache()
    _write_session(
        tmp_path,
        [
            {"role": "user", "content": "我画了鲸鱼", "created_at": _utc(12, 1, 0)},
            {"role": "assistant", "content": "好可爱嘟", "created_at": _utc(12, 1, 1)},
            {"role": "user", "content": "晚安", "created_at": _utc(11, 14, 0)},
        ],
    )
    dialog = DiaryDialog(tmp_path)
    assert dialog.day_count == 2
    assert dialog.current_day == "2026-11-12"
    assert "鲸鱼" in dialog._text.toPlainText()

    dialog._search.setText("晚安")
    assert dialog.day_count == 1
    assert dialog.current_day == "2026-11-11"

    dialog._search.setText("没出现过的词")
    assert dialog.day_count == 0
    assert "没有找到" in dialog._hint.text()

    dialog._search.clear()
    assert dialog.day_count == 2
    dialog.deleteLater()
    _app().processEvents()


def test_diary_dialog_handles_no_sessions(tmp_path):
    _app()
    from pet import diary as diary_mod
    from pet.diary_dialog import DiaryDialog

    diary_mod.clear_cache()
    dialog = DiaryDialog(tmp_path)
    assert dialog.day_count == 0
    assert "还没有对话" in dialog._hint.text()
    dialog.deleteLater()
    _app().processEvents()


# ---------------------------------------------------------------- 照片备注（她写的那一句）


class _FakeProvider:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def stream(self, messages, config, cancel):  # noqa: ARG002 - 与真实 provider 同签名
        yield self.answer


def _fake_config():
    return SimpleNamespace(model="m", thinking="auto", reasoning_effort="high")


def test_clean_note_strips_quotes_and_truncates():
    from pet.chat.photo_note import _clean_note

    assert _clean_note("「哥哥画的鲸鱼」。") == "哥哥画的鲸鱼"
    assert _clean_note('"哥哥的晚饭"') == "哥哥的晚饭"
    assert _clean_note("多" * 40) == "多" * 16
    assert _clean_note("   ") == ""


def test_photo_note_run_updates_card_note(tmp_path):
    from pet.chat import photo_note

    card = cards_mod.add_photo(tmp_path, _png(tmp_path / "x.png"), note="这是他画的", text="画好了")
    assert card is not None
    photo_note._run(tmp_path, [card], "画好了", "好可爱嘟", _FakeProvider("「哥哥画的鲸鱼」"), _fake_config())
    assert cards_mod.load_cards(tmp_path)[0]["note"] == "哥哥画的鲸鱼"


def test_photo_note_run_keeps_original_note_on_failure(tmp_path):
    from pet.chat import photo_note

    class _Boom:
        def stream(self, messages, config, cancel):
            raise RuntimeError("network down")

    card = cards_mod.add_photo(tmp_path, _png(tmp_path / "y.png"), note="原备注")
    assert card is not None
    photo_note._run(tmp_path, [card], "hi", "hi", _Boom(), _fake_config())
    assert cards_mod.load_cards(tmp_path)[0]["note"] == "原备注"


def test_schedule_photo_note_guards(tmp_path, monkeypatch):
    from pet.chat import photo_note
    from pet import feature_activation as fa

    photo_note.reset_for_tests()
    card = cards_mod.add_photo(tmp_path, _png(tmp_path / "z.png"), note="x")
    assert card is not None
    # 没有 provider / 没有卡片 → 不排线程
    assert photo_note.schedule_photo_note(
        config_dir=tmp_path, cards=[], user_text="a", reply_text="b",
        provider=None, provider_config=None) is False
    # chat 模块停用（纯核心快照）→ 不排线程
    fa.freeze_snapshot_for_tests(set())
    try:
        assert photo_note.schedule_photo_note(
            config_dir=tmp_path, cards=[card], user_text="a", reply_text="b",
            provider=_FakeProvider("x"), provider_config=_fake_config()) is False
    finally:
        fa.reset_snapshot_for_tests()


@pytest.mark.parametrize("note", ["哥哥画的鲸鱼"])
def test_memory_card_note_column_roundtrip(tmp_path, note):
    card = cards_mod.add_text(tmp_path, "正文", note=note)
    assert card is not None
    assert cards_mod.load_cards(tmp_path)[0]["note"] == note


# ---------------------------------------------------------------- 右键菜单入口


def test_menu_has_memory_card_and_diary_entries(monkeypatch):
    """两个入口在注册表 + 默认布局里都在，且点了会调到宿主的打开方法。"""
    _app()
    from PySide6.QtWidgets import QMenu

    from pet.context_menus.registry import ACTION_ICONS, ACTION_LABELS, MENU_ACTIONS
    from pet.menu_layout import load_default_menu_layout

    assert ACTION_LABELS["memory_card"] == "查看记忆卡"
    assert ACTION_LABELS["diary"] == "嘟嘟的日记"
    assert ACTION_ICONS["memory_card"] and ACTION_ICONS["diary"]
    ids = [node.get("id") for node in load_default_menu_layout()["nodes"]]
    assert "memory_card" in ids and "diary" in ids
    # 紧跟在「AI 对话」之后（默认布局口径）
    assert ids[ids.index("chat") + 1 : ids.index("chat") + 3] == ["memory_card", "diary"]

    opened: list[str] = []

    class _Cfg:
        def get(self, key, default=None):
            return default

    class _Pet:
        cfg = _Cfg()

        def on_open_memory_card(self):
            opened.append("memory")

        def on_open_diary(self):
            opened.append("diary")

    menu = QMenu()
    MENU_ACTIONS.populate(menu, _Pet(), [
        {"type": "action", "id": "memory_card", "visible": True},
        {"type": "action", "id": "diary", "visible": True},
    ])
    texts = [action.text() for action in menu.actions()]
    assert texts == ["查看记忆卡", "嘟嘟的日记"]
    menu.actions()[0].trigger()
    menu.actions()[1].trigger()
    assert opened == ["memory", "diary"]
    menu.deleteLater()
    _app().processEvents()


def test_app_shell_exposes_both_openers():
    """宿主侧两个打开方法必须真在 AppShell 上（菜单回调取的就是它们）。"""
    from pet.app import AppShell

    assert callable(getattr(AppShell, "open_memory_card", None))
    assert callable(getattr(AppShell, "open_diary", None))
