"""DSH ⇄ 桌宠 记忆桥（Memory Bridge）。

把 DSH 桌宠插件 ``dsh-pet`` 的对话记忆（``~/.dsh/dsh-pet/memory.json``，原始问答轮次）
并入独立版桌宠的记忆引擎（``<config_dir>/sessions/<character>/memory.json``，四层条目），
并把桌宠侧沉淀的记忆反向导出成 DSH 可读的文本，让两边互相"记得"。

独立版桌宠的记忆文件结构（``pet/chat/memory.py``，本文件按它一比一写入）：

    {
      "version": 1,
      "entries": [
        {
          "id": "uuid4 hex",
          "text": "我不吃辣",
          "source": "manual" | "auto",
          "layer": "user" | "fact" | "lesson" | "topic",
          "keywords": ["不吃辣", "吃辣"],
          "created_at": "<isoformat>",
          "updated_at": "<isoformat>",
          "hits": 0,
          # 可选： "archived": false, "last_hit_at": "<isoformat>", "protected": false
        }
      ]
    }

设计约束（与桌宠自身同款纪律）：
- **读失败绝不写盘**：任何异常都只记日志，盘上一个字节都不动。
- **原子替换**：同目录临时文件 + fsync + ``os.replace``。
- **跨进程互斥**：``memory.json.bridge-lock``（O_CREAT|O_EXCL + 超时 + 陈旧锁回收），
  不与桌宠自己的 QLockFile 抢同一个文件名。
- **纯标准库**：零第三方依赖，能被桌宠进程内的 island provider 直接 import。

CLI::

    python memory_bridge.py status      # 打印诊断
    python memory_bridge.py sync        # 增量同步一次
    python memory_bridge.py sync --full # 重新全量导入（忽略游标）
    python memory_bridge.py export      # 只做反向导出
    python memory_bridge.py watch       # 前台常驻轮询
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

APP_NAME = "dsh-pet-standalone-webm-chat"
APP_NAME_LEGACY = "dsh-pet-standalone"

PET_MEMORY_VERSION = 1
MAX_ENTRIES = 100
MAX_TOTAL_CHARS = 4000
MAX_ENTRY_CHARS = 500

STATE_FILE = ".memory-bridge-state.json"
LOG_FILE = "memory-bridge.log"
LOCK_SUFFIX = ".bridge-lock"

# 这些层有"恒注入 / 高价值"语义，裁剪时最后才动它们
KEEP_FIRST_LAYERS = ("user", "lesson", "fact")

DEFAULT_INTERVAL = 60.0


# ---------------------------------------------------------------- 路径定位


def _appdata() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Roaming"


def candidate_config_dirs() -> list[Path]:
    """桌宠配置目录的候选（按可信度排序，第一个存在的胜出）。"""
    explicit = os.environ.get("DSH_PET_CONFIG_DIR", "").strip()
    if explicit:
        return [Path(explicit)]
    base = _appdata()
    out = [base / APP_NAME]
    out.extend(sorted(p for p in base.glob(f"{APP_NAME}*") if p.is_dir() and p not in out))
    out.append(base / APP_NAME_LEGACY)
    return out


def resolve_config_dir() -> Path:
    dirs = candidate_config_dirs()
    for d in dirs:
        if (d / "config.json").is_file():
            return d
    # 一个都不存在也返回首选路径：调用方据此给出可读的错误
    return dirs[0]


def resolve_characters(config_dir: Path) -> list[str]:
    """当前在册的角色 id（slot 档案里的 ``character``），去重保序。"""
    names: list[str] = []
    for slot in sorted(config_dir.glob("config-slot-*.json")):
        data = _load_json(slot, {})
        name = str(data.get("character") or "").strip() if isinstance(data, dict) else ""
        if name and name not in names:
            names.append(name)
    if not names:
        data = _load_json(config_dir / "config.json", {})
        # 老配置没有 slot 时，默认角色与内置素材同名
        names = ["shenshen"] if not data else ["shenshen"]
    return names


def pet_memory_paths(config_dir: Path) -> list[tuple[str, Path]]:
    """[(character, memory.json)]：``sessions/``（slot-0）与 ``sessions-<实例>/`` 都算。"""
    out: list[tuple[str, Path]] = []
    roots = [config_dir / "sessions"]
    roots.extend(sorted(p for p in config_dir.glob("sessions-*") if p.is_dir()))
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir():
                out.append((child.name, child / "memory.json"))
    return out


def plugin_memory_path() -> Path:
    home = os.environ.get("DSH_HOME", "").strip()
    root = Path(home) if home else Path.home() / ".dsh"
    return root / "dsh-pet" / "memory.json"


def export_dir() -> Path:
    home = os.environ.get("DSH_HOME", "").strip()
    root = Path(home) if home else Path.home() / ".dsh"
    return root / "dsh-pet" / "memory-bridge"


# ---------------------------------------------------------------- 基础 IO


def _load_json(path: Path, default: Any) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def log_line(config_dir: Path, message: str) -> None:
    try:
        with (config_dir / LOG_FILE).open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


@contextmanager
def file_lock(lock_path: Path, timeout: float = 5.0, stale_after: float = 60.0) -> Iterator[None]:
    """跨进程互斥：O_CREAT|O_EXCL + 超时 + 陈旧锁回收（不依赖 msvcrt/posix 差异）。"""
    deadline = time.monotonic() + timeout
    acquired = False
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > stale_after:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    try:
        yield
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------- 文本处理

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:~`\"'“”‘’（）()\[\]{}<>《》…—-]+")

# 纯寒暄/填充词：单条就等于没有信息量
_SMALL_TALK = {
    "你好", "您好", "在吗", "在不在", "嗨", "哈喽", "hello", "hi", "嗯", "哦", "噢",
    "好的", "好", "行", "可以", "谢谢", "谢了", "再见", "晚安", "早安", "早", "午安",
    "没事", "随便", "不知道", "算了", "ok", "okay", "收到", "了解", "明白", "1", "11",
    "测试", "test", "在么", "在嘛", "喂",
}

_REMEMBER = re.compile(r"^(?:请)?(?:帮我)?(?:记住|记一下|记下|记着|别忘了|别忘记|记得)\s*[：:，,]?\s*")
_LAYER_HINT = re.compile(r"^(?:偏好|偏好类|教训|话题)\s*[：:]\s*")

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
    "写一个", "写个", "检查", "排查", "部署", "安装", "重构", "优化", "整理", "生成", "看看这个",
    "项目", "代码", "文件", "脚本", "插件", "桌宠", "记忆",
)


def normalize_text(text: str) -> str:
    """去重用的归一化键：去空白与标点、英文小写。"""
    return _PUNCT.sub("", _WS.sub("", str(text or ""))).lower()


def _is_small_talk(text: str) -> bool:
    key = normalize_text(text)
    if not key or len(key) < 2:
        return True
    if key in _SMALL_TALK:
        return True
    # 纯数字 / 单字符重复（"111" "aaaa"）
    if key.isdigit() or len(set(key)) == 1:
        return True
    return False


def extract_keywords(text: str, limit: int = 12) -> list[str]:
    """与桌宠 memory_recall 同口径的粗粒度关键词：中文 bigram + 英文/数字词。"""
    raw = str(text or "")
    words: list[str] = []
    words.extend(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{1,23}", raw))
    words.extend(re.findall(r"\d{2,}", raw))
    han = re.findall(r"[\u4e00-\u9fff]+", raw)
    stop = {"我们", "你们", "他们", "这个", "那个", "什么", "怎么", "可以", "一个", "现在", "就是", "因为", "所以"}
    for chunk in han:
        if len(chunk) == 1:
            words.append(chunk)
            continue
        for i in range(len(chunk) - 1):
            pair = chunk[i : i + 2]
            if pair not in stop:
                words.append(pair)
    seen: list[str] = []
    for word in words:
        if word and word not in seen:
            seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def _now_iso() -> str:
    return datetime.now().isoformat()


def _ts_to_iso(ts: float) -> str:
    """插件写的是 JS ``Date.now()`` 毫秒；也兼容秒级时间戳与 0。"""
    if not ts:
        return _now_iso()
    value = float(ts)
    if value > 1e11:  # 毫秒
        value /= 1000.0
    try:
        return datetime.fromtimestamp(value).isoformat()
    except (OSError, OverflowError, ValueError):
        return _now_iso()


def _text_of(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


# ---------------------------------------------------------------- 记忆读写


def read_pet_memory(path: Path) -> dict[str, Any] | None:
    """严格读：文件不存在 → 空结构；解析失败 → None（调用方据此放弃写入）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": PET_MEMORY_VERSION, "entries": []}
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        data["entries"] = []
    data.setdefault("version", PET_MEMORY_VERSION)
    return data


