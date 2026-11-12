# -*- coding: utf-8 -*-
"""角色卡读 Markdown / 感受字段：两个新入口的契约测试。

- 角色卡：``.json`` 与 ``.md`` / ``.txt`` 都能读；md 只取人设、不带台词；
  导入统一落成 JSON，重复导入同内容同 id。
- 感受：记忆条目带 ``feeling``（第一人称），提炼 / 照片判断都会写；
  它只在记忆卡上展示，不进注入。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pet import memory_card as cards_mod
from pet.chat.memory import ChatMemory
from pet.persona_cards import (
    SUPPLEMENT_HEADER,
    all_cards,
    card_from_markdown,
    card_to_markdown,
    compose_prompt,
    import_card,
    load_card_file,
    prompt_source,
)


# ---------------------------------------------------------------- 角色卡：Markdown


def test_markdown_card_uses_title_and_body(tmp_path):
    path = tmp_path / "dudu.md"
    path.write_text(
        "# 角色卡：嘟嘟\n\n## 一、你是谁\n\n- 你叫嘟嘟，是哥哥桌面上的小肥鱼。\n",
        encoding="utf-8",
    )
    card = load_card_file(path)
    assert card is not None
    assert card.name == "嘟嘟"          # 「角色卡：」前缀被去掉
    assert card.id.startswith("md-")
    assert card.phrases == {}           # md 没有台词
    assert card.system_prompt.startswith("## 一、你是谁")
    assert "角色卡：嘟嘟" not in card.system_prompt


def test_plain_text_without_title_uses_filename(tmp_path):
    path = tmp_path / "my-persona.txt"
    path.write_text("你是一只安静的猫，说话很短。", encoding="utf-8")
    card = load_card_file(path)
    assert card is not None
    assert card.name == "my-persona"
    assert card.system_prompt == "你是一只安静的猫，说话很短。"


def test_same_markdown_gives_same_id(tmp_path):
    a = card_from_markdown("# 嘟嘟\n\n正文")
    b = card_from_markdown("# 嘟嘟\n\n正文")
    assert a is not None and b is not None
    assert a.id == b.id, "同内容必须同 id，否则重复导入会堆出一堆卡"
    c = card_from_markdown("# 嘟嘟\n\n改了正文")
    assert c is not None and c.id != a.id


def test_json_suffix_with_markdown_content_still_reads(tmp_path):
    """用户把 .md 改名成 .json 是常见操作：尽力按 md 读，不直接判死。"""
    path = tmp_path / "wrong.json"
    path.write_text("# 嘟嘟\n\n正文内容", encoding="utf-8")
    card = load_card_file(path)
    assert card is not None and card.name == "嘟嘟"


def test_import_markdown_lands_as_json_card(tmp_path):
    src = tmp_path / "in.md"
    src.write_text("# 小灰\n\n你是一只灰猫。", encoding="utf-8")
    card = import_card(tmp_path / "cfg", src)
    assert card is not None
    saved = tmp_path / "cfg" / "persona-cards" / f"{card.id}.json"
    assert saved.is_file(), "md 导入应落成标准 JSON 卡"
    reloaded = {c.id: c for c in all_cards(tmp_path / "cfg")}
    assert reloaded[card.id].name == "小灰"
    assert reloaded[card.id].system_prompt == "你是一只灰猫。"


def test_card_to_markdown_roundtrip_keeps_prompt():
    card = card_from_markdown("# 嘟嘟\n\n你是嘟嘟，说话很短。")
    assert card is not None
    text = card_to_markdown(card)
    again = card_from_markdown(text)
    assert again is not None
    assert again.name == "嘟嘟"
    assert again.system_prompt == card.system_prompt


def test_prompt_source_marker():
    assert prompt_source({"prompt_source": "card:dudu"}) == "card:dudu"
    assert prompt_source({}) == ""


# ---------------------------------------------------------------- 感受（feeling）


def _memory(tmp_path) -> ChatMemory:
    return ChatMemory(tmp_path / "sessions" / "shenshen" / "memory.json")


def test_extraction_writes_feeling_and_card_shows_it(tmp_path):
    memory = _memory(tmp_path)
    assert memory.apply_ops(
        [
            {
                "op": "ADD",
                "text": "哥哥生日是 1 月 11 日",
                "layer": "fact",
                "feeling": "他把生日告诉我了，我有点开心",
            }
        ],
        source="auto",
    )
    entry = memory.load()[0]
    assert entry["feeling"] == "他把生日告诉我了，我有点开心"

    item = cards_mod.iter_items(tmp_path)[0]
    assert item.text == "哥哥生日是 1 月 11 日"
    assert item.feeling == "他把生日告诉我了，我有点开心"


def test_feeling_is_trimmed_and_replaced_on_repeat(tmp_path):
    memory = _memory(tmp_path)
    memory.apply_ops(
        [{"op": "ADD", "text": "哥哥怕冷", "feeling": "  他\n总是  穿很多  "}],
        source="auto",
    )
    assert memory.load()[0]["feeling"] == "他 总是 穿很多"

    memory.apply_ops(
        [{"op": "ADD", "text": "哥哥怕冷", "feeling": "我会记得给他留件外套"}],
        source="auto",
    )
    assert memory.load()[0]["feeling"] == "我会记得给他留件外套"


def test_manual_add_can_carry_feeling(tmp_path):
    memory = _memory(tmp_path)
    result = memory.add("记住：哥哥不吃香菜", feeling="这条我得记牢")
    assert result is not None
    assert memory.load()[0]["feeling"] == "这条我得记牢"


def test_feeling_absent_stays_absent(tmp_path):
    memory = _memory(tmp_path)
    memory.apply_ops([{"op": "ADD", "text": "哥哥喜欢猫"}], source="auto")
    assert "feeling" not in memory.load()[0]
    assert cards_mod.iter_items(tmp_path)[0].feeling == ""


def test_feeling_does_not_enter_injection(tmp_path):
    """感受只给人看：注入段里不该出现（否则会挤占对话预算、也不是给模型的指令）。"""
    from pet.chat.memory import render_injection

    memory = _memory(tmp_path)
    memory.apply_ops(
        [{"op": "ADD", "text": "哥哥喜欢鲸鱼", "feeling": "被记住这件事让我很开心"}],
        source="auto",
    )
    assert "被记住这件事让我很开心" not in render_injection(memory.load())


def test_photo_verdict_feeling_is_written(tmp_path):
    from pet.chat import photo_memory

    class _Provider:
        def stream(self, messages, config, cancel):
            yield (
                '{"keep": true, "note": "哥哥画的鲸鱼", '
                '"feeling": "他居然真的画了，我有点想笑"}'
            )

    photo = tmp_path / "w.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    staged = cards_mod.stage_photo(tmp_path, "shenshen", photo)
    assert staged is not None
    from types import SimpleNamespace

    photo_memory._run(
        tmp_path, "shenshen", [staged], "画好了", "好看嘟",
        _Provider(), SimpleNamespace(model="m", thinking="auto", reasoning_effort="high"),
    )
    entry = _memory(tmp_path).load()[0]
    assert entry["text"] == "哥哥画的鲸鱼"
    assert entry["feeling"] == "他居然真的画了，我有点想笑"
    assert cards_mod.iter_items(tmp_path)[0].feeling == entry["feeling"]


def test_feeling_clipped_to_limit(tmp_path):
    from pet.chat.memory import MAX_FEELING_CHARS

    memory = _memory(tmp_path)
    memory.apply_ops(
        [{"op": "ADD", "text": "很长的一句感受", "feeling": "啊" * 500}],
        source="auto",
    )
    assert len(memory.load()[0]["feeling"]) == MAX_FEELING_CHARS


def test_created_at_sorting_still_works_with_feeling(tmp_path):
    """加字段不该影响面板原有的排序口径（最新在前）。"""
    memory = _memory(tmp_path)
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    memory._clock = lambda: now  # noqa: SLF001 - 测试固定时钟
    memory.apply_ops([{"op": "ADD", "text": "先记的", "feeling": "开心"}], source="auto")
    items = cards_mod.iter_items(tmp_path)
    assert items[0].text == "先记的"
    assert items[0].feeling == "开心"

# ---------------------------------------------------------------- 人设两段式（主体 + 补充）


def test_compose_prompt_merges_supplement():
    text = compose_prompt("你是嘟嘟。", "回答不要用表情符号。")
    assert text.startswith("你是嘟嘟。")
    assert SUPPLEMENT_HEADER in text
    assert text.endswith("回答不要用表情符号。")


def test_compose_prompt_without_supplement_or_merge():
    assert compose_prompt("你是嘟嘟。", "") == "你是嘟嘟。"
    assert compose_prompt("你是嘟嘟。", "补充", merge=False) == "你是嘟嘟。"
    assert compose_prompt("", "只有补充") == "只有补充"
    assert compose_prompt("", "") == ""


def test_apply_card_keeps_supplement_in_composition():
    """应用角色卡只换主体；补充段照样叠在后面（这就是"共同作用"）。"""
    card = card_from_markdown("# 嘟嘟\n\n你是嘟嘟，说话很短。")
    assert card is not None
    final = compose_prompt(card.system_prompt, "不要叫我主人", merge=True)
    assert card.system_prompt in final
    assert "不要叫我主人" in final
    # 关掉叠加：补充不生效，但仍然留在配置里（由设置页自己保存）
    off = compose_prompt(card.system_prompt, "不要叫我主人", merge=False)
    assert off == card.system_prompt.strip()

# ---------------------------------------------------------------- 设置页：补充与卡共存


def _ai_page(tmp_path, monkeypatch):
    import pet.modern_settings_dialog as settings_mod
    from PySide6.QtWidgets import QApplication

    from pet.chat.ai_settings_page import _AiSettingsPage
    from pet.config import Config

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    config = Config(tmp_path)
    return config, _AiSettingsPage(config)


def _write_card(config_dir, card_id: str, name: str, prompt: str) -> None:
    import json

    folder = Path(config_dir) / "persona-cards"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{card_id}.json").write_text(
        json.dumps(
            {
                "version": "persona-card/v1",
                "id": card_id,
                "name": name,
                "system_prompt": prompt,
                "phrases": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_settings_supplement_merges_and_survives_card_apply(tmp_path, monkeypatch):
    config, page = _ai_page(tmp_path, monkeypatch)
    try:
        page.prompt.setPlainText("你是嘟嘟。")
        page.prompt_supplement.setPlainText("不要用表情符号")
        page.save()

        assert config.get("prompt_base") == "你是嘟嘟。"
        assert config.get("prompt_supplement") == "不要用表情符号"
        assert config.get("prompt_merge") is True
        merged = config.chat_settings().default_system_prompt
        assert "你是嘟嘟。" in merged and "不要用表情符号" in merged

        # 应用角色卡：主体换掉，补充必须保留
        _write_card(config.dir, "xi", "小 X", "你是小 X，说话很短。")
        page._reload_persona_cards()
        page.persona_card_combo.setCurrentIndex(
            page.persona_card_combo.findData("xi")
        )
        page._apply_persona_card()

        after = config.chat_settings().default_system_prompt
        assert "你是小 X，说话很短。" in after
        assert "不要用表情符号" in after, "应用卡不能把用户补充冲掉"

        # 关掉叠加：只用主体，补充留在配置里
        page.prompt_merge.setChecked(False)
        page.save()
        final = config.chat_settings().default_system_prompt
        assert final.strip() == "你是小 X，说话很短。"
        assert config.get("prompt_supplement") == "不要用表情符号"

        # 再打开：补充回来
        page.prompt_merge.setChecked(True)
        page.save()
        again = config.chat_settings().default_system_prompt
        assert "不要用表情符号" in again
    finally:
        page.deleteLater()


def test_settings_prompt_source_tracks_card_then_manual(tmp_path, monkeypatch):
    config, page = _ai_page(tmp_path, monkeypatch)
    try:
        _write_card(config.dir, "xi", "小 X", "你是小 X。")
        page._reload_persona_cards()
        page.persona_card_combo.setCurrentIndex(page.persona_card_combo.findData("xi"))
        page._apply_persona_card()
        assert config.get("prompt_source") == "card:xi"

        page.prompt.setPlainText("你是别人了。")
        page.save()
        assert config.get("prompt_source") == "manual"
    finally:
        page.deleteLater()


def test_legacy_prompt_shows_as_base_on_open(tmp_path, monkeypatch):
    """老配置只有 default_system_prompt：打开设置页时它应当显示为主体。"""
    from pet.config import Config

    config = Config(tmp_path)
    config.set("prompt_base", "")
    config.set("prompt_supplement", "")
    existing = config.chat_settings().default_system_prompt
    config.save()

    _config, page = _ai_page(tmp_path, monkeypatch)
    try:
        assert page.prompt.toPlainText().strip() == existing.strip()
        assert page.prompt_supplement.toPlainText() == ""
    finally:
        page.deleteLater()
