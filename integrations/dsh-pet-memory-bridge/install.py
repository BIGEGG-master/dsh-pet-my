"""把「DSH 记忆桥」安装成本机桌宠的一个灵动岛组件（幂等，可重复运行）。

用法::

    python install.py            # 安装/更新到本机配置目录
    python install.py --remove   # 卸载（只删本组件，不碰记忆数据）

安装位置：``<桌宠配置目录>/island-extensions/dsh_memory/``
桌宠启动后会扫描该目录；provider 在桌宠进程内运行，首次采样即开始增量同步。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from memory_bridge import resolve_config_dir  # noqa: E402

COMPONENT_ID = "dsh_memory"
FILES = ("island-component.json", "provider.py")


def install() -> Path:
    config_dir = resolve_config_dir()
    target = config_dir / "island-extensions" / COMPONENT_ID
    target.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copy2(HERE / "island-component" / name, target / name)
    # provider 与核心库必须同目录：它按绝对路径加载 memory_bridge.py
    shutil.copy2(HERE / "memory_bridge.py", target / "memory_bridge.py")
    return target


def remove() -> Path:
    config_dir = resolve_config_dir()
    target = config_dir / "island-extensions" / COMPONENT_ID
    if target.is_dir():
        shutil.rmtree(target)
    return target


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--remove" in args:
        target = remove()
        print(f"已卸载：{target}")
        return 0
    target = install()
    print(f"已安装：{target}")
    for path in sorted(target.iterdir()):
        print(f"  {path.name}  ({path.stat().st_size} bytes)")
    print("提示：重启桌宠后生效（灵动岛会多出「记忆」一段）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