def _clean_entry(entry: Any) -> dict[str, Any] | None:
    """把任意来源的条目归一成桌宠能读的最小字段，坏条目丢弃。"""
    if not isinstance(entry, dict):
        return None
    text = str(entry.get("text") or "").strip()
    if not text:
        return None
    now = _now_iso()
    layer = str(entry.get("layer") or "fact").strip().lower()
    if layer not in ("user", "fact", "lesson", "topic"):
        layer = "fact"
    keywords = entry.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        keywords = extract_keywords(text)
    out: dict[str, Any] = {
        "id": str(entry.get("id") or uuid.uuid4().hex),
        "text": text[:MAX_ENTRY_CHARS],
        "source": "manual" if str(entry.get("source") or "") == "manual" else "auto",
        "layer": layer,
        "keywords": [str(k) for k in keywords if str(k).strip()][:24],
        "created_at": str(entry.get("created_at") or now),
        "updated_at": str(entry.get("updated_at") or now),
        "hits": int(entry.get("hits") or 0),
    }
    if str(entry.get("origin") or "") == "dsh-pet":
        out["origin"] = "dsh-pet"
        if entry.get("dsh_pet"):
            out["dsh_pet"] = str(entry["dsh_pet"])
        if entry.get("dsh_bucket"):
            out["dsh_bucket"] = str(entry["dsh_bucket"])
    if layer == "topic" and isinstance(entry.get("archived"), bool):
        out["archived"] = entry["archived"]
    if isinstance(entry.get("last_hit_at"), str):
        out["last_hit_at"] = entry["last_hit_at"]
    if entry.get("protected") is True:
        out["protected"] = True
    return out


