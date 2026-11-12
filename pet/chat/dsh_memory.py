# -*- coding: utf-8 -*-
"""DSH 桌宠插件（dsh-pet）的对话记忆 → 本机桌宠的全局记忆。

数据源：``~/.dsh/dsh-pet/memory.json``（插件版结构 ``{桶: {宠物: {messages: [...]}}}``，
与本机桌宠的 ``sessions/<角色>/memory.json`` 是**两份不同格式**的文件）。

本模块只做「读 → 分类 → 交给 ``ChatMemory.apply_ops``」，不碰注入/渲染路径：
写进来的条目与手动「记住：…」的条目在下游完全等价（同一份文件、同样四层、同样召回）。

纪律：
- 读失败/解析失败 → 记日志并返回 0，**一个字节都不写**；
- 只取 ``role == "user"``：助手回复是桌宠自己说的话，不是「关于主人的记忆」；
- 寒暄、纯数字、过短不导入（DSH 里大量「你好」「1」会把记忆冲成噪声）；
- 已存在的文本不再产生 ADD——否则每 60 秒同步一次就把 hits 刷一遍、把 topic 的
  14 天归档时钟搅乱；
- 节流在模块级：多窗、多入口共用一份 ``_last_sync_at``，同一拍只同步一次。

为什么不复用 ``integrations/dsh-pet-memory-bridge``：那是随包分发的独立脚本
（给「不重新打包也能用」的场景），不能反向 import 进 pet 包；两边的分类口径在
``tests/test_dsh_memory.py`` 里对齐。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from .memory import MAX_ENTRY_CHARS, ChatMemory
from .memory_recall import extract_keywords

log = logging.getLogger(__name__)

#: 两次自动同步的最小间隔（秒）。
SYNC_INTERVAL_SECONDS = 60.0

_sync_lock = threading.Lock()
_last_sync_at = 0.0


def dsh_memory_path() -> Path:
    """DSH 插件的记忆文件路径（``DSH_HOME`` 可覆盖，与桌面端同一套规则）。"""
    home = os.environ.get("DSH_HOME", "").strip()
    root = Path(home) if home else Path.home() / ".dsh"
    return root / "dsh-pet" / "memory.json"


# 「记住偏好：…」「记住教训：…」这类显式层提示
_LAYER_HINT = re.compile(r"^(偏好|偏好类|教训|话题)\s*[：:]\s*")
_REMEMBER = re.compile(r"^(?:请)?(?:帮我)?(?:记住|记一下|记下|记着|别忘了|别忘记|记得)\s*[：:，,]?\s*")

#: 单条即等于没有说话内容的词（比对前会先去掉标点与空白、英文转小写）
_SMALL_TALK = frozenset({
    "你好", "您好", "在吗", "在不在", "嗨", "哈喽", "hello", "hi", "嗯", "哦", "噢",
    "好的", "好", "行", "可以", "谢谢", "谢了", "再见", "晚安", "早安", "早", "午安",
    "没事", "随便", "不知道", "算了", "ok", "okay", "收到", "了解", "明白", "在么", "在嘛",
})

_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:~`\"'“”‘’（）()\[\]{}<>《》…—\-]+")

_FACT_HINTS = (
    "我喜欢", "我不喜欢", "我爱", "我不爱", "我讨厌", "我受不了", "我是", "我在", "我的",
    "我叫", "我住", "我养", "我玩", "我学", "我做", "我吃", "我怕", "我会", "我想", "我要",
    "习惯", "偏好", "过敏", "生日", "家住", "工作", "职业",
)
_LESSON_HINTS = (
    "下次", "以后", "之后", "别再", "不要再", "不要这样", "说错了", "搞错了", "弄错了",
    "不是这样", "记住教训", "以后不要", "下次别",
)
_TASK_HINTS = (
    "帮我", "帮我做", "做一个", "实现", "修一下", "修复", "改一下", "改成", "添加", "加一个",
    "写一个", "写个", "检查", "排查", "部署", "安装", "重构", "优化", "整理", "生成",
    "项目", "代码", "文件", "脚本", "插件", "桌宠", "记忆",
)


def _message_text(message: dict[str, Any]) -> str:
    """取消息正文（兼容 str 与多模态 content 列表）。"""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def read_user_turns(path: Path | None = None) -> list[str]:
    """读插件记忆里全部真人消息正文（按文件内出现顺序）。

    任何读/解析失败都返回空列表并记日志——调用方据此「什么都不做」。
    """
    target = path or dsh_memory_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        log.warning("DSH 记忆读取失败（本次不同步）: %s (%s)", target, exc)
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        log.warning("DSH 记忆解析失败（本次不同步）: %s (%s)", target, exc)
        return []
    if not isinstance(data, dict):
        log.warning("DSH 记忆结构异常（根不是对象），本次不同步: %s", target)
        return []
    texts: list[str] = []
    for bucket in data.values():
        if not isinstance(bucket, dict):
            continue
        for leaf in bucket.values():
            if not isinstance(leaf, dict):
                continue
            messages = leaf.get("messages")
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                text = _message_text(message)
                if text:
                    texts.append(text)
    return texts


def _normalized(text: str) -> str:
    return _PUNCT.sub("", text).lower()


def classify(text: str) -> tuple[str, str] | None:
    """把一条用户消息判成 ``(层, 正文)``；没有记忆价值返回 ``None``。"""
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    if not body:
        return None
    hinted_layer = ""
    hinted = _LAYER_HINT.match(body)
    if hinted:
        hinted_layer = {"偏好": "fact", "偏好类": "fact", "教训": "lesson", "话题": "topic"}.get(
            hinted.group(1), ""
        )
        body = body[hinted.end():].strip()
    remember = _REMEMBER.match(body)
    if remember:
        body = body[remember.end():].strip()
    body = body.strip(" 　:：-—")
    if not body:
        return None
    key = _normalized(body)
    if not key or key in _SMALL_TALK or key.isdigit() or len(set(key)) == 1:
        return None
    if len(key) < 4:
        return None
    text = body[:MAX_ENTRY_CHARS]
    if any(hint in text for hint in _LESSON_HINTS):
        return "lesson", text
    if hinted_layer:
        return hinted_layer, text
    if remember:
        return "fact", text
    if any(hint in text for hint in _FACT_HINTS):
        return "fact", text
    if len(key) >= 6 and any(hint in text for hint in _TASK_HINTS):
        return "topic", text
    return None


def sync_into(
    memory: ChatMemory,
    *,
    force: bool = False,
    interval: float | None = None,
    path: Path | None = None,
) -> int:
    """把 DSH 里新增的真人消息并进 ``memory``，返回本次落盘的条目数。

    节流：默认 ``SYNC_INTERVAL_SECONDS`` 内只跑一次（``force=True`` 跳过）。
    读失败、没有新内容、拿不到跨进程锁都返回 0，且盘上一个字节都没动。
    """
    global _last_sync_at
    window = SYNC_INTERVAL_SECONDS if interval is None else max(0.0, float(interval))
    with _sync_lock:
        now = time.monotonic()
        if not force and _last_sync_at and now - _last_sync_at < window:
            return 0
        _last_sync_at = now
        texts = read_user_turns(path)
        if not texts:
            return 0
        try:
            existing = {str(entry.get("text") or "").strip() for entry in memory.load()}
        except Exception:
            existing = set()
        ops: list[dict[str, Any]] = []
        seen: set[str] = set()
        for text in texts:
            decided = classify(text)
            if decided is None:
                continue
            layer, body = decided
            if body in existing or body in seen:
                continue
            seen.add(body)
            ops.append({"op": "ADD", "text": body, "layer": layer, "keywords": extract_keywords(body)})
        if not ops:
            return 0
        if not memory.apply_ops(ops, source="auto"):
            return 0
        log.info("DSH 记忆同步：新增 %d 条（来源 %s）", len(ops), path or dsh_memory_path())
        return len(ops)


def reset_throttle() -> None:
    """清掉节流时间戳（测试与「用户手动点同步」用）。"""
    global _last_sync_at
    with _sync_lock:
        _last_sync_at = 0.0
