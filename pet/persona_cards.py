# -*- coding: utf-8 -*-
"""角色卡：一份可整体切换的**角色身份**（人设 + 显示名 + 事件台词）。

与「台词模板」(``persona_template``) 的分工：
- 台词模板只覆盖 ``dialogue_phrases``（一个事件一组文案），是**表达层**的补丁；
- 角色卡是**一个角色**的完整身份，应用时同时改三处：
  ``chat.default_system_prompt``（人设）、``character_aliases``（显示名）、
  ``dialogue_mode`` + ``dialogue_phrases``（口吻）。

为什么需要它：桌宠只有一套立绘素材，但用户可能想让同一只桌宠说不同角色的话
（比如插件里已有的「小肥鱼」）。切角色卡不改素材、不重启，只换身份三件套。

卡从两处加载（同 id 时用户卡优先）：
- 内置：``pet/persona_cards/builtin/*.json``（随包分发）
- 用户：``<config_dir>/persona-cards/*.json``（设置页导入/导出）

卡格式（``persona-card/v1``）::

    {
      "version": "persona-card/v1",
      "id": "feiyu",
      "name": "小肥鱼",
      "system_prompt": "你是「小肥鱼」……",
      "aliases": {"shenshen": "小肥鱼"},
      "phrases": {"activity.default": ["……", "……"]}
    }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

log = logging.getLogger(__name__)

CARD_VERSION = "persona-card/v1"
CARD_SUFFIX = ".json"
#: 单条台词上限（与 config 的 dialogue_phrases 清洗口径一致）
MAX_PHRASE_CHARS = 120
#: 每个事件最多保留几条变体
MAX_PHRASES_PER_KEY = 8


def _builtin_dir() -> Path:
    return Path(__file__).resolve().parent / "persona_cards" / "builtin"


def user_dir(config_dir: Path | str) -> Path:
    """用户卡目录（与 config.json 同级，便于整体备份/迁移）。"""
    return Path(config_dir) / "persona-cards"


@dataclass(frozen=True)
class PersonaCard:
    """一份角色卡（不可变；应用时才写进配置）。"""

    id: str
    name: str
    system_prompt: str = ""
    phrases: dict[str, list[str]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    source: str = ""
    path: Path | None = None

    @property
    def phrase_count(self) -> int:
        return sum(len(items) for items in self.phrases.values())

    def describe(self) -> str:
        """设置页/日志用的一行摘要。"""
        parts = [f"{len(self.phrases)} 组台词"]
        if self.system_prompt:
            parts.append("含人设")
        if self.aliases:
            parts.append("改显示名")
        return "、".join(parts)


def _clean_phrases(raw: Any) -> dict[str, list[str]]:
    """事件台词归一化：键必须是非空 str，值是非空字符串列表（截断/去重/限量）。"""
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, list[str]] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name:
            continue
        if isinstance(value, str):
            items: Iterable[Any] = [value]
        elif isinstance(value, (list, tuple)):
            items = value
        else:
            continue
        texts: list[str] = []
        for item in items:
            if not isinstance(item, str):
                continue
            text = item.strip()[:MAX_PHRASE_CHARS]
            if text and text not in texts:
                texts.append(text)
            if len(texts) >= MAX_PHRASES_PER_KEY:
                break
        if texts:
            cleaned[name] = texts
    return cleaned


def _clean_aliases(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        character = str(key or "").strip()
        name = str(value or "").strip()
        if character and name:
            out[character] = name
    return out


def card_from_dict(data: Any, *, source: str = "", path: Path | None = None) -> PersonaCard | None:
    """从 dict 构造角色卡；非法（缺 id/name）返回 ``None``。"""
    if not isinstance(data, Mapping):
        return None
    card_id = str(data.get("id") or "").strip()
    name = str(data.get("name") or "").strip()
    if not card_id or not name:
        return None
    return PersonaCard(
        id=card_id,
        name=name,
        system_prompt=str(data.get("system_prompt") or "").strip(),
        phrases=_clean_phrases(data.get("phrases")),
        aliases=_clean_aliases(data.get("aliases")),
        source=source or str(data.get("source") or ""),
        path=path,
    )


def load_card_file(path: Path) -> PersonaCard | None:
    """读一份卡文件；坏文件只记日志（不影响其它卡）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("角色卡读取失败: %s (%s)", path, exc)
        return None
    return card_from_dict(data, source=str(path.parent.name), path=path)