def _iso_to_epoch(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return 0.0


def _enforce_limits(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """与桌宠 _enforce_limits 同口径的保守裁剪：限制条数与总字数，优先保高价值层。"""

    def key(entry: dict[str, Any]) -> tuple[int, float]:
        layer = str(entry.get("layer") or "fact")
        priority = 0 if layer in KEEP_FIRST_LAYERS else 1
        return (priority, -_iso_to_epoch(str(entry.get("updated_at") or "")))

    ordered = sorted(entries, key=key)
    kept: list[dict[str, Any]] = []
    total = 0
    for entry in ordered:
        text_len = len(str(entry.get("text") or ""))
        if len(kept) >= MAX_ENTRIES or total + text_len > MAX_TOTAL_CHARS:
            continue
        kept.append(entry)
        total += text_len
    return kept


def write_pet_memory(path: Path, data: dict[str, Any]) -> None:
    payload = {"version": PET_MEMORY_VERSION, "entries": data.get("entries") or []}
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- DSH 侧读取


def read_plugin_turns(path: Path) -> list[dict[str, Any]]:
    """读 ``dsh-pet`` 的 memory.json，摊平成 (会话, 宠物, 轮次) 列表。

    插件结构是双层桶 ``{<种类>: {<宠物 id>: {messages: [...]}}}``；多实例/多宠物都在里面。
    只取 ``role == user`` 的正文——助手回复是桌宠自己说的话，不需要当成"关于主人的记忆"。
    """
    data = _load_json(path, {})
    if not isinstance(data, dict):
        return []
    turns: list[dict[str, Any]] = []
    for bucket_name, bucket in data.items():
        if not isinstance(bucket, dict):
            continue
        for pet_id, leaf in bucket.items():
            if not isinstance(leaf, dict):
                continue
            messages = leaf.get("messages")
            if not isinstance(messages, list):
                continue
            for index, message in enumerate(messages):
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                text = _text_of(message)
                if not text:
                    continue
                turns.append(
                    {
                        "bucket": str(bucket_name),
                        "pet": str(pet_id),
                        "index": index,
                        "text": text,
                        "ts": float(message.get("ts") or 0.0),
                    }
                )
    turns.sort(key=lambda t: (t["ts"], t["bucket"], t["pet"], t["index"]))
    return turns


def classify_turn(text: str) -> tuple[str, str] | None:
    """把一条主人消息判成 (层, 正文)；没有记忆价值返回 None。"""
    body = _WS.sub(" ", str(text or "")).strip()
    if not body:
        return None
    # 「记住偏好：…」「记住教训：…」显式层提示
    layer_hint = ""
    hinted = _LAYER_HINT.match(body)
    if hinted:
        layer_hint = body[: hinted.end()].rstrip("：: ").strip()
        body = body[hinted.end() :].strip()
        layer_hint = {"偏好": "fact", "偏好类": "fact", "教训": "lesson", "话题": "topic"}.get(layer_hint, "")
    remember = _REMEMBER.match(body)
    if remember:
        body = body[remember.end() :].strip()
    body = body.strip(" 　:：-—")
    if not body or _is_small_talk(body):
        return None
    if len(body) < 4 and body not in _SMALL_TALK:
        return None
    text = body[:MAX_ENTRY_CHARS]
    if _LESSON_HINTS and any(hint in text for hint in _LESSON_HINTS):
        return "lesson", text
    if layer_hint:
        return layer_hint, text
    if remember:
        return "fact", text
    if any(hint in text for hint in _FACT_HINTS):
        return "fact", text
    if len(text) >= 6 and any(hint in text for hint in _TASK_HINTS):
        return "topic", text
    return None


# ---------------------------------------------------------------- 同步


def _load_state(path: Path) -> dict[str, Any]:
    data = _load_json(path, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("seen", {})
    return data


def _save_state(path: Path, state: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _turn_key(turn: dict[str, Any]) -> str:
    return f"{turn['bucket']}/{turn['pet']}/{turn['index']}/{int(turn['ts'])}"

def sync(config_dir: Path | None = None, full: bool = False, quiet: bool = False) -> dict[str, Any]:
    """把 DSH 插件记忆并入独立版桌宠记忆。返回一份可打印的报告。"""
    config_dir = config_dir or resolve_config_dir()
    state_path = config_dir / STATE_FILE
    plugin_path = plugin_memory_path()
    report: dict[str, Any] = {
        "config_dir": str(config_dir),
        "plugin_memory": str(plugin_path),
        "plugin_exists": plugin_path.is_file(),
        "targets": [],
        "added": 0,
        "refreshed": 0,
        "skipped": 0,
        "errors": [],
        "checked_at": _now_iso(),
    }
    if not plugin_path.is_file():
        report["errors"].append("插件记忆不存在（dsh-pet 还没聊过天？）")
        _remember_last_run(config_dir, report)
        return report

    turns = read_plugin_turns(plugin_path)
    state = _load_state(state_path)
    seen = state.get("seen") if isinstance(state.get("seen"), dict) else {}
    if full:
        seen = {}

    # 逐条转换（先全部转完，再按目标角色落盘）
    converted: list[dict[str, Any]] = []
    for turn in turns:
        key = _turn_key(turn)
        if key in seen:
            continue
        seen[key] = True
        decided = classify_turn(turn["text"])
        if not decided:
            report["skipped"] += 1
            continue
        layer, text = decided
        converted.append(
            {
                "layer": layer,
                "text": text,
                "ts": turn["ts"],
                "pet": turn["pet"],
                "bucket": turn["bucket"],
                "turn": key,
            }
        )

    characters = [name for name, path in pet_memory_paths(config_dir)]
    if not characters:
        characters = resolve_characters(config_dir)

    lock_path = config_dir / ("memory" + LOCK_SUFFIX)
    with file_lock(lock_path):
        for character in characters:
            target = config_dir / "sessions" / character / "memory.json"
            memory = read_pet_memory(target)
            if memory is None:
                report["errors"].append(f"记忆文件解析失败，跳过写入：{target}")
                continue
            entries = [e for e in (_clean_entry(x) for x in memory.get("entries") or []) if e]
            index = {normalize_text(e["text"]): e for e in entries}
            added = refreshed = 0
            for item in converted:
                key = normalize_text(item["text"])
                if not key:
                    continue
                existing = index.get(key)
                if existing is not None:
                    existing["hits"] = int(existing.get("hits") or 0) + 1
                    existing["updated_at"] = _now_iso()
                    refreshed += 1
                    continue
                entry = _clean_entry(
                    {
                        "text": item["text"],
                        "source": "auto",
                        "layer": item["layer"],
                        "created_at": _ts_to_iso(item["ts"]),
                        "updated_at": _now_iso(),
                        "hits": 0,
                        "origin": "dsh-pet",
                        "dsh_pet": item["pet"],
                        "dsh_bucket": item["bucket"],
                    }
                )
                if entry is None:
                    continue
                entries.append(entry)
                index[key] = entry
                added += 1
            if added or refreshed:
                write_pet_memory(target, {"entries": _enforce_limits(entries)})
            report["added"] += added
            report["refreshed"] += refreshed
            report["targets"].append({"character": character, "path": str(target), "added": added, "refreshed": refreshed})

    state["seen"] = {k: True for k in list(seen)[-4000:]}
    state["last_run"] = report
    _save_state(state_path, state)
    if not quiet:
        log_line(config_dir, f"sync: +{report['added']} ~{report['refreshed']} skip={report['skipped']}")
    return report


def _remember_last_run(config_dir: Path, report: dict[str, Any]) -> None:
    state_path = config_dir / STATE_FILE
    state = _load_state(state_path)
    state["last_run"] = report
    _save_state(state_path, state)


# ---------------------------------------------------------------- 反向导出


def export_markdown(config_dir: Path | None = None) -> dict[str, Any]:
    """把桌宠侧的记忆导出成 DSH 可读的 JSON + Markdown。"""
    config_dir = config_dir or resolve_config_dir()
    out_dir = export_dir()
    report: dict[str, Any] = {"dir": str(out_dir), "characters": [], "entries": 0}
    payload: dict[str, Any] = {
        "version": 1,
        "exported_at": _now_iso(),
        "source": "dsh-pet-standalone-webm-chat",
        "characters": {},
    }
    lines = ["# 桌宠记忆（导出自 dsh-pet-standalone-webm-chat）", ""]
    for character, path in pet_memory_paths(config_dir):
        memory = read_pet_memory(path)
        if not memory:
            continue
        entries = [e for e in (_clean_entry(x) for x in memory.get("entries") or []) if e]
        if not entries:
            continue
        payload["characters"][character] = entries
        report["entries"] += len(entries)
        report["characters"].append(character)
        lines.append(f"## 角色：{character}")
        for layer in ("user", "lesson", "fact", "topic"):
            group = [e for e in entries if e["layer"] == layer and not e.get("archived")]
            if not group:
                continue
            lines.append(f"### {layer}")
            for entry in sorted(group, key=lambda e: str(e.get("updated_at") or ""), reverse=True):
                lines.append(f"- {entry['text']}")
        lines.append("")
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_dir / "memory.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(out_dir / "memory.md", "\n".join(lines).rstrip() + "\n")
    report["markdown"] = str(out_dir / "memory.md")
    return report


# ---------------------------------------------------------------- 状态


def status(config_dir: Path | None = None) -> dict[str, Any]:
    config_dir = config_dir or resolve_config_dir()
    state = _load_state(config_dir / STATE_FILE)
    info: dict[str, Any] = {
        "config_dir": str(config_dir),
        "plugin_memory": str(plugin_memory_path()),
        "plugin_exists": plugin_memory_path().is_file(),
        "plugin_turns": len(read_plugin_turns(plugin_memory_path())),
        "state": str(config_dir / STATE_FILE),
        "last_run": state.get("last_run"),
        "seen": len(state.get("seen") or {}),
        "targets": [],
    }
    for character, path in pet_memory_paths(config_dir):
        memory = read_pet_memory(path) or {}
        entries = memory.get("entries") or []
        counts: dict[str, int] = {}
        for entry in entries:
            layer = str(entry.get("layer") or "fact") if isinstance(entry, dict) else "fact"
            counts[layer] = counts.get(layer, 0) + 1
        info["targets"].append(
            {"character": character, "path": str(path), "exists": path.is_file(), "count": len(entries), "layers": counts}
        )
    return info


def memory_count(config_dir: Path | None = None) -> int:
    """岛扩展用：全部角色记忆条目总数（不抛异常）。"""
    try:
        config_dir = config_dir or resolve_config_dir()
    except Exception:
        return 0
    total = 0
    for _character, path in pet_memory_paths(config_dir):
        memory = read_pet_memory(path) or {}
        total += len(memory.get("entries") or [])
    return total


# ---------------------------------------------------------------- CLI


def _print(obj: Any) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(text.encode("utf-8", "replace"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    action = args[0] if args else "status"
    full = "--full" in args
    if action == "status":
        _print(status())
        return 0
    if action == "sync":
        _print(sync(full=full))
        return 0
    if action == "export":
        _print(export_markdown())
        return 0
    if action == "watch":
        interval = DEFAULT_INTERVAL
        for arg in args[1:]:
            if arg.startswith("--interval="):
                try:
                    interval = max(5.0, float(arg.split("=", 1)[1]))
                except ValueError:
                    pass
        config_dir = resolve_config_dir()
        while True:
            try:
                report = sync(config_dir=config_dir, quiet=True)
                export_markdown(config_dir=config_dir)
                log_line(config_dir, f"watch: +{report['added']} ~{report['refreshed']}")
            except Exception as exc:  # 常驻进程绝不因一次失败退出
                log_line(config_dir, f"watch 失败: {exc!r}")
            time.sleep(interval)
    _print({"error": f"unknown action: {action}", "usage": ["status", "sync [--full]", "export", "watch [--interval=N]"]})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
