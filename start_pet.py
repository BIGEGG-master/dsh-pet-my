"""启动这个桌宠，并把「DSH 现在监听哪个端口」一起交给它。

桌宠的 DSH 联动（``pet/agent_link``）靠端口探活判断 DSH 在不在线，内置候选是
3080 / 19387 / 38080 再加环境变量 ``DSH_PORT``；而 DSH 的实际端口是启动时分配的
（本机常见 27084），所以直接双击 exe 往往联动一直是 offline。

这个启动器做三件事：
1. 找到正在运行的 DSH 进程（优先桥文件 ``dsh-{pid}.jsonl`` 里的 pid，其次按进程名）；
2. 用 ``netstat`` 取它 LISTENING 的端口并注入 ``DSH_PORT``；
3. 拉起同目录的桌宠 exe（已在本机运行则只打印提示，不重复开）。

用法::

    python start_pet.py            # 启动（或提示已在运行）
    python start_pet.py --status   # 只看当前探测结果
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXE = HERE / "dsh-pet-standalone-webm-chat.exe"
IMAGE = EXE.name
DSH_IMAGE = "DeepSeek Harness.exe"


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))


def _tasklist(image: str) -> list[int]:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for row in csv.reader(out.splitlines()):
        if len(row) >= 2 and row[0].lower() == image.lower():
            try:
                pids.append(int(row[1]))
            except ValueError:
                pass
    return pids


def _listen_ports() -> dict[int, list[int]]:
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        try:
            port = int(parts[1].rsplit(":", 1)[-1])
            pid = int(parts[4])
        except ValueError:
            continue
        table.setdefault(pid, []).append(port)
    return table


def _bridge_pids() -> list[int]:
    pids: list[int] = []
    bridge = _appdata() / "dsh-pet-bridge"
    try:
        for name in bridge.glob("dsh-*.jsonl"):
            stem = name.stem  # dsh-7080
            _, _, pid = stem.partition("-")
            if pid.isdigit():
                pids.append(int(pid))
    except OSError:
        pass
    return pids


def find_dsh_port() -> tuple[int | None, list[int]]:
    ports = _listen_ports()
    candidates: list[int] = []
    for pid in _bridge_pids() + _tasklist(DSH_IMAGE):
        for port in ports.get(pid, []):
            if port > 0 and port not in candidates:
                candidates.append(port)
    return (candidates[0] if candidates else None), candidates


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    port, candidates = find_dsh_port()
    running = _tasklist(IMAGE)
    if "--status" in args:
        print(f"桌宠进程：{running or '未运行'}")
        print(f"DSH 候选端口：{candidates or '未探测到'}")
        print(f"将注入 DSH_PORT：{port if port else '(不注入)'}")
        return 0
    if running:
        print(f"桌宠已在运行（pid={','.join(map(str, running))}），不重复启动。")
        return 0
    if not EXE.is_file():
        print(f"找不到桌宠可执行文件：{EXE}")
        return 1
    env = dict(os.environ)
    if port and not env.get("DSH_PORT"):
        env["DSH_PORT"] = str(port)
    print(f"启动桌宠…（DSH_PORT={env.get('DSH_PORT', '默认候选')}）")
    subprocess.Popen([str(EXE)], cwd=str(HERE), env=env, close_fds=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
