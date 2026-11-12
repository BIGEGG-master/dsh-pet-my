# -*- coding: utf-8 -*-
"""记忆卡：嘟嘟记住的文本与照片（右键「查看记忆卡」的数据层）。

和 ``pet/chat/memory.py`` 的分工（两者**不是**同一份存储）：

- 对话记忆（``memory.json``）是**给模型读的注入段**：条目短、按 hits 淘汰、
  总字符有硬预算，用户看不到全文；
- 记忆卡是**给人看的**：一条文字或一张照片 + 她自己写的一句备注，不参与注入、
  不自动过期，只在用户主动删除时消失。

存储（``<config_dir>/memory-cards/``）::

    index.json          卡片索引（原子替换写；坏文件改名保留后再重建）
    photos/<id>.png     照片副本（原图只读，用户自己的文件一个字节都不动）

卡片字段::

    {
      "id": "…",                 # 32 位 hex
      "kind": "text" | "photo",
      "text": "…",               # photo 卡可为空（有备注就够）
      "note": "哥哥画的鲸鱼",     # 她写的备注，列表里显示这一行
      "photo": "abc.png",        # 只存文件名，不存路径（配置目录可整体搬走）
      "created_at": "…",         # 本地时间 ISO 串
      "updated_at": "…",
      "source": "chat" | "manual" | "…"
    }

为什么把照片复制到配置目录而不是记账原路径：粘贴/截图进来的图在系统临时目录，
聊天发送完就删；用户自己的图也可能被移动或删除。记忆卡要"记得住"，就得自己留一份。
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

#: 索引版本：结构变化时递增，读到更高版本按"不认识"处理（保留原文件不覆盖）。
CARD_VERSION = 1
#: 卡片总数上限。记忆卡永不自动过期，所以只能在新增强制一个天花板：超限拒绝新增
#: 并如实告知（静默丢弃会让"我明明发过这张图"变成无法排查的鬼故事）。
MAX_CARDS = 500
#: 单条正文 / 备注上限（备注是列表里的一行，超长会撑坏布局）。
MAX_TEXT_CHARS = 2000
MAX_NOTE_CHARS = 80
#: 单张照片上限（与聊天附件同口径的 20MB：更大的图只该进相册，不该进记忆卡）。
MAX_PHOTO_BYTES = 20 * 1024 * 1024
PHOTO_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")

Index = dict[str, Any]

#: 读改写全程互斥：GUI 线程写、后台线程（照片备注）也写，原子替换只保证
#: "不会读到半截"，不保证"不会互相覆盖"，所以两者都要。
_write_lock = threading.Lock()


# ---------------------------------------------------------------- 路径


def cards_dir(config_dir: Path | str) -> Path:
    """记忆卡根目录（与 config.json 同级，便于整体备份/迁移）。"""
    return Path(config_dir) / "memory-cards"


def photos_dir(config_dir: Path | str) -> Path:
    return cards_dir(config_dir) / "photos"


def index_path(config_dir: Path | str) -> Path:
    return cards_dir(config_dir) / "index.json"


# ---------------------------------------------------------------- 读


def _empty_index() -> Index:
    return {"version": CARD_VERSION, "updated_at": "", "cards": []}


def _quarantine(path: Path) -> None:
    """坏索引改名保留：不覆盖证据，也不让一个坏文件把功能永久锁死。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        path.replace(path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}"))
        log.warning("记忆卡索引损坏，已改名保留：%s", path)
    except OSError:
        log.exception("记忆卡索引损坏且改名失败：%s", path)


def _clean_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _clean_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return ""
    return text


def _clean_card(raw: Any) -> dict[str, Any] | None:
    """单张卡片归一化：缺 id/kind 的条目直接丢弃（其余字段尽量保住）。"""
    if not isinstance(raw, dict):
        return None
    card_id = _clean_text(raw.get("id"), 40)
    kind = _clean_text(raw.get("kind"), 8)
    if not card_id or kind not in ("text", "photo"):
        return None
    card: dict[str, Any] = {
        "id": card_id,
        "kind": kind,
        "text": _clean_text(raw.get("text"), MAX_TEXT_CHARS),
        "note": _clean_text(raw.get("note"), MAX_NOTE_CHARS),
        "created_at": _clean_timestamp(raw.get("created_at")),
        "updated_at": _clean_timestamp(raw.get("updated_at")),
        "source": _clean_text(raw.get("source"), 40),
    }
    if kind == "photo":
        # 只认文件名：手改索引塞进来的路径一律剥掉，防止读到配置目录之外。
        name = os.path.basename(_clean_text(raw.get("photo"), 200))
        card["photo"] = name if name.lower().endswith(PHOTO_SUFFIXES) else ""
    else:
        card["photo"] = ""
    if not card["created_at"]:
        card["created_at"] = datetime.now().replace(microsecond=0).isoformat()
    if not card["updated_at"]:
        card["updated_at"] = card["created_at"]
    return card


