# -*- coding: utf-8 -*-
"""角色卡（pet/persona_cards.py）：内置卡加载、应用、模板转换、用户卡覆盖。"""
from __future__ import annotations

import json

from pet.persona_cards import (
    PersonaCard,
    all_cards,
    apply_card,
    builtin_cards,
    card_from_dict,
    card_to_persona_template,
    find_card,
    import_card,
    save_user_card,
    user_cards,
)


def test_builtin_cards_include_feiyu():
    ids = [card.id for card in builtin_cards()]
    assert "feiyu" in ids
    card = find_card("feiyu")
    assert card is not None
    assert card.name == "小肥鱼"
    assert card.system_prompt.startswith("你是「小肥鱼」")
    assert len(card.phrases) == 30
    assert card.aliases.get("shenshen") == "小肥鱼"


def test_builtin_cards_include_dudu():
    """嘟嘟角色卡：内置「小肥鱼」之外的第二个身份，素材仍复用同一只桌宠。"""
    ids = [card.id for card in builtin_cards()]
    assert "dudu" in ids
    card = find_card("dudu")
    assert card is not None
    assert card.name == "嘟嘟"
    assert card.system_prompt.startswith("你是「嘟嘟」")
    assert card.aliases.get("shenshen") == "嘟嘟"
    # 与内置卡同口径：30 组台词（每组不超过 8 条、单条不超过 120 字）。
    assert len(card.phrases) == 30
    assert card.phrase_count >= 80
    # 口吻红线：一句里最多一个「嘟」。
    for key, texts in card.phrases.items():
        for text in texts:
            assert text.count("嘟") <= 1, f"{key}: {text}"


def test_dudu_card_covers_every_preset_phrase_key():
    """事件台词覆盖面：嘟嘟卡必须覆盖内置「小肥鱼」的每一个事件键。"""
    feiyu = find_card("feiyu")
    dudu = find_card("dudu")
    assert feiyu is not None and dudu is not None
    assert set(dudu.phrases) == set(feiyu.phrases)


def test_apply_card_writes_identity_only():
    card = find_card("feiyu")
    config = {
        "chat": {"default_system_prompt": "旧人设", "active_provider": "x"},
        "character_aliases": {"shenshen": "深深"},
        "dialogue_mode": "legacy",
        "dialogue_phrases": {},
        "agent_link": {"dsh": True},
    }
    written = apply_card(config, card, ["shenshen"])
    assert written["system_prompt"] is True
    assert written["phrases"] == 30
    assert config["dialogue_mode"] == "custom"
    assert config["character_aliases"]["shenshen"] == "小肥鱼"
    assert len(config["dialogue_phrases"]) == 30
    # 无关配置不动
    assert config["chat"]["active_provider"] == "x"
    assert config["agent_link"] == {"dsh": True}


def test_apply_card_falls_back_to_characters_when_no_aliases():
    card = PersonaCard(id="t", name="测试角色")
    config: dict = {}
    written = apply_card(config, card, ["shenshen", "other"])
    assert written["aliases"] == {"shenshen": "测试角色", "other": "测试角色"}
    # 没有 phrases / system_prompt 时不动这些键
    assert "dialogue_phrases" not in config
    assert "chat" not in config


def test_card_to_persona_template_is_v1():
    card = find_card("feiyu")
    template = card_to_persona_template(card)
    assert template["template"] == "persona-phrases/v1"
    assert template["mode"] == "custom"
    assert template["name"] == "小肥鱼"
    assert len(template["phrases"]) == 30


def test_card_from_dict_rejects_incomplete():
    assert card_from_dict({}) is None
    assert card_from_dict({"id": "x"}) is None
    assert card_from_dict({"name": "只有名字"}) is None
    assert card_from_dict("not a dict") is None


def test_user_card_overrides_builtin(tmp_path):
    custom = PersonaCard(id="feiyu", name="小肥鱼（私人改）", system_prompt="改过的人设")
    save_user_card(tmp_path, custom)
    cards = {card.id: card for card in all_cards(tmp_path)}
    assert cards["feiyu"].name == "小肥鱼（私人改）"
    assert len(user_cards(tmp_path)) == 1


def test_import_card_from_file(tmp_path):
    source = tmp_path / "incoming.json"
    source.write_text(
        json.dumps(
            {
                "id": "imported",
                "name": "导入的角色",
                "phrases": {"start": ["开工啦", "开工啦", "  "]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    card = import_card(tmp_path / "cfg", source)
    assert card is not None
    assert card.id == "imported"
    # 台词去重 + 空白项丢弃
    assert card.phrases["start"] == ["开工啦"]
    assert (tmp_path / "cfg" / "persona-cards" / "imported.json").is_file()
