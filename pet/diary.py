# -*- coding: utf-8 -*-
"""对话日记：把真实对话按天编成嘟嘟的日记（右键「嘟嘟的日记」的数据层）。

数据源是聊天会话文件 ``<config_dir>/sessions/<角色>/<会话>.json``
（``pet/chat/session_store.py`` 落盘的 ``ChatSession`` JSON）。**只读**：日记功能
绝不改会话文件，坏文件跳过并记日志。

为什么不用 ``memory.json``：对话记忆是给模型的注入段（短条目、会按 hits 淘汰），
日记要的是**当天说过的话**——原文与时间只存在会话文件里。

**不编造**：日记正文只由「真实消息 + 时间」拼出来，没有发生的事一个字都不写。
口吻是嘟嘟的第一人称，但内容是事实；这一点比"读起来更文学"优先。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: 单条引用上限：日记是回看用的，不是全文转储（点开对话会话窗口看原文）。
QUOTE_CHARS = 60
#: 每天最多引用几组「他说 / 我回」——再多就成了流水账。
MAX_QUOTES = 3
#: 搜索结果条数上限（面板一次别渲染几千行）。
MAX_HITS = 120
#: 搜索结果里片段两侧各留几个字。
SNIPPET_PAD = 14

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

#: 按 (路径, mtime, 大小) 缓存解析结果：日记窗口每次筛选都要重算，读盘只做一次。
_cache: dict[str, tuple[float, int, list["DiaryLine"]]] = {}


@dataclass(frozen=True)
class DiaryLine:
    """一条真实消息（已换算成本地时间）。"""

    ts: datetime
    role: str
    content: str


@dataclass(frozen=True)
class DiaryEntry:
    """一天的日记（正文已生成，可直接显示/导出）。"""

    day: str
    title: str
    text: str
    turns: int
    first_at: str
    last_at: str


@dataclass(frozen=True)
class DiaryHit:
    """跨天搜索的一条命中。"""

    day: str
    when: str
    role: str
    snippet: str


@dataclass(frozen=True)
class DaySummary:
    """某一天的概览（日期列表用：不生成正文就能显示"聊了几句"）。"""

    day: str
    label: str
    turns: int
    first_at: str
    last_at: str


def sessions_root(config_dir: Path | str) -> Path:
    return Path(config_dir) / "sessions"


# ---------------------------------------------------------------- 读会话


def _parse_ts(value: Any) -> datetime | None:
    """``created_at`` → 本地 aware datetime；解析不出返回 ``None``。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        # 旧文件可能没有时区（当年直接写本地时间）：按本地时间理解，不硬加 UTC，
        # 否则会把每条消息平移成 8 小时前的"昨天"。
        moment = moment.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return moment.astimezone()


def _messages_from_file(path: Path) -> list[DiaryLine]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.info("日记跳过无法读取的会话文件：%s（%s）", path, exc)
        return []
    if not isinstance(data, dict):
        return []
    messages = data.get("messages")
    if not isinstance(messages, list):
        return []
    lines: list[DiaryLine] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in ("user", "assistant"):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        moment = _parse_ts(item.get("created_at"))
        if moment is None:
            continue
        lines.append(DiaryLine(moment, role, content))
    return lines


def read_lines(config_dir: Path | str) -> list[DiaryLine]:
    """全部角色的真实消息，按时间升序（会话文件按 mtime 缓存）。"""
    root = sessions_root(config_dir)
    characters = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
    collected: list[DiaryLine] = []
    for folder in sorted(characters):
        try:
            files = sorted(p for p in folder.glob("*.json") if p.is_file())
        except OSError:
            continue
        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            key = str(path)
            cached = _cache.get(key)
            if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                collected.extend(cached[2])
                continue
            lines = _messages_from_file(path)
            _cache[key] = (stat.st_mtime, stat.st_size, lines)
            collected.extend(lines)
    collected.sort(key=lambda line: line.ts)
    return collected


def clear_cache() -> None:
    """测试用：丢掉会话解析缓存。"""
    _cache.clear()


def available_days(config_dir: Path | str) -> list[str]:
    """有对话的日子（``YYYY-MM-DD``），最新在前。"""
    days = {line.ts.strftime("%Y-%m-%d") for line in read_lines(config_dir)}
    return sorted(days, reverse=True)


# ---------------------------------------------------------------- 生成日记


def day_label(day: str) -> str:
    """``2026-11-12`` → ``11 月 12 日 · 星期三``（解析失败原样返回）。"""
    try:
        moment = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{moment.month} 月 {moment.day} 日 · {_WEEKDAYS[moment.weekday()]}"


def day_summaries(config_dir: Path | str) -> list[DaySummary]:
    """有对话的每一天的概览（最新在前）：日期列表一次拿全，不逐日生成正文。

    轮次口径与 :func:`build_entry` 一致（以用户消息为一轮的起点）。
    """
    grouped: dict[str, list[DiaryLine]] = {}
    for line in read_lines(config_dir):
        grouped.setdefault(line.ts.strftime("%Y-%m-%d"), []).append(line)
    summaries: list[DaySummary] = []
    for day in sorted(grouped, reverse=True):
        lines = grouped[day]
        turns = sum(1 for line in lines if line.role == "user") or 1
        summaries.append(
            DaySummary(
                day=day,
                label=day_label(day),
                turns=turns,
                first_at=lines[0].ts.strftime("%H:%M"),
                last_at=lines[-1].ts.strftime("%H:%M"),
            )
        )
    return summaries