def load_index(config_dir: Path | str) -> Index:
    """读索引；文件不存在 = 空索引，损坏 = 改名保留 + 空索引。"""
    path = index_path(config_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty_index()
    except OSError as exc:
        log.warning("记忆卡索引读取失败：%s（%s）", path, exc)
        return _empty_index()
    try:
        data = json.loads(raw)
    except ValueError:
        _quarantine(path)
        return _empty_index()
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        _quarantine(path)
        return _empty_index()
    version = data.get("version")
    if isinstance(version, int) and version > CARD_VERSION:
        # 更高版本写的索引：不认、不覆盖（降级时用户的卡还在，只是这次看不到）。
        log.warning("记忆卡索引版本 %s 高于本程序（%s），本次不读取", version, CARD_VERSION)
        return _empty_index()
    cards = [card for card in (_clean_card(item) for item in data["cards"]) if card]
    return {
        "version": CARD_VERSION,
        "updated_at": str(data.get("updated_at") or ""),
        "cards": cards,
    }


def load_cards(config_dir: Path | str) -> list[dict[str, Any]]:
    """全部卡片，最新在前。"""
    cards = load_index(config_dir)["cards"]
    return sorted(cards, key=lambda card: card.get("created_at") or "", reverse=True)


# ---------------------------------------------------------------- 写


def _atomic_write(path: Path, text: str) -> None:
    """原子替换：读者要么看到旧索引、要么看到新索引，不会读到半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _save_index(config_dir: Path | str, index: Index) -> bool:
    index["version"] = CARD_VERSION
    index["updated_at"] = datetime.now().replace(microsecond=0).isoformat()
    try:
        _atomic_write(
            index_path(config_dir),
            json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        )
        return True
    except OSError:
        log.exception("记忆卡索引写入失败：%s", index_path(config_dir))
        return False


def _new_card(kind: str, *, text: str, note: str, source: str) -> dict[str, Any]:
    now = datetime.now().replace(microsecond=0).isoformat()
    return {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "text": _clean_text(text, MAX_TEXT_CHARS),
        "note": _clean_text(note, MAX_NOTE_CHARS),
        "photo": "",
        "created_at": now,
        "updated_at": now,
        "source": _clean_text(source, 40),
    }


def add_text(
    config_dir: Path | str,
    text: str,
    note: str = "",
    *,
    source: str = "manual",
) -> dict[str, Any] | None:
    """存一条文字卡；空正文返回 ``None``（不写任何东西）。"""
    body = _clean_text(text, MAX_TEXT_CHARS)
    if not body:
        return None
    with _write_lock:
        index = load_index(config_dir)
        if len(index["cards"]) >= MAX_CARDS:
            log.warning("记忆卡已满（%d 张），拒绝新增文字卡", MAX_CARDS)
            return None
        card = _new_card("text", text=body, note=note, source=source)
        index["cards"].insert(0, card)
        if not _save_index(config_dir, index):
            return None
        return card


def add_photo(
    config_dir: Path | str,
    source_path: Path | str,
    note: str = "",
    text: str = "",
    *,
    source: str = "chat",
) -> dict[str, Any] | None:
    """存一张照片卡（复制进配置目录）；不是图片 / 超大小 / 已满都返回 ``None``。

    失败**不抛异常**：调用点在聊天发送路径上，记忆卡是锦上添花——图照常发出去，
    记不住只写日志，绝不打断这一次对话。
    """
    src = Path(source_path)
    suffix = src.suffix.lower()
    if not src.is_file() or suffix not in PHOTO_SUFFIXES:
        log.info("记忆卡跳过非图片或缺失文件：%s", src)
        return None
    try:
        size = src.stat().st_size
    except OSError:
        return None
    if size <= 0 or size > MAX_PHOTO_BYTES:
        log.info("记忆卡跳过超限图片：%s（%d 字节）", src, size)
        return None
    with _write_lock:
        index = load_index(config_dir)
        if len(index["cards"]) >= MAX_CARDS:
            log.warning("记忆卡已满（%d 张），拒绝新增照片", MAX_CARDS)
            return None
        card = _new_card("photo", text=text, note=note, source=source)
        name = f"{card['id']}{suffix}"
        target = photos_dir(config_dir) / name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
        except OSError:
            log.exception("记忆卡照片复制失败：%s", src)
            return None
        card["photo"] = name
        index["cards"].insert(0, card)
        if not _save_index(config_dir, index):
            # 索引没写成功就把刚复制的图删掉：不留孤儿文件。
            try:
                target.unlink()
            except OSError:
                pass
            return None
        return card


def update_note(config_dir: Path | str, card_id: str, note: str) -> bool:
    """改一行的备注；卡不存在返回 ``False``。"""
    target = _clean_text(note, MAX_NOTE_CHARS)
    with _write_lock:
        index = load_index(config_dir)
        for card in index["cards"]:
            if card["id"] != card_id:
                continue
            card["note"] = target
            card["updated_at"] = datetime.now().replace(microsecond=0).isoformat()
            return _save_index(config_dir, index)
        return False


def delete_card(config_dir: Path | str, card_id: str) -> bool:
    """删卡（照片连同副本一起删）；不存在返回 ``False``。"""
    with _write_lock:
        index = load_index(config_dir)
        kept = [card for card in index["cards"] if card["id"] != card_id]
        if len(kept) == len(index["cards"]):
            return False
        removed = [card for card in index["cards"] if card["id"] == card_id]
        index["cards"] = kept
        if not _save_index(config_dir, index):
            return False
        for card in removed:
            _unlink_photo(config_dir, card)
        return True


def _unlink_photo(config_dir: Path | str, card: dict[str, Any]) -> None:
    name = os.path.basename(str(card.get("photo") or ""))
    if not name:
        return
    try:
        (photos_dir(config_dir) / name).unlink()
    except OSError:
        log.debug("记忆卡照片删除失败（可能已不存在）：%s", name)


# ---------------------------------------------------------------- 查询


def photo_abs_path(config_dir: Path | str, card: dict[str, Any]) -> Path | None:
    """照片的绝对路径；副本不存在返回 ``None``（列表里显示占位而不是抛异常）。"""
    name = os.path.basename(str(card.get("photo") or ""))
    if not name:
        return None
    path = photos_dir(config_dir) / name
    return path if path.is_file() else None


def card_day(card: dict[str, Any]) -> str:
    """卡片创建日（``YYYY-MM-DD``，本地时间）；时间戳坏了返回空串。"""
    try:
        return datetime.fromisoformat(str(card.get("created_at") or "")).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def summary(card: dict[str, Any], limit: int = 120) -> str:
    """列表/搜索用的一行摘要：优先正文，其次备注。"""
    text = str(card.get("text") or "").strip() or str(card.get("note") or "").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def filter_cards(
    cards: Iterable[dict[str, Any]],
    *,
    query: str = "",
    kind: str = "all",
    day: str = "",
) -> list[dict[str, Any]]:
    """按类型 / 日期 / 关键词过滤（关键词同时匹配备注、正文与日期本身）。"""
    needle = str(query or "").strip().lower()
    result: list[dict[str, Any]] = []
    for card in cards:
        if kind in ("text", "photo") and card.get("kind") != kind:
            continue
        if day and card_day(card) != day:
            continue
        if needle:
            haystack = " ".join(
                str(card.get(key) or "") for key in ("note", "text", "created_at")
            ).lower()
            if needle not in haystack:
                continue
        result.append(card)
    return result


def stats(config_dir: Path | str) -> dict[str, int]:
    """总览：总数 / 文字数 / 照片数（面板副标题用，避免建了窗口才数一遍）。"""
    cards = load_cards(config_dir)
    photos = sum(1 for card in cards if card.get("kind") == "photo")
    return {"total": len(cards), "text": len(cards) - photos, "photo": photos}


def guess_suffix(name: str, mime: str = "") -> str:
    """从文件名/ MIME 猜图片后缀（聊天附件链只认路径，这里用于兜底）。"""
    suffix = Path(name).suffix.lower()
    if suffix in PHOTO_SUFFIXES:
        return suffix
    guessed = mimetypes.guess_extension(mime) if mime else None
    return guessed if guessed in PHOTO_SUFFIXES else ".png"
