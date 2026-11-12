"""灵动岛组件：DSH 记忆桥（provider 与 read/format 入口）。

宿主只有一个采样线程会调用 :func:`read_count`，所以这里只做**毫秒级**的事：
读一份内存缓存；真正的读写盘全部丢给本模块自己起的 daemon 线程（首次采样即启动，
之后每 ``INTERVAL_SECONDS`` 秒增量同步一次 DSH 插件记忆并反向导出）。

这样即使 DSH 那边的记忆文件很大、或磁盘卡住，岛上的这一段也只会"数字晚一拍"，
不会因为一次慢读被宿主熔断。
"""

from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

INTERVAL_SECONDS = 60.0

_HERE = Path(__file__).resolve().parent
_BRIDGE: object | None = None
_START_LOCK = threading.Lock()
_THREAD: threading.Thread | None = None
_STATE: dict[str, object] = {"count": None, "added": 0, "last": 0.0, "error": ""}


def _load_bridge():
    """按绝对路径加载同目录的 memory_bridge.py（不污染 sys.path，不撞宿主模块名）。"""
    global _BRIDGE
    if _BRIDGE is not None:
        return _BRIDGE
    spec = importlib.util.spec_from_file_location("_dsh_memory_bridge", _HERE / "memory_bridge.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("memory_bridge.py 缺失")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _BRIDGE = module
    return module


def _refresh() -> None:
    try:
        bridge = _load_bridge()
        report = bridge.sync(quiet=True)
        bridge.export_markdown()
        _STATE["count"] = bridge.memory_count()
        _STATE["added"] = int(report.get("added") or 0)
        _STATE["last"] = time.time()
        _STATE["error"] = ""
    except Exception as exc:  # 一次失败绝不能让采样线程死掉
        _STATE["error"] = repr(exc)[:160]


def _worker() -> None:
    while True:
        _refresh()
        time.sleep(INTERVAL_SECONDS)


def _ensure_started() -> None:
    global _THREAD
    with _START_LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_worker, name="dsh-memory-bridge", daemon=True)
            _THREAD.start()


def read_count() -> int:
    """段的原始值：桌宠侧当前的记忆条目总数。

    只读内存缓存（首拍在后台线程算出来之前返回 0）——这条线程是宿主唯一的采样线程，
    绝不为加载模块或读盘在这里等。
    """
    _ensure_started()
    try:
        return max(0, int(_STATE["count"] or 0))
    except (TypeError, ValueError):
        return 0


def format_count(value) -> str:
    """紧凑文案：只显示数字，label 已经写明「记忆」。"""
    try:
        return str(max(0, int(value)))
    except (TypeError, ValueError):
        return "--"
