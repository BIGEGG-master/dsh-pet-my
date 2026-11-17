# -*- coding: utf-8 -*-
"""对话日记（pet/diary.py）：会话 → 按天日记、关键词搜索、导出文本。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from pet.diary import (
    available_days,
    build_entry,
    clear_cache,
    day_label,
    read_lines,
    render_day,
    search,
)


def _write_session(root, character, session_id, messages, *, updated_at=None):
    folder = root / "sessions" / character
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": session_id,
        "character_id": character,
        "provider_id": "p",
        "system_prompt": "sys",
        "created_at": messages[0]["created_at"] if messages else "",
        "updated_at": updated_at or "",
        "title": "",
        "pinned": False,
        "messages": messages,
    }
    path = folder / f"{session_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _utc(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).isoformat()


def test_read_lines_orders_and_skips_bad_entries(tmp_path):
    clear_cache()
    _write_session(
        tmp_path,
        "shenshen",
        "s1",
        [
            {"role": "user", "content": "第二句", "created_at": _utc(2026, 11, 12, 10, 0)},
            {"role": "assistant", "content": "回第二句", "created_at": _utc(2026, 11, 12, 10, 1)},
            {"role": "system", "content": "系统消息不该进日记", "created_at": _utc(2026, 11, 12, 10, 2)},
            {"role": "user", "content": "坏时间", "created_at": "not-a-time"},
            {"role": "user", "content": "", "created_at": _utc(2026, 11, 12, 10, 3)},
        ],
    )
    _write_session(
        tmp_path,
        "shenshen",
        "s2",
        [{"role": "user", "content": "早上那句", "created_at": _utc(2026, 11, 12, 1, 0)}],
    )
    lines = read_lines(tmp_path)
    assert [line.content for line in lines] == ["早上那句", "第二句", "回第二句"]
    assert all(line.ts.tzinfo is not None for line in lines)


def test_missing_and_corrupt_session_files_are_ignored(tmp_path):
    clear_cache()
    folder = tmp_path / "sessions" / "shenshen"
    folder.mkdir(parents=True)
    (folder / "bad.json").write_text("[]", encoding="utf-8")
    (folder / "worse.json").write_text("{oops", encoding="utf-8")
    assert read_lines(tmp_path) == []


def test_available_days_newest_first(tmp_path):
    clear_cache()
    _write_session(
        tmp_path,
        "shenshen",
        "a",
        [
            {"role": "user", "content": "昨天的", "created_at": _utc(2026, 11, 11, 10, 0)},
            {"role": "user", "content": "今天的", "created_at": _utc(2026, 11, 12, 10, 0)},
        ],
    )
    days = available_days(tmp_path)
    assert len(days) == 2
    assert days[0] > days[1]


def test_build_entry_uses_real_quotes_and_times(tmp_path):
    clear_cache()
    _write_session(
        tmp_path,
        "shenshen",
        "a",
        [
            {"role": "user", "content": "帮我看看鲸鱼照片", "created_at": _utc(2026, 11, 12, 1, 30)},
            {"role": "assistant", "content": "好嘟，我看看", "created_at": _utc(2026, 11, 12, 1, 31)},
            {"role": "user", "content": "晚安", "created_at": _utc(2026, 11, 12, 14, 0)},
            {"role": "assistant", "content": "晚安嘟", "created_at": _utc(2026, 11, 12, 14, 1)},
        ],
    )
    entry = build_entry(tmp_path, "2026-11-12")
    assert entry is not None
    assert entry.turns == 2
    assert "鲸鱼照片" in entry.text
    assert "晚安" in entry.text
    assert "明天也来吧" in entry.text
    # 引用必须是原文，且带了当天的时间锚点
    assert entry.first_at in entry.text and entry.last_at in entry.text
    assert "编出来" not in entry.text


def test_build_entry_returns_none_for_empty_day(tmp_path):
    clear_cache()
    assert build_entry(tmp_path, "2026-01-01") is None
    assert render_day(tmp_path, "2026-01-01") == ""


def test_search_matches_content_and_respects_range(tmp_path):
    clear_cache()
    _write_session(
        tmp_path,
        "shenshen",
        "a",
        [
            {"role": "user", "content": "我画了一只鲸鱼", "created_at": _utc(2026, 11, 11, 10, 0)},
            {"role": "user", "content": "今天画的是小猫", "created_at": _utc(2026, 11, 12, 10, 0)},
        ],
    )
    hits = search(tmp_path, "鲸鱼")
    assert len(hits) == 1
    assert hits[0].role == "哥哥"
    assert "鲸鱼" in hits[0].snippet
    assert search(tmp_path, "鲸鱼", since="2026-11-12") == []
    assert len(search(tmp_path, "画")) == 2
    assert search(tmp_path, "  ") == []


def test_day_label_format():
    assert day_label("2026-11-12") == "11 月 12 日 · 星期四"
    assert day_label("bad") == "bad"


def test_unknown_created_at_without_timezone_is_local(tmp_path):
    clear_cache()
    folder = tmp_path / "sessions" / "shenshen"
    folder.mkdir(parents=True)
    local = datetime.now().replace(microsecond=0, second=0, minute=30, hour=9)
    payload = {
        "session_id": "tz",
        "character_id": "shenshen",
        "messages": [
            {"role": "user", "content": "本地时间", "created_at": local.isoformat()},
        ],
    }
    (folder / "tz.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    lines = read_lines(tmp_path)
    assert len(lines) == 1
    assert lines[0].ts.strftime("%Y-%m-%d") == local.strftime("%Y-%m-%d")