def _clip(text: str, limit: int = QUOTE_CHARS) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _pick_quote_indexes(total: int) -> list[int]:
    """在 ``total`` 组对话里挑最多 ``MAX_QUOTES`` 组：开头、中间、结尾各一组。

    挑位置而不是"前 3 组"：一天的对话，最先说的和最后说的信息量最大，中间取一组
    让时间跨度看得出来。
    """
    if total <= 0:
        return []
    if total <= MAX_QUOTES:
        return list(range(total))
    middle = total // 2
    return sorted({0, middle, total - 1})[:MAX_QUOTES]


def _greeting_for(moment: datetime) -> str:
    hour = moment.hour
    if hour < 6:
        return "半夜"
    if hour < 11:
        return "早上"
    if hour < 14:
        return "中午"
    if hour < 18:
        return "下午"
    return "晚上"


def build_entry(
    config_dir: Path | str,
    day: str,
    *,
    name: str = "嘟嘟",
    owner: str = "哥哥",
) -> DiaryEntry | None:
    """生成某一天的日记；那天没有对话返回 ``None``。

    正文全是事实拼装：当天几次、起止时间、按时间引用的原话、共几句。
    最后一句固定是她的语气（"明天也来吧"），不引入任何未发生的内容。
    """
    lines = [line for line in read_lines(config_dir) if line.ts.strftime("%Y-%m-%d") == day]
    if not lines:
        return None
    pairs: list[tuple[DiaryLine, DiaryLine | None]] = []
    pending: DiaryLine | None = None
    for line in lines:
        if line.role == "user":
            if pending is not None:
                pairs.append((pending, None))
            pending = line
        elif pending is not None:
            pairs.append((pending, line))
            pending = None
    if pending is not None:
        pairs.append((pending, None))

    first, last = lines[0].ts, lines[-1].ts
    turns = len(pairs) or len(lines)
    span_hours = (last - first).total_seconds() / 3600.0
    wanted = _pick_quote_indexes(len(pairs))

    chunks: list[str] = [day_label(day), ""]
    if turns == 1:
        chunks.append(f"{_greeting_for(first)} {first:%H:%M}，{owner}来找过一次，就聊了几句嘟。")
    else:
        chunks.append(
            f"今天{owner}来找我 {turns} 次，从 {first:%H:%M} 一直到 {last:%H:%M}。"
        )
    if span_hours >= 4 and turns > 1:
        chunks.append("中间隔了好几个钟头，我还以为今天他不来了嘟。")
    chunks.append("")

    for index in wanted:
        asked, replied = pairs[index]
        when = asked.ts.strftime("%H:%M")
        quote = _clip(asked.content)
        chunks.append(f"{when}　{owner}说：「{quote}」。")
        if replied is not None:
            chunks.append(f"　　　我回他：「{_clip(replied.content)}」。")
        chunks.append("")

    if turns > 1:
        chunks.append(f"这一天我们来回说了 {len(lines)} 句。")
    chunks.append(f"明天也来吧，{name}在这儿呢。")
    text = "\n".join(chunks).strip() + "\n"
    return DiaryEntry(
        day=day,
        title=day_label(day),
        text=text,
        turns=turns,
        first_at=first.strftime("%H:%M"),
        last_at=last.strftime("%H:%M"),
    )


def render_day(config_dir: Path | str, day: str, **kwargs: Any) -> str:
    """一天的日记纯文本（导出/剪贴板用）；没有对话返回空串。"""
    entry = build_entry(config_dir, day, **kwargs)
    return entry.text if entry is not None else ""


# ---------------------------------------------------------------- 搜索


def _snippet(content: str, needle: str) -> str:
    flat = " ".join(str(content or "").split())
    position = flat.lower().find(needle)
    if position < 0:
        return _clip(flat, max(QUOTE_CHARS, SNIPPET_PAD * 2))
    start = max(0, position - SNIPPET_PAD)
    end = min(len(flat), position + len(needle) + SNIPPET_PAD)
    head = "…" if start > 0 else ""
    tail = "…" if end < len(flat) else ""
    return f"{head}{flat[start:end]}{tail}"


def search(
    config_dir: Path | str,
    query: str,
    *,
    since: str = "",
    until: str = "",
    limit: int = MAX_HITS,
) -> list[DiaryHit]:
    """在全部对话里按关键词找，返回按时间倒序的命中（可按日期区间收窄）。

    ``since`` / ``until`` 是 ``YYYY-MM-DD``（含边界）；空串表示不限。
    """
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    hits: list[DiaryHit] = []
    for line in reversed(read_lines(config_dir)):
        day = line.ts.strftime("%Y-%m-%d")
        if since and day < since:
            continue
        if until and day > until:
            continue
        if needle not in line.content.lower():
            continue
        hits.append(
            DiaryHit(
                day=day,
                when=line.ts.strftime("%m-%d %H:%M"),
                role="我" if line.role == "assistant" else "哥哥",
                snippet=_snippet(line.content, needle),
            )
        )
        if len(hits) >= limit:
            break
    return hits


def matches_day(query: str, day: str) -> bool:
    """关键词是否命中某一天（日期本身或日记正文里出现）。"""
    needle = str(query or "").strip().lower()
    if not needle:
        return True
    return needle in day or needle in day_label(day).lower()
