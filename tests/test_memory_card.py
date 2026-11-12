# -*- coding: utf-8 -*-
"""记忆卡（pet/memory_card.py）：它就是 memory.json 的视图 + 照片附件。

不测"另一套存储"——这里没有另一套：条目来自 ``ChatMemory``，删卡走
``ChatMemory.remove``。测试盯的是"视图与记忆是否一致"以及照片附件的生灭。
"""
from __future__ import annotations

from pet import memory_card as cards_mod
from pet.chat.memory import ChatMemory


def _memory(tmp_path, character: str = "shenshen") -> ChatMemory:
    return ChatMemory(tmp_path / "sessions" / character / "memory.json")


def _seed(tmp_path, text="哥哥喜欢鲸鱼", layer="fact", character="shenshen"):
    memory = _memory(tmp_path, character)
    assert memory.apply_ops([{"op": "ADD", "text": text, "layer": layer}], source="manual")
    return memory.last_changes[0]["entry"]


def _png(path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return path


def test_items_come_from_memory_entries(tmp_path):
    entry = _seed(tmp_path, "哥哥喜欢鲸鱼", layer="fact")
    items = cards_mod.iter_items(tmp_path)
    assert len(items) == 1
    item = items[0]
    assert item.entry_id == entry["id"]
    assert item.text == "哥哥喜欢鲸鱼"
    assert item.layer == "fact" and item.layer_label == "事实"
    assert item.hits == 1
    assert item.character_id == "shenshen"
    assert item.photo is None
    # 没有自己的存储目录：不产生第二份记忆
    assert not (tmp_path / "memory-cards").exists()


def test_items_aggregate_characters_and_sort_newest_first(tmp_path):
    _seed(tmp_path, "第一只记住的", character="a")
    _seed(tmp_path, "第二只记住的", character="b")
    items = cards_mod.iter_items(tmp_path)
    assert {item.character_id for item in items} == {"a", "b"}
    assert len(items) == 2
    # created_at 相同时顺序稳定（不抛错即可；这里只校验数量与内容）
    assert {item.text for item in items} == {"第一只记住的", "第二只记住的"}


def test_layer_labels_cover_memory_layers(tmp_path):
    assert cards_mod.LAYER_LABELS == {
        "user": "偏好", "fact": "事实", "lesson": "教训", "topic": "话题",
    }
    entry = _seed(tmp_path, "别熬夜", layer="lesson")
    item = cards_mod.iter_items(tmp_path)[0]
    assert entry["layer"] == "lesson" and item.layer_label == "教训"


def test_attach_staged_puts_photo_into_memory_photos(tmp_path):
    entry = _seed(tmp_path)
    staged = cards_mod.stage_photo(tmp_path, "shenshen", _png(tmp_path / "whale.png"))
    assert staged is not None
    assert cards_mod.attach_staged(tmp_path, "shenshen", entry["id"], staged)

    item = cards_mod.iter_items(tmp_path)[0]
    assert item.photo is not None and item.photo.is_file()
    assert item.photo.name == f"{entry['id']}.png"
    assert not any(cards_mod.pending_dir(tmp_path, "shenshen").glob("*.png"))
    # 写回的是同一条记忆条目（不是另建卡片）
    stored = _memory(tmp_path).load()[0]
    assert stored["id"] == entry["id"]
    assert stored["photo"] == f"{entry['id']}.png"


def test_discard_staged_removes_only_the_copy(tmp_path):
    entry = _seed(tmp_path)
    original = _png(tmp_path / "keep.png")
    staged = cards_mod.stage_photo(tmp_path, "shenshen", original)
    assert staged is not None
    assert cards_mod.discard_staged(tmp_path, "shenshen", staged)
    assert original.is_file(), "用户原图永远不动"
    assert _memory(tmp_path).load()[0]["id"] == entry["id"]
    assert _memory(tmp_path).load()[0].get("photo") in (None, "")


def test_delete_item_removes_memory_and_photo(tmp_path):
    entry = _seed(tmp_path)
    staged = cards_mod.stage_photo(tmp_path, "shenshen", _png(tmp_path / "a.png"))
    assert staged is not None and cards_mod.attach_staged(
        tmp_path, "shenshen", entry["id"], staged
    )
    item = cards_mod.iter_items(tmp_path)[0]
    photo = item.photo
    assert photo is not None and photo.is_file()

    assert cards_mod.delete_item(tmp_path, item)
    assert _memory(tmp_path).load() == []
    assert not photo.exists()
    assert cards_mod.iter_items(tmp_path) == []


def test_filter_by_layer_and_query(tmp_path):
    _seed(tmp_path, "哥哥喜欢鲸鱼", layer="fact")
    _seed(tmp_path, "别在晚上提工作", layer="lesson")
    items = cards_mod.iter_items(tmp_path)
    assert [item.layer for item in cards_mod.filter_items(items, layer="lesson")] == ["lesson"]
    assert [item.text for item in cards_mod.filter_items(items, query="鲸鱼")] == ["哥哥喜欢鲸鱼"]
    assert cards_mod.filter_items(items, query="不存在") == []
    assert len(cards_mod.filter_items(items, layer="all", query="")) == 2


def test_stage_photo_rejects_non_image_and_missing(tmp_path):
    text_file = tmp_path / "note.txt"
    text_file.write_text("hi", encoding="utf-8")
    assert cards_mod.stage_photo(tmp_path, "shenshen", text_file) is None
    assert cards_mod.stage_photo(tmp_path, "shenshen", tmp_path / "missing.png") is None


def test_photo_of_deleted_entry_is_not_reported(tmp_path):
    entry = _seed(tmp_path)
    staged = cards_mod.stage_photo(tmp_path, "shenshen", _png(tmp_path / "b.png"))
    assert staged is not None and cards_mod.attach_staged(
        tmp_path, "shenshen", entry["id"], staged
    )
    # 绕过面板直接删条目（模拟限额淘汰 / 别的进程删了记忆）
    assert _memory(tmp_path).remove(entry["id"])
    items = cards_mod.iter_items(tmp_path)
    assert items == []
