# -*- coding: utf-8 -*-
"""记忆卡与深层记忆是同一份：面板看到的 = 注入时用的那份条目。

这里钉住三件事：
1. 提炼产出的 ADD / FORGET 立刻体现在 ``iter_items()``（没有中间同步步骤）；
2. 面板删除走 ``ChatMemory.remove``，记忆文件真的少一条；
3. 照片是条目的附件（``photo`` 字段 + ``memory-photos/``），条目没了图也没了。
"""
from __future__ import annotations

from pet import memory_card as cards_mod
from pet.chat.memory import ChatMemory


def _memory(tmp_path) -> ChatMemory:
    return ChatMemory(tmp_path / "sessions" / "shenshen" / "memory.json")


def test_extracted_memory_shows_up_without_any_sync_step(tmp_path):
    """提炼写完 memory.json，面板下一次 reload 就能看到——没有第二份存储要同步。"""
    memory = _memory(tmp_path)
    assert memory.apply_ops(
        [{"op": "ADD", "text": "哥哥喜欢鲸鱼", "layer": "fact"}], source="auto"
    )
    items = cards_mod.iter_items(tmp_path)
    assert [item.text for item in items] == ["哥哥喜欢鲸鱼"]
    assert items[0].entry_id == memory.last_changes[0]["entry"]["id"]


def test_forget_from_extraction_removes_the_card(tmp_path):
    memory = _memory(tmp_path)
    memory.apply_ops([{"op": "ADD", "text": "哥哥不吃辣"}], source="auto")
    assert len(cards_mod.iter_items(tmp_path)) == 1

    memory.apply_ops([{"op": "FORGET", "text": "哥哥不吃辣"}], source="auto")
    assert cards_mod.iter_items(tmp_path) == []


def test_repeat_mention_updates_same_entry_not_a_second_card(tmp_path):
    memory = _memory(tmp_path)
    memory.apply_ops([{"op": "ADD", "text": "哥哥养了一只猫"}], source="auto")
    memory.apply_ops([{"op": "ADD", "text": "哥哥养了一只猫"}], source="auto")
    items = cards_mod.iter_items(tmp_path)
    assert len(items) == 1
    assert items[0].hits == 2, "重申只 +hits（记忆模块自己的规则），不新增卡"


def test_panel_delete_goes_through_memory_remove(tmp_path):
    memory = _memory(tmp_path)
    memory.apply_ops([{"op": "ADD", "text": "临时记住的一条"}], source="auto")
    item = cards_mod.iter_items(tmp_path)[0]

    assert cards_mod.delete_item(tmp_path, item)
    assert _memory(tmp_path).load() == []
    assert cards_mod.iter_items(tmp_path) == []


def test_archived_entry_still_visible_with_flag(tmp_path):
    """归档条目不再注入，但仍在记忆文件里——面板如实显示，不假装没有。"""
    memory = _memory(tmp_path)
    memory.apply_ops([{"op": "ADD", "text": "很久以前的话题", "layer": "topic"}], source="auto")
    entries = memory.load()
    entries[0]["archived"] = True
    memory._write(entries)  # noqa: SLF001 - 模拟归档巡检

    item = cards_mod.iter_items(tmp_path)[0]
    assert item.archived is True
    assert item.text == "很久以前的话题"


def test_photo_attachment_belongs_to_the_entry(tmp_path):
    memory = _memory(tmp_path)
    memory.apply_ops([{"op": "ADD", "text": "哥哥画的鲸鱼", "layer": "topic"}], source="auto")
    entry_id = memory.last_changes[0]["entry"]["id"]
    photo = tmp_path / "w.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    staged = cards_mod.stage_photo(tmp_path, "shenshen", photo)
    assert staged is not None
    assert cards_mod.attach_staged(tmp_path, "shenshen", entry_id, staged)

    item = cards_mod.iter_items(tmp_path)[0]
    assert item.photo is not None and item.photo.parent.name == "memory-photos"
    # 条目被删（限额淘汰 / 用户删），照片跟着走
    assert cards_mod.delete_item(tmp_path, item)
    assert not item.photo.exists()
