# -*- coding: utf-8 -*-
"""照片记忆：她自己判断这张图该不该记住，并把"记住"这件事写进原记忆模块。

落点只有一个：``sessions/<角色>/memory.json``——和聊天里提炼出来的记忆是**同一份
数据、同一套规则**（层 / hits / 归档 / 限额 / 注入）。照片只是某条记忆的附件：
条目里多一个 ``photo`` 字段，文件在同目录的 ``memory-photos/`` 下，条目删了图跟着删。

判断由她做（严格 JSON，容错解析）::

    {"keep": true, "note": "哥哥画的鲸鱼"}

- ``keep=false``：随手截图 / 表情包 / 测试图 → 删掉暂存副本，记忆里什么都不留；
- ``keep=true``：在记忆里 ADD 一条 ``layer=topic`` 的条目（正文就是那句备注），
  再把暂存图挂到这条记忆上。

静默是硬要求（与 memory_extract 同口径）：无气泡、不打断回复；失败只写日志。
失败时**保守保留**：图是用户明确发来的，宁可多记一条，也不因为一次网络抖动
让"我明明发过"变成没发生过。
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import threading
import time
from pathlib import Path
from typing import Any

from .. import feature_activation as _fa
from .. import memory_card as cards_mod
from .memory import ChatMemory, _clean_feeling
from .memory_extract import _RESPONSE_CHAR_LIMIT, _complete

log = logging.getLogger(__name__)

#: 备注（也是这条记忆的正文）上限：记忆条目本来就短。
NOTE_CHARS = 40
#: 同一条暂存图 10 分钟内不重复判断（用户重发同一张图不重复花钱）。
_DEDUP_SECONDS = 600.0
#: 一轮最多判断几张图（成本护栏；超出的直接删暂存，不静默留一堆）。
MAX_PHOTOS_PER_TURN = 4

_SYSTEM = (
    "你是嘟嘟，一只住在哥哥桌面上的小肥鱼桌宠。哥哥刚给你看了一张图。\n"
    "请判断这张图值不值得记住，值得的话再写一句你会记在心里的备注。\n"
    "值得记：他的照片、他画/做的东西、他的作品、有纪念意义的场景、他特意给你看的。\n"
    "不值得记：随手截图、表情包、测试图、纯文字截图、与你们无关的图。\n"
    "只输出一个 JSON 对象，不要输出其它文字或代码围栏：\n"
    '{"keep": true 或 false, "note": "不超过 16 个汉字的备注", '
    '"feeling": "你对这张图的感受，第一人称一句话"}\n'
    "备注是第一人称、像你自己记的小本子（例：哥哥画的鲸鱼）。"
    "feeling 写你看到它时的心情（例：他居然真的画了，我有点想笑）。"
)

_USER = (
    "【他发图时说的话】\n{user_text}\n\n"
    "【我当时回他的话】\n{reply_text}\n\n"
    "只输出那个 JSON 对象。"
)

_last_seen: dict[str, float] = {}
_lock = threading.Lock()


def _image_payload(path: Path) -> dict[str, Any] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def _clean_note(raw: Any) -> str:
    """备注 → 一句短记忆：去引号/换行/句末标点，超长截断。"""
    text = " ".join(str(raw or "").split())
    for pair in ('"', "'", "「", "」", "“", "”", "『", "』"):
        text = text.replace(pair, "")
    text = text.strip("。.!！?？,，;；:： ")
    return text[:NOTE_CHARS]


def parse_verdict(raw: str) -> dict[str, Any] | None:
    """模型输出 → ``{"keep": bool, "note": str}``；解析不出返回 ``None``。"""
    text = str(raw or "").strip()[:_RESPONSE_CHAR_LIMIT]
    if not text:
        return None
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        keep = data.get("keep")
        if isinstance(keep, str):
            keep = keep.strip().lower() in ("true", "yes", "1", "是", "记")
        return {
            "keep": bool(keep),
            "note": _clean_note(data.get("note")),
            "feeling": _clean_feeling(data.get("feeling")),
        }
    return None


def fallback_note(user_text: str) -> str:
    """判断失败时的备注：用他自己那句话，实在没有就写一句中性的。"""
    text = _clean_note(user_text)
    return text or "哥哥给我看过一张图"


def schedule_photo_memory(
    *,
    config_dir,
    character_id: str,
    staged: list[dict[str, Any]],
    user_text: str,
    reply_text: str,
    provider,
    provider_config,
) -> bool:
    """安排一次后台判断；返回有没有真的排上（护栏全在同步侧）。"""
    try:
        items = [item for item in (staged or []) if isinstance(item, dict)][:MAX_PHOTOS_PER_TURN]
        if not items or not character_id:
            return False
        if not _fa.is_active("chat"):
            return False
        if provider is None or provider_config is None:
            return False
        pending: list[dict[str, Any]] = []
        with _lock:
            now = time.monotonic()
            for item in items:
                key = str(item.get("id") or "")
                if not key or now - _last_seen.get(key, -1e18) < _DEDUP_SECONDS:
                    continue
                _last_seen[key] = now
                pending.append(item)
        if not pending:
            return False
        thread = threading.Thread(
            target=_run_safely,
            args=(config_dir, str(character_id), pending, str(user_text or ""),
                  str(reply_text or ""), provider, provider_config),
            daemon=True,
            name="chat-photo-memory",
        )
        thread.start()
        return True
    except Exception:
        log.exception("照片记忆调度失败（已静默）")
        return False


def _run_safely(config_dir, character_id, staged, user_text, reply_text, provider, provider_config) -> None:
    try:
        _run(config_dir, character_id, staged, user_text, reply_text, provider, provider_config)
    except Exception:
        log.exception("照片记忆判断失败（已静默）")


def _run(config_dir, character_id, staged, user_text, reply_text, provider, provider_config) -> None:
    for item in staged:
        path = Path(str(item.get("path") or ""))
        payload = _image_payload(path)
        if payload is None:
            cards_mod.discard_staged(config_dir, character_id, item)
            continue
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": _USER.format(
                            user_text=(user_text or "（他没说话，只发了这张图）")[:800],
                            reply_text=(reply_text or "（还没回）")[:800],
                        ),
                    },
                    payload,
                ],
            },
        ]
        verdict = None
        try:
            verdict = parse_verdict(_complete(provider, messages, provider_config))
        except Exception as exc:  # noqa: BLE001 - 后台异常只记日志
            log.info("照片记忆判断请求失败（保守保留）：%s", exc)
        _apply_verdict(
            config_dir, character_id, item, verdict, user_text=user_text
        )


def _apply_verdict(
    config_dir,
    character_id: str,
    staged: dict[str, Any],
    verdict: dict[str, Any] | None,
    *,
    user_text: str,
) -> None:
    """按她的判断收尾：不留就删；留下就在原记忆模块里 ADD 一条并挂图。"""
    if verdict is not None and not verdict.get("keep"):
        cards_mod.discard_staged(config_dir, character_id, staged)
        log.debug("照片记忆：她判断不需要记住，已删除暂存副本")
        return
    note = (verdict or {}).get("note") or fallback_note(user_text)
    feeling = str((verdict or {}).get("feeling") or "").strip()
    memory = ChatMemory(
        cards_mod.sessions_root(config_dir) / character_id / "memory.json"
    )
    # 走自动通道（apply_ops），不借手动通道 add()：照片记忆是"她自己记的"，
    # 与聊天提炼出来的条目同一来源、同一去重/归档规则。
    op: dict[str, Any] = {"op": "ADD", "text": note, "layer": "topic"}
    if feeling:
        op["feeling"] = feeling
    memory.apply_ops([op], source="auto")
    entry = next(
        (
            change["entry"]
            for change in memory.last_changes
            if change.get("op") in ("ADD", "UPDATE")
        ),
        None,
    )
    if entry is None:
        entry = next((item for item in memory.load() if item.get("text") == note), None)
    if entry is None or not entry.get("id"):
        cards_mod.discard_staged(config_dir, character_id, staged)
        log.info("照片记忆：记忆条目没写进去，暂存副本已清理")
        return
    if not cards_mod.attach_staged(config_dir, character_id, str(entry["id"]), staged):
        log.info("照片记忆：图没挂上（条目 %s）", entry.get("id"))


def reset_for_tests() -> None:
    """测试用：清掉限频状态。"""
    with _lock:
        _last_seen.clear()
