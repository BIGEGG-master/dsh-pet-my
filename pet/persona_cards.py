# -*- coding: utf-8 -*-
"""角色卡：一份可整体切换的**角色身份**（人设 + 显示名 + 事件台词）。

与「台词模板」(``persona_template``) 的分工：
- 台词模板只覆盖 ``dialogue_phrases``（一个事件一组文案），是**表达层**的补丁；
- 角色卡是**一个角色**的完整身份，应用时改三处：
  ``chat.default_system_prompt``（人设）、``character_aliases``（显示名）、
  ``dialogue_mode`` + ``dialogue_phrases``（口吻）。

**和设置页那栏 System Prompt 的关系**：它们是同一个字段。应用一张卡会把卡里的
人设写进 System Prompt，手改 System Prompt 则让当前配置不再等于那张卡——两条
入口写同一个键，这就是"看起来冲突"的来源。应用卡时会在顶层写下
``prompt_source``（``card:<id>`` / ``manual``），设置页据此提示当前人设来自哪里。

卡从两处加载（同 id 时用户卡优先）：
- 内置：``pet/persona_cards/builtin/*.json``（随包分发）
- 用户：``<config_dir>/persona-cards/``（设置页导入/导出）

**两种输入格式都认**：

1. ``persona-card/v1`` JSON（可带台词）::

       {
         "version": "persona-card/v1",
         "id": "feiyu",
         "name": "小肥鱼",
         "system_prompt": "你是「小肥鱼」……",
         "aliases": {"shenshen": "小肥鱼"},
         "phrases": {"activity.default": ["……", "……"]}
       }

2. **Markdown / 纯文本**（只提供人设，最省事的写法）::

       # 角色卡：嘟嘟

       ## 一、你是谁
       - 你叫嘟嘟……

   规则：第一个 ``# 标题`` 当显示名（去掉「角色卡：」这类前缀），其余正文整段
   作为 System Prompt；id 由正文哈希生成（同内容同 id，重复导入即覆盖），
   不带台词（应用时不动现有 ``dialogue_phrases``）。
   """

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping

log = logging.getLogger(__name__)

CARD_VERSION = "persona-card/v1"
CARD_SUFFIX = ".json"
#: 能读的卡文件后缀：JSON 是完整卡，md/txt 只当人设文档（设置页导入即转成 JSON）。
CARD_SUFFIXES = (".json", ".md", ".markdown", ".txt")
#: Markdown 人设正文上限：System Prompt 每轮都发，太长的文档会挤掉对话历史预算。
MAX_PROMPT_CHARS = 8000
#: 单条台词上限（与 config 的 dialogue_phrases 清洗口径一致）
MAX_PHRASE_CHARS = 120
#: 每个事件最多保留几条变体
MAX_PHRASES_PER_KEY = 8

_MD_TITLE = re.compile(r"^\s{0,3}#\s+(.+?)\s*$", re.MULTILINE)
_MD_TITLE_PREFIX = re.compile(r"^(?:角色卡|人设|角色|persona)\s*[:：]\s*", re.IGNORECASE)


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


def card_from_markdown(
    text: str,
    *,
    name: str = "",
    path: Path | None = None,
) -> PersonaCard | None:
    """Markdown / 纯文本 → 卡：``# 标题`` 当显示名，其余正文当人设。

    md 没有台词，所以 ``phrases`` 为空——应用时**不会动**现有事件台词，
    这是刻意的：人设文档不该顺手把口吻洗掉。
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return None
    title = ""
    match = _MD_TITLE.search(raw)
    body = raw
    if match is not None and match.start() <= 3:
        # 只认文首那个 H1；正文里的 ``## 分节`` 原样留在人设里。
        title = _MD_TITLE_PREFIX.sub("", match.group(1).strip()).strip()
        body = (raw[: match.start()] + raw[match.end():]).strip()
    prompt = body[:MAX_PROMPT_CHARS].strip()
    if not prompt:
        return None
    display = title or str(name or "").strip() or (path.stem if path else "")
    if not display:
        return None
    digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:10]
    return PersonaCard(
        id=f"md-{digest}",
        name=display[:40],
        system_prompt=prompt,
        phrases={},
        aliases={},
        source="markdown",
        path=path,
    )


def card_to_markdown(card: PersonaCard) -> str:
    """卡 → Markdown（人设文档形态，丢掉台词；导出给人看/再导入都行）。"""
    lines = [f"# {card.name}", "", str(card.system_prompt or "").strip()]
    return "\n".join(lines).strip() + "\n"


#: 补充段的分隔标题：模型能一眼看出"前面是角色，后面是用户追加的要求"。
SUPPLEMENT_HEADER = "【补充说明】"


def compose_prompt(base: str, supplement: str, *, merge: bool = True) -> str:
    """角色卡人设 + 用户补充 → 最终 System Prompt。

    为什么需要它：人设只有 ``chat.default_system_prompt`` 一个字段，而"应用角色卡"
    和"手写 System Prompt"两个入口都写它，于是互相覆盖。现在拆成两段：
    ``prompt_base``（卡/手写的主体）与 ``prompt_supplement``（手写补充），
    这个函数把两段合成一个字段——运行时读取方仍然只看 default_system_prompt，
    行为不变，只是不再二选一。

    ``merge=False`` 时只用主体（补充保留在配置里，随时可以再打开叠加）。
    """
    body = str(base or "").strip()
    extra = str(supplement or "").strip()
    if not merge or not extra:
        return body
    if not body:
        return extra
    return f"{body}\n\n{SUPPLEMENT_HEADER}\n{extra}"


def load_card_file(path: Path) -> PersonaCard | None:
    """读一份卡文件（``.json`` 或 ``.md`` / ``.txt``）；坏文件只记日志。"""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("角色卡读取失败: %s (%s)", path, exc)
        return None
    if suffix not in CARD_SUFFIXES:
        return None
    if suffix != ".json":
        return card_from_markdown(text, path=path)
    try:
        data = json.loads(text)
    except ValueError:
        # 后缀是 .json 但内容其实是 md（用户改后缀的常见情况）：尽力按 md 读一次。
        return card_from_markdown(text, path=path)
    return card_from_dict(data, source=str(path.parent.name), path=path)


def _load_dir(directory: Path, source: str) -> list[PersonaCard]:
    cards: list[PersonaCard] = []
    try:
        files = sorted(
            p
            for p in directory.iterdir()
            if p.is_file() and p.suffix.lower() in CARD_SUFFIXES
        )
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
    """导入一份外部卡（JSON 或 Markdown；非法返回 ``None``，合法则落到用户卡目录）。

    统一存成 ``.json``：md 只是输入形态（人设文档），落盘时转成完整卡格式，
    以后在设置页能直接编辑/导出；同 id 覆盖旧卡（md 的 id 由正文哈希决定，
    同一份文档重复导入只会刷新那一张）。
    """
    card = load_card_file(Path(source_path))
    if card is None:
        return None
    save_user_card(config_dir, card)
    return card


def prompt_source(config: Mapping[str, Any]) -> str:
    """当前人设来自哪里：``card:<id>`` / ``manual`` / ``""``（未记录，旧配置）。

    设置页用它说明"你现在这段 System Prompt 是不是某张卡写的"——两条入口写
    同一个字段，用户需要看见归属，才不会以为它们能各管一半。
    """
    return str(config.get("prompt_source") or "").strip()
