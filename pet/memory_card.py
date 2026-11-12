# -*- coding: utf-8 -*-
"""记忆卡：深层记忆（``memory.json``）的视图 + 照片附件。

**不是第二套存储**——这里没有自己的索引、没有自己的"要不要记住"的判断，也没有
另一份条目。一张卡 = ``sessions/<角色>/memory.json`` 里的一条记忆条目；有照片的
条目多一个 ``photo`` 字段，图片文件放在同目录的 ``memory-photos/`` 旁边。
删卡就是 ``ChatMemory.remove``，改层就是 ``ChatMemory.update_layer``——和记忆模块
本身是同一份数据、同一套规则（层、hits、归档、限额）。

为什么需要这一层：

- ``memory.json`` 是给模型注入的短条目，用户看不到；面板要按角色聚合、把层名 /
  命中次数 / 照片路径翻出来给人看；
- 照片不能留在会话的临时附件里（粘贴图发送后就被删），所以要复制到 memory 旁边，
  跟着条目一起生灭。

照片的"要不要记"由她自己判断（``pet/chat/photo_memory.py``）：判断通过就在记忆里
ADD 一条 ``layer=topic`` 的条目，再把暂存图挪进 ``memory-photos/``；判断不通过就
删掉暂存副本，记忆里什么都不留。
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .chat.memory import ChatMemory

log = logging.getLogger(__name__)

#: 照片后缀白名单（与聊天附件同口径：只认图片，别把任意文件塞进记忆目录）。
PHOTO_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
#: 单张照片上限（更大的图应该进相册，不该进记忆）。
MAX_PHOTO_BYTES = 20 * 1024 * 1024

#: 记忆层的展示名（与 ``memory_recall.LAYERS`` 同源；这里只做中文标签）。
LAYER_LABELS = {
    "user": "偏好",
    "fact": "事实",
    "lesson": "教训",
    "topic": "话题",
}


@dataclass(frozen=True)
class MemoryItem:
    """面板上的一张"卡"：一条真实记忆条目 + 它所在角色 + 照片路径。"""

    character_id: str
    entry: dict[str, Any]
    photo: Path | None = None

    @property
    def entry_id(self) -> str:
        return str(self.entry.get("id") or "")

    @property
    def text(self) -> str:
        return str(self.entry.get("text") or "")

    @property
    def layer(self) -> str:
        value = str(self.entry.get("layer") or "").strip().lower()
        return value if value in LAYER_LABELS else "fact"

    @property
    def layer_label(self) -> str:
        return LAYER_LABELS[self.layer]

    @property
    def hits(self) -> int:
        try:
            return int(self.entry.get("hits", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def feeling(self) -> str:
        """她对这条记忆的感受（第一人称一句话）；没有就是空串。

        这是条目自己的字段（提炼时一起写的），不是面板另算的文案——面板只负责
        显示；它不参与注入，所以不会挤占对话预算。
        """
        return " ".join(str(self.entry.get("feeling") or "").split())

    @property
    def created_at(self) -> str:
        return str(self.entry.get("created_at") or "")

    @property
    def archived(self) -> bool:
        return bool(self.entry.get("archived"))


def sessions_root(config_dir: Path | str) -> Path:
    return Path(config_dir) / "sessions"


def character_dirs(config_dir: Path | str) -> list[Path]:
    """有记忆文件的角色目录（按名字排序，输出确定）。"""
    root = sessions_root(config_dir)
    if not root.is_dir():
        return []
    try:
        return sorted(
            folder
            for folder in root.iterdir()
            if folder.is_dir() and (folder / "memory.json").is_file()
        )
    except OSError:
        return []


def photos_dir(config_dir: Path | str, character_id: str) -> Path:
    """照片与 memory.json 同目录：记忆条目在哪，图就在哪。"""
    return sessions_root(config_dir) / str(character_id) / "memory-photos"


def pending_dir(config_dir: Path | str, character_id: str) -> Path:
    """刚发来、还没被她判断的照片（判完即入记忆或删除）。"""
    return photos_dir(config_dir, character_id) / "pending"


def entry_photo_path(config_dir: Path | str, character_id: str, entry: dict[str, Any]) -> Path | None:
    """条目照片的绝对路径；没挂图或文件不在了返回 ``None``。"""
    name = os.path.basename(str(entry.get("photo") or ""))
    if not name:
        return None
    path = photos_dir(config_dir, character_id) / name
    return path if path.is_file() else None


def iter_items(config_dir: Path | str) -> list[MemoryItem]:
    """全部角色、全部记忆条目（最新在前）——面板的唯一数据源。

    直接读 ``ChatMemory.load()``：这里不缓存、不复制、不额外落盘，看到的就是
    模型注入时会看到的那一份（只是展示得更细）。
    """
    items: list[MemoryItem] = []
    for folder in character_dirs(config_dir):
        character_id = folder.name
        try:
            entries = ChatMemory(folder / "memory.json").load()
        except Exception:
            log.exception("记忆卡读取失败（%s），本次跳过该角色", folder)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            items.append(
                MemoryItem(
                    character_id=character_id,
                    entry=entry,
                    photo=entry_photo_path(config_dir, character_id, entry),
                )
            )
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items


def layer_counts(items: Iterable[MemoryItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.layer] = counts.get(item.layer, 0) + 1
    return counts


def filter_items(
    items: Iterable[MemoryItem],
    *,
    query: str = "",
    layer: str = "all",
) -> list[MemoryItem]:
    """按层 / 关键词过滤（关键词匹配正文，也匹配层名与日期）。"""
    needle = str(query or "").strip().lower()
    result: list[MemoryItem] = []
    for item in items:
        if layer in LAYER_LABELS and item.layer != layer:
            continue
        if needle:
            haystack = " ".join(
                (item.text, item.layer_label, item.created_at)
            ).lower()
            if needle not in haystack:
                continue
        result.append(item)
    return result


def delete_item(config_dir: Path | str, item: MemoryItem) -> bool:
    """删一条记忆：走 ``ChatMemory.remove``，再删它的照片文件。"""
    if not item.entry_id:
        return False
    memory = ChatMemory(sessions_root(config_dir) / item.character_id / "memory.json")
    if not memory.remove(item.entry_id):
        return False
    if item.photo is not None:
        try:
            item.photo.unlink()
        except OSError:
            log.debug("记忆照片删除失败（可能已不存在）：%s", item.photo)
    return True


# ---------------------------------------------------------------- 照片暂存


def stage_photo(
    config_dir: Path | str,
    character_id: str,
    source_path: Path | str,
) -> dict[str, Any] | None:
    """把刚发来的图复制进 ``memory-photos/pending/``，等她判断要不要记。

    先复制再判断：粘贴/截图进来的图在系统临时目录，聊天发送完就删；不先留一份，
    等她判断（一次模型请求）的时候图早就没了。
    """
    src = Path(source_path)
    suffix = src.suffix.lower()
    if not src.is_file() or suffix not in PHOTO_SUFFIXES:
        return None
    try:
        size = src.stat().st_size
    except OSError:
        return None
    if size <= 0 or size > MAX_PHOTO_BYTES:
        return None
    staged_id = uuid.uuid4().hex
    target = pending_dir(config_dir, character_id) / f"{staged_id}{suffix}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    except OSError:
        log.exception("记忆照片暂存失败：%s", src)
        return None
    return {"id": staged_id, "path": str(target)}


def discard_staged(
    config_dir: Path | str,
    character_id: str,
    staged: dict[str, Any] | None,
) -> bool:
    """她不打算记：删暂存副本（用户的原图仍然一个字节都不动）。"""
    if not staged:
        return False
    name = os.path.basename(str(staged.get("path") or ""))
    if not name:
        return False
    try:
        (pending_dir(config_dir, character_id) / name).unlink()
        return True
    except OSError:
        return False


def attach_staged(
    config_dir: Path | str,
    character_id: str,
    entry_id: str,
    staged: dict[str, Any] | None,
) -> bool:
    """把暂存图挂到某条记忆上：挪进 ``memory-photos/<entry_id><后缀>`` 并写回条目。

    失败**不抛**：调用点在回复后的后台线程里，记忆没挂上图不该影响对话。
    """
    if not staged or not entry_id:
        return False
    source = Path(str(staged.get("path") or ""))
    if not source.is_file():
        return False
    suffix = source.suffix.lower()
    if suffix not in PHOTO_SUFFIXES:
        discard_staged(config_dir, character_id, staged)
        return False
    target = photos_dir(config_dir, character_id) / f"{entry_id}{suffix}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
    except OSError:
        log.exception("记忆照片转存失败：%s -> %s", source, target)
        discard_staged(config_dir, character_id, staged)
        return False
    memory = ChatMemory(sessions_root(config_dir) / character_id / "memory.json")
    if memory.set_photo(entry_id, target.name):
        return True
    # 条目没写进去（并发删除 / 锁失败）：把图删掉，不留孤儿文件
    try:
        target.unlink()
    except OSError:
        pass
    return False


def guess_suffix(name: str, mime: str = "") -> str:
    """从文件名 / MIME 猜图片后缀（聊天附件链只给路径时兜底）。"""
    suffix = Path(name).suffix.lower()
    if suffix in PHOTO_SUFFIXES:
        return suffix
    guessed = mimetypes.guess_extension(mime) if mime else None
    return guessed if guessed in PHOTO_SUFFIXES else ".png"