def _load_dir(directory: Path, source: str) -> list[PersonaCard]:
    cards: list[PersonaCard] = []
    try:
        files = sorted(p for p in directory.glob("*" + CARD_SUFFIX) if p.is_file())
    except OSError:
        return cards
    for path in files:
        card = load_card_file(path)
        if card is not None:
            cards.append(card)
    return cards


def builtin_cards() -> list[PersonaCard]:
    return _load_dir(_builtin_dir(), "builtin")


def user_cards(config_dir: Path | str) -> list[PersonaCard]:
    return _load_dir(user_dir(config_dir), "user")


def all_cards(config_dir: Path | str | None = None) -> list[PersonaCard]:
    """全部可用角色卡：内置在前，用户卡同 id 覆盖内置。"""
    merged: dict[str, PersonaCard] = {}
    for card in builtin_cards():
        merged[card.id] = card
    if config_dir is not None:
        for card in user_cards(config_dir):
            merged[card.id] = card
    return list(merged.values())


def find_card(card_id: str, config_dir: Path | str | None = None) -> PersonaCard | None:
    for card in all_cards(config_dir):
        if card.id == card_id:
            return card
    return None


def apply_card(
    config: MutableMapping[str, Any],
    card: PersonaCard,
    characters: Iterable[str] = (),
) -> dict[str, Any]:
    """把角色卡写进配置，返回实际写下的字段（供 UI 展示/测试断言）。

    只动这四类键，不碰 provider/语音/记忆等无关设置：
    ``chat.default_system_prompt``、``character_aliases``、``dialogue_mode``、
    ``dialogue_phrases``。
    """
    written: dict[str, Any] = {}
    if card.system_prompt:
        chat = config.get("chat")
        if not isinstance(chat, dict):
            chat = {}
            config["chat"] = chat
        chat["default_system_prompt"] = card.system_prompt
        written["system_prompt"] = True
    targets = dict(card.aliases)
    if not targets:
        targets = {str(c).strip(): card.name for c in characters if str(c).strip()}
    if targets:
        aliases = config.get("character_aliases")
        aliases = dict(aliases) if isinstance(aliases, Mapping) else {}
        aliases.update(targets)
        config["character_aliases"] = aliases
        written["aliases"] = targets
    if card.phrases:
        config["dialogue_mode"] = "custom"
        config["dialogue_phrases"] = {key: list(value) for key, value in card.phrases.items()}
        written["phrases"] = len(card.phrases)
    return written


def card_to_dict(card: PersonaCard) -> dict[str, Any]:
    """卡 → 可落盘 dict（导出/复制用）。"""
    data: dict[str, Any] = {"version": CARD_VERSION, "id": card.id, "name": card.name}
    if card.system_prompt:
        data["system_prompt"] = card.system_prompt
    if card.aliases:
        data["aliases"] = dict(card.aliases)
    if card.phrases:
        data["phrases"] = {key: list(value) for key, value in card.phrases.items()}
    if card.source:
        data["source"] = card.source
    return data


def card_to_persona_template(card: PersonaCard) -> dict[str, Any]:
    """卡 → ``persona-phrases/v1`` 模板（塞进设置页「导入模板」也能用）。"""
    return {
        "template": "persona-phrases/v1",
        "mode": "custom",
        "name": card.name,
        "description": f"角色卡：{card.name}",
        "phrases": {key: list(value) for key, value in card.phrases.items()},
    }


def export_card(card: PersonaCard, target: Path) -> Path:
    """把卡写到指定路径（父目录自动创建）。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(card_to_dict(card), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def save_user_card(config_dir: Path | str, card: PersonaCard) -> Path:
    """存为用户卡（``<config_dir>/persona-cards/<id>.json``）。"""
    return export_card(card, user_dir(config_dir) / f"{card.id}{CARD_SUFFIX}")


def import_card(config_dir: Path | str, source_path: Path) -> PersonaCard | None:
    """导入一份外部卡（非法返回 ``None``；合法则落到用户卡目录）。"""
    card = load_card_file(Path(source_path))
    if card is None:
        return None
    save_user_card(config_dir, card)
    return card
