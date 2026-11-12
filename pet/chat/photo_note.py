# -*- coding: utf-8 -*-
"""给照片记忆卡补一句她自己的备注（静默、后台、可失败）。

为什么要有这个模块：用户把照片发给她时，记忆卡里先落的是**用户自己说的话**
（"这是我画的鲸鱼"）。用户要的是"她会给图片记忆备注成「哥哥画的鲸鱼」"——
也就是备注由**她**来写。于是发送完这一轮回复后，后台拿同一张图 + 这一轮对话
问一次模型，让她写一句 ≤16 字的备注，写回卡片。

硬性约束（与 ``memory_extract`` 同一套口径）：

- **静默**：无气泡、无通知、不延迟正常回复；失败只写日志；
- **不阻塞**：网络在后台线程，GUI 线程只做一次入队；
- **可失败**：模型不支持图片 / 网络失败 / 解析不出，都保留发送时那句备注——
  卡片仍然可用，只是备注不是她写的。

护栏（发请求之前）：chat 模块未激活不发、没有卡片不发、同一张卡 10 分钟内只写一次。
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import threading
import time
from pathlib import Path
from typing import Any

from .. import feature_activation as _fa
from .. import memory_card as cards_mod
from .memory_extract import _RESPONSE_CHAR_LIMIT, _complete

log = logging.getLogger(__name__)

#: 备注上限（与记忆卡列表一行放得下的长度一致；卡片层还会再截一次）。
NOTE_CHARS = 16
#: 同一张卡两次自动备注的最小间隔：用户重发同一张图不该再花一次钱。
_DEDUP_SECONDS = 600.0
_last_note: dict[str, float] = {}
_lock = threading.Lock()

_SYSTEM = (
    "你是嘟嘟，一只住在哥哥桌面上的小肥鱼桌宠。哥哥刚给你看了一张图。"
    "请用第一人称给这张图写一句备注，像你自己记在心里的小本子上写的那样。"
    "只输出这一句备注本身：不超过 16 个汉字，不加引号，不加句末标点，不作解释。"
)

_USER = (
    "【这张图的来历】\n{user_text}\n\n"
    "【我当时回他的话】\n{reply_text}\n\n"
    "请只输出一句备注。"
)


def _clean_note(raw: str) -> str:
    """模型输出 → 一句备注：去引号/换行/句末标点，超长截断。"""
    text = " ".join(str(raw or "").split())
    for pair in ('"', "'", "「", "」", "『", "』", "“", "”", "‘", "’"):
        text = text.replace(pair, "")
    text = text.strip("。.!！?？,，;；:： ")
    if len(text) > NOTE_CHARS:
        text = text[:NOTE_CHARS]
    return text


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


def schedule_photo_note(
    *,
    config_dir,
    cards: list[dict[str, Any]],
    user_text: str,
    reply_text: str,
    provider,
    provider_config,
) -> bool:
    """安排一次后台备注生成；返回有没有真的排上（护栏全在同步侧）。"""
    try:
        if not cards:
            return False
        if not _fa.is_active("chat"):
            return False
        if provider is None or provider_config is None:
            return False
        now = time.monotonic()
        pending: list[dict[str, Any]] = []
        with _lock:
            for card in cards:
                key = str(card.get("id") or "")
                if not key:
                    continue
                if now - _last_note.get(key, -1e18) < _DEDUP_SECONDS:
                    continue
                _last_note[key] = now
                pending.append(card)
        if not pending:
            return False
        thread = threading.Thread(
            target=_run_safely,
            args=(config_dir, pending, str(user_text or ""), str(reply_text or ""),
                  provider, provider_config),
            daemon=True,
            name="chat-photo-note",
        )
        thread.start()
        return True
    except Exception:
        log.exception("照片备注调度失败（已静默）")
        return False


def _run_safely(config_dir, cards, user_text, reply_text, provider, provider_config) -> None:
    try:
        _run(config_dir, cards, user_text, reply_text, provider, provider_config)
    except Exception:
        log.exception("照片备注生成失败（已静默）")


def _run(config_dir, cards, user_text, reply_text, provider, provider_config) -> None:
    for card in cards:
        path = cards_mod.photo_abs_path(config_dir, card)
        if path is None:
            continue
        payload = _image_payload(path)
        if payload is None:
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
        try:
            raw = _complete(provider, messages, provider_config)
        except Exception as exc:  # noqa: BLE001 - 后台异常只记日志，卡片保持原备注
            log.info("照片备注请求失败（保留原备注）：%s", exc)
            continue
        note = _clean_note(raw)
        if not note:
            continue
        if cards_mod.update_note(config_dir, str(card["id"]), note):
            log.info("照片记忆卡备注已更新：%s", note)


def reset_for_tests() -> None:
    """测试用：清掉限频状态。"""
    with _lock:
        _last_note.clear()


def _response_limit() -> int:
    """备注解析预算（比记忆提炼小得多；暴露出来便于测试断言）。"""
    return min(_RESPONSE_CHAR_LIMIT, 200)
