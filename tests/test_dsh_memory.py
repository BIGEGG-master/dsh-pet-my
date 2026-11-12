# -*- coding: utf-8 -*-
"""DSH 插件记忆 → 本机桌宠记忆的转换与落盘（pet/chat/dsh_memory.py）。"""
from __future__ import annotations

import json

from pet.chat.dsh_memory import classify, read_user_turns, sync_into
from pet.chat.memory import ChatMemory


def _plugin_memory(records):
    return {"main": {"main": {"messages": records}}}


def test_classify_layers_and_noise():
    assert classify("我喜欢吃辣的，别给我推荐甜口的") == ("fact", "我喜欢吃辣的，别给我推荐甜口的")
    assert classify("记住：我对花生过敏") == ("fact", "我对花生过敏")
    assert classify("记住教训：下次别再用中文输出乱码了")[0] == "lesson"
    assert classify("帮我给桌宠加一个记忆桥")[0] == "topic"
    # 无信息量的不进记忆
    assert classify("你好") is None
    assert classify("1") is None
    assert classify("123") is None
    assert classify("   ") is None


def test_read_user_turns_ignores_assistant(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps(
            _plugin_memory(
                [
                    {"role": "user", "content": "我喜欢蓝色", "ts": 1},
                    {"role": "assistant", "content": "记住啦", "ts": 1},
                    {"role": "user", "content": [{"type": "text", "text": "我在杭州上班"}], "ts": 2},
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert read_user_turns(path) == ["我喜欢蓝色", "我在杭州上班"]


def test_read_user_turns_broken_file_is_empty(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_user_turns(path) == []
    assert read_user_turns(tmp_path / "missing.json") == []


def test_sync_into_writes_then_is_idempotent(tmp_path):
    plugin = tmp_path / "plugin-memory.json"
    plugin.write_text(
        json.dumps(
            _plugin_memory(
                [
                    {"role": "user", "content": "我喜欢吃辣的", "ts": 1},
                    {"role": "assistant", "content": "记住啦", "ts": 1},
                    {"role": "user", "content": "你好", "ts": 2},
                    {"role": "user", "content": "下次别再弄丢我的文件", "ts": 3},
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    memory = ChatMemory(tmp_path / "sessions" / "shenshen" / "memory.json")

    added = sync_into(memory, force=True, path=plugin)
    assert added == 2
    texts = {entry["text"] for entry in memory.load()}
    assert texts == {"我喜欢吃辣的", "下次别再弄丢我的文件"}
    layers = {entry["text"]: entry["layer"] for entry in memory.load()}
    assert layers["我喜欢吃辣的"] == "fact"
    assert layers["下次别再弄丢我的文件"] == "lesson"

    # 第二次同步不重复添加、也不刷新 hits
    before = {entry["text"]: entry["hits"] for entry in memory.load()}
    assert sync_into(memory, force=True, path=plugin) == 0
    after = {entry["text"]: entry["hits"] for entry in memory.load()}
    assert before == after


def test_sync_into_throttles_without_force(tmp_path):
    plugin = tmp_path / "plugin-memory.json"
    plugin.write_text(
        json.dumps(_plugin_memory([{"role": "user", "content": "我是做后端的", "ts": 1}]), ensure_ascii=False),
        encoding="utf-8",
    )
    memory = ChatMemory(tmp_path / "sessions" / "shenshen" / "memory.json")
    assert sync_into(memory, force=True, path=plugin) == 1
    # 立刻再调（不 force）应被 60s 节流挡住
    assert sync_into(memory, path=plugin) == 0
