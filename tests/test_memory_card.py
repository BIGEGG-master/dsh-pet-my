# -*- coding: utf-8 -*-
"""记忆卡（pet/memory_card.py）：文字/照片卡片、备注、检索、删除。"""
from __future__ import annotations

import json

from pet.memory_card import (
    MAX_NOTE_CHARS,
    add_photo,
    add_text,
    card_day,
    cards_dir,
    delete_card,
    filter_cards,
    index_path,
    load_cards,
    photo_abs_path,
    photos_dir,
    stats,
    summary,
    update_note,
)


def _png(path):
    """最小的合法 PNG 头（内容不需要能解码，测试只关心复制与后缀）。"""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return path


def test_add_text_keeps_note_and_lists_newest_first(tmp_path):
    first = add_text(tmp_path, "哥哥喜欢鲸鱼", note="哥哥说的")
    second = add_text(tmp_path, "今天吃面")
    assert first is not None and second is not None
    cards = load_cards(tmp_path)
    assert [card["id"] for card in cards] == [second["id"], first["id"]]
    assert cards[1]["note"] == "哥哥说的"
    assert cards[1]["kind"] == "text"
    assert card_day(cards[0]) == cards[0]["created_at"][:10]


def test_add_text_rejects_empty(tmp_path):
    assert add_text(tmp_path, "   ") is None
    assert load_cards(tmp_path) == []
    assert not index_path(tmp_path).exists()


def test_add_photo_copies_into_config_dir(tmp_path):
    source = _png(tmp_path / "whale.png")
    card = add_photo(tmp_path, source, note="哥哥画的鲸鱼")
    assert card is not None and card["kind"] == "photo"
    assert source.is_file(), "原图必须原样保留（用户文件只读）"
    copied = photo_abs_path(tmp_path, card)
    assert copied is not None and copied.is_file()
    assert copied.read_bytes() == source.read_bytes()
    assert copied.parent == photos_dir(tmp_path)
    assert load_cards(tmp_path)[0]["note"] == "哥哥画的鲸鱼"


def test_add_photo_rejects_non_image_and_missing(tmp_path):
    text_file = tmp_path / "note.txt"
    text_file.write_text("hi", encoding="utf-8")
    assert add_photo(tmp_path, text_file) is None
    assert add_photo(tmp_path, tmp_path / "missing.png") is None
    assert load_cards(tmp_path) == []


def test_update_note_truncates_and_reports_missing(tmp_path):
    card = add_text(tmp_path, "正文")
    assert card is not None
    assert update_note(tmp_path, card["id"], "新备注" * 30)
    assert len(load_cards(tmp_path)[0]["note"]) == MAX_NOTE_CHARS
    assert update_note(tmp_path, "nope", "x") is False


def test_delete_card_removes_photo_copy(tmp_path):
    card = add_photo(tmp_path, _png(tmp_path / "a.png"))
    assert card is not None
    copied = photo_abs_path(tmp_path, card)
    assert copied is not None
    assert delete_card(tmp_path, card["id"]) is True
    assert not copied.exists()
    assert load_cards(tmp_path) == []
    assert delete_card(tmp_path, card["id"]) is False


def test_filter_by_kind_day_and_query(tmp_path):
    text_card = add_text(tmp_path, "哥哥说想养鲸鱼", note="养鲸鱼")
    photo_card = add_photo(tmp_path, _png(tmp_path / "b.png"), note="哥哥画的鲸鱼")
    assert text_card is not None and photo_card is not None
    day = card_day(text_card)
    assert [c["id"] for c in filter_cards(load_cards(tmp_path), kind="photo")] == [photo_card["id"]]
    assert [c["id"] for c in filter_cards(load_cards(tmp_path), kind="text")] == [text_card["id"]]
    assert len(filter_cards(load_cards(tmp_path), day=day)) == 2
    assert [c["id"] for c in filter_cards(load_cards(tmp_path), query="鲸鱼")] == [
        photo_card["id"],
        text_card["id"],
    ]
    assert filter_cards(load_cards(tmp_path), query="不存在的东西") == []


def test_corrupt_index_is_quarantined_and_rebuilt(tmp_path):
    cards_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    index_path(tmp_path).write_text("{ not json", encoding="utf-8")
    assert load_cards(tmp_path) == []
    assert list(cards_dir(tmp_path).glob("index.corrupt-*.json")), "坏索引必须改名保留"
    assert add_text(tmp_path, "重建之后还能用") is not None
    assert json.loads(index_path(tmp_path).read_text(encoding="utf-8"))["version"] == 1


def test_stats_and_summary(tmp_path):
    add_text(tmp_path, "一条文字")
    add_photo(tmp_path, _png(tmp_path / "c.png"), note="照片备注")
    assert stats(tmp_path) == {"total": 2, "text": 1, "photo": 1}
    assert summary({"text": "x" * 200}) .endswith("…")
    assert summary({"text": "", "note": "只有备注"}) == "只有备注"
