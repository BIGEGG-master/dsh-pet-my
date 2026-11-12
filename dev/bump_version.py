# -*- coding: utf-8 -*-
"""版本号唯一来源的读写工具（供 dev/build.ps1 调用）。

约定：**版本号只有一个来源** —— ``pet/__init__.py`` 里的 ``__version__``。
安装包、更新检测、安装目录名都从它推导，所以升版本只改这一处。

用法::

    python dev/bump_version.py            # 打印当前版本
    python dev/bump_version.py patch      # 4.4.0 -> 4.4.1
    python dev/bump_version.py minor      # 4.4.0 -> 4.5.0
    python dev/bump_version.py major      # 4.4.0 -> 5.0.0
    python dev/bump_version.py set 4.4.2  # 直接指定
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "pet" / "__init__.py"
PATTERN = re.compile(r"__version__\s*=\s*['\"]([^'\"]+)['\"]")


def read_version() -> str:
    match = PATTERN.search(INIT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"在 {INIT} 里找不到 __version__")
    return match.group(1)


def write_version(value: str) -> None:
    text = INIT.read_text(encoding="utf-8")
    replaced, count = PATTERN.subn(f"__version__ = '{value}'", text, count=1)
    if count != 1:
        raise SystemExit("版本号替换失败")
    INIT.write_text(replaced, encoding="utf-8", newline="\n")


def bump(current: str, kind: str) -> str:
    parts = [int(x) for x in current.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    major, minor, patch = parts
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main(argv: list[str]) -> int:
    current = read_version()
    if not argv:
        print(current)
        return 0
    kind = argv[0].lower()
    if kind == "set":
        if len(argv) < 2:
            raise SystemExit("用法：bump_version.py set <x.y.z>")
        target = argv[1]
    elif kind in ("patch", "minor", "major"):
        target = bump(current, kind)
    else:
        raise SystemExit(f"未知参数：{kind}")
    write_version(target)
    print(f"{current} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
