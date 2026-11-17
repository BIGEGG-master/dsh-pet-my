"""把插件里的角色卡（人设 + 台词 + 名字）应用到这个独立版桌宠。

角色卡来自 ``dsh-pet`` 插件的皮肤包（``pet-pack/skins/feiyu-*``）：一份人设正文 +
一套按事件口吻的台词。独立版桌宠没有"第二套立绘"，所以这里做的是**角色卡层**的迁移：

- ``chat.default_system_prompt`` ← 人设正文
- ``character_aliases[<当前角色>]`` ← 角色显示名
- ``dialogue_mode`` = ``custom``、``dialogue_phrases`` ← 30 个事件的全套台词

用法::

    python apply_persona.py            # 应用（先备份）
    python apply_persona.py --revert   # 回滚到最近一次备份
    python apply_persona.py --print    # 只打印将产生的 persona-phrases/v1 模板

写配置前请先退出桌宠（它会在退出时把内存里的配置写回，覆盖外部修改）。
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CARD = HERE / "feiyu.persona-card.json"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dsh-pet-memory-bridge"))
try:
    from memory_bridge import resolve_characters, resolve_config_dir  # noqa: E402
except ImportError:  # 目录被移动时的兜底
    resolve_config_dir = None  # type: ignore[assignment]
    resolve_characters = None  # type: ignore[assignment]


def _config_dir() -> Path:
    if resolve_config_dir is None:
        raise SystemExit("找不到 memory_bridge.py（应与本脚本同仓库）")
    return resolve_config_dir()


def _characters(config_dir: Path) -> list[str]:
    if resolve_characters is None:
        return ["shenshen"]
    return resolve_characters(config_dir)


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"配置不是对象：{path}")
    return data


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + f".{datetime.now().strftime('%H%M%S%f')}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def _template(card: dict) -> dict:
    return {
        "template": "persona-phrases/v1",
        "mode": "custom",
        "name": str(card.get("name") or "角色卡"),
        "description": f"角色卡：{card.get('name')}（来自 {card.get('source')}）",
        "phrases": dict(card.get("phrases") or {}),
    }


def apply(revert: bool = False) -> int:
    config_dir = _config_dir()
    config_path = config_dir / "config.json"
    card = _load(CARD)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = HERE / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    if revert:
        backups = sorted(backup_dir.glob("config-*.json"))
        if not backups:
            print("没有可回滚的备份。")
            return 1
        latest = backups[-1]
        shutil.copy2(latest, config_path)
        print(f"已回滚：{latest.name} → {config_path}")
        return 0

    config = _load(config_path)
    shutil.copy2(config_path, backup_dir / f"config-{stamp}.json")

    chat = config.get("chat")
    if not isinstance(chat, dict):
        chat = {}
        config["chat"] = chat
    old_prompt = chat.get("default_system_prompt")
    chat["default_system_prompt"] = str(card.get("system_prompt") or old_prompt or "")

    config["dialogue_mode"] = "custom"
    config["dialogue_phrases"] = dict(card.get("phrases") or {})

    aliases = config.get("character_aliases")
    if not isinstance(aliases, dict):
        aliases = {}
    for character in _characters(config_dir):
        aliases[character] = str(card.get("name") or character)
    config["character_aliases"] = aliases

    _atomic_write(config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    template_path = HERE / "feiyu.persona-phrases.json"
    _atomic_write(template_path, json.dumps(_template(card), ensure_ascii=False, indent=2) + "\n")

    print(f"已应用角色卡「{card.get('name')}」")
    print(f"  配置：{config_path}")
    print(f"  备份：{backup_dir / f'config-{stamp}.json'}")
    print(f"  台词模板：{template_path}（可在设置页「导入模板」里复用）")
    print(f"  事件台词：{len(card.get('phrases') or {})} 组；角色别名：{aliases}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--print" in args:
        card = _load(CARD)
        sys.stdout.buffer.write(
            (json.dumps(_template(card), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
        return 0
    return apply(revert="--revert" in args)


if __name__ == "__main__":
    raise SystemExit(main())
