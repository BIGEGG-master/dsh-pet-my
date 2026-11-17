# -*- coding: utf-8 -*-
"""记忆卡面板 / 日记窗 / 照片记忆：UI 行为与她自己的记忆判断（不联网、不打真窗口）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from pet import memory_card as cards_mod
from pet.chat.memory import ChatMemory


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _png(path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return path


def _memory(tmp_path, character="shenshen"):
    return ChatMemory(tmp_path / "sessions" / character / "memory.json")


def _seed(tmp_path, text="哥哥喜欢鲸鱼", layer="fact"):
    memory = _memory(tmp_path)
    assert memory.apply_ops([{"op": "ADD", "text": text, "layer": layer}], source="manual")
    return memory.last_changes[0]["entry"]


# ---------------------------------------------------------------- 记忆卡面板


def test_memory_card_dialog_lists_searches_and_filters(tmp_path):
    _app()
    from pet.memory_card_dialog import MemoryCardDialog

    dialog = MemoryCardDialog(tmp_path)
    assert dialog.item_count == 0  # 没有记忆：空状态可见

    _seed(tmp_path, "哥哥喜欢鲸鱼", layer="fact")
    _seed(tmp_path, "别在晚上提工作", layer="lesson")
    dialog.reload()
    assert dialog.item_count == 2

    dialog._search.setText("鲸鱼")
    assert dialog.item_count == 1
    dialog._search.clear()
    dialog._layer.setCurrentIndex(3)  # 教训
    assert dialog.item_count == 1
    dialog._layer.setCurrentIndex(0)
    assert dialog.item_count == 2
    dialog.deleteLater()
    _app().processEvents()


def test_memory_card_detail_deletes_through_memory(tmp_path, monkeypatch):
    _app()
    from pet.memory_card_dialog import CardDetailDialog

    _seed(tmp_path, "这条要删掉")
    item = cards_mod.iter_items(tmp_path)[0]
    dialog = CardDetailDialog(tmp_path, item)

    # conftest 把 QMessageBox.question 默认成 No（安全拒绝），这里显式放行一次
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    dialog._delete()
    assert _memory(tmp_path).load() == []
    assert cards_mod.iter_items(tmp_path) == []
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


# ---------------------------------------------------------------- 照片记忆（她判断该不该记）


class _FakeProvider:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def stream(self, messages, config, cancel):  # noqa: ARG002 - 与真实 provider 同签名
        yield self.answer


def _fake_config():
    return SimpleNamespace(model="m", thinking="auto", reasoning_effort="high")


def test_parse_verdict_accepts_json_and_string_flags():
    from pet.chat.photo_memory import parse_verdict

    verdict = parse_verdict('{"keep": true, "note": "「哥哥画的鲸鱼」"}')
    assert verdict == {"keep": True, "note": "哥哥画的鲸鱼", "feeling": ""}
    assert parse_verdict('{"keep": "false", "note": "随手截图"}')["keep"] is False
    assert parse_verdict('```json\n{"keep": true, "note": "哥哥的晚饭"}\n```')["note"] == "哥哥的晚饭"
    assert parse_verdict("完全不是 JSON") is None


def test_photo_memory_keep_writes_one_memory_with_photo(tmp_path):
    from pet.chat import photo_memory

    staged = cards_mod.stage_photo(tmp_path, "shenshen", _png(tmp_path / "x.png"))
    assert staged is not None and Path(staged["path"]).is_file()
    photo_memory._run(
        tmp_path, "shenshen", [staged], "画好了", "好可爱嘟",
        _FakeProvider('{"keep": true, "note": "哥哥画的鲸鱼"}'), _fake_config(),
    )
    entries = _memory(tmp_path).load()
    assert len(entries) == 1
    assert entries[0]["text"] == "哥哥画的鲸鱼"
    assert entries[0]["layer"] == "topic"
    assert entries[0]["source"] == "auto"
    assert entries[0]["photo"]
    assert not Path(staged["path"]).exists(), "转正后暂存副本要清掉"

    item = cards_mod.iter_items(tmp_path)[0]
    assert item.photo is not None and item.photo.is_file()


def test_photo_memory_discards_when_she_says_no(tmp_path):
    from pet.chat import photo_memory

    staged = cards_mod.stage_photo(tmp_path, "shenshen", _png(tmp_path / "y.png"))
    assert staged is not None
    photo_memory._run(
        tmp_path, "shenshen", [staged], "截图", "嗯",
        _FakeProvider('{"keep": false, "note": "随手截图"}'), _fake_config(),
    )
    assert _memory(tmp_path).load() == []
    assert cards_mod.iter_items(tmp_path) == []
    assert not Path(staged["path"]).exists()


def test_photo_memory_failure_keeps_memory_with_fallback_note(tmp_path):
    from pet.chat import photo_memory

    class _Boom:
        def stream(self, messages, config, cancel):
            raise RuntimeError("network down")

    staged = cards_mod.stage_photo(tmp_path, "shenshen", _png(tmp_path / "z.png"))
    assert staged is not None
    photo_memory._run(tmp_path, "shenshen", [staged], "这是我画的鲸鱼", "好看嘟", _Boom(), _fake_config())
    entries = _memory(tmp_path).load()
    assert len(entries) == 1
    assert entries[0]["text"] == "这是我画的鲸鱼"
    assert entries[0]["photo"]


def test_schedule_photo_memory_guards(tmp_path):
    from pet import feature_activation as fa
    from pet.chat import photo_memory

    photo_memory.reset_for_tests()
    staged = cards_mod.stage_photo(tmp_path, "shenshen", _png(tmp_path / "w.png"))
    assert staged is not None
    assert photo_memory.schedule_photo_memory(
        config_dir=tmp_path, character_id="shenshen", staged=[], user_text="a",
        reply_text="b", provider=None, provider_config=None) is False
    fa.freeze_snapshot_for_tests(set())
    try:
        assert photo_memory.schedule_photo_memory(
            config_dir=tmp_path, character_id="shenshen", staged=[staged],
            user_text="a", reply_text="b",
            provider=_FakeProvider("{}"), provider_config=_fake_config()) is False
    finally:
        fa.reset_snapshot_for_tests()


@pytest.mark.parametrize("text", ["哥哥生日是 1 月 11 日"])
def test_memory_item_text_roundtrip(tmp_path, text):
    _seed(tmp_path, text, layer="fact")
    assert cards_mod.iter_items(tmp_path)[0].text == text


# ---------------------------------------------------------------- 右键菜单入口


def test_menu_has_memory_card_and_diary_entries():
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
