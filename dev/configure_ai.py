# -*- coding: utf-8 -*-
"""把桌宠的 AI 对话 provider 配好：写 config.json + 把 key 放进系统钥匙串。

用法::

    python dev/configure_ai.py --key sk-xxxx
    python dev/configure_ai.py --key sk-xxxx --base-url https://api.deepseek.com --model deepseek-chat
    python dev/configure_ai.py --show
    python dev/configure_ai.py --key sk-xxxx --dry-run      # 只看会写什么
    python dev/configure_ai.py --key sk-xxxx --test         # 写完立刻试一次真实请求

设计要点：
- **key 只进 keyring**（service ``dsh-pet-standalone``，ref ``provider/<id>``），
  config.json 里只留 ref，不落明文；与桌宠设置页的存储方式完全一致。
- 只改 ``chat.providers[<id>]`` / ``chat.active_provider`` / ``chat.enabled``，
  人设、记忆、台词等一概不碰。
- 写盘前自动备份到 ``<配置目录>/config.json.ai-backup-<时间戳>``。
- 不 import pet 包（那会连带 PySide6）：本脚本只依赖标准库 + keyring。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

SERVICE = "dsh-pet-standalone"
#: 打包变体的数据目录（APP_DIR_NAME = "dsh-pet-standalone-" + VARIANT）
APP_DIR = "dsh-pet-standalone-webm-chat"
#: 源码直跑（dev\run.ps1）时的数据目录：没有 packaging/build_variant.py，
#: _app_dir_name() 回退到共享名。两者**不是同一个目录**，别搞混。
LEGACY_APP_DIR = "dsh-pet-standalone"


def config_dir(explicit: str = "") -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("DSH_PET_CONFIG_DIR", "").strip()
    if env:
        return Path(env)
    base = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
    for name in (APP_DIR, LEGACY_APP_DIR):
        candidate = base / name
        if (candidate / "config.json").is_file():
            return candidate
    return base / APP_DIR


def _keyring():
    try:
        import keyring  # noqa: PLC0415
    except ImportError:
        return None
    return keyring


def _mask(value: str) -> str:
    if not value:
        return "(空)"
    return value[:5] + "…(" + str(len(value)) + " 字符)"


def show(config_path: Path) -> int:
    data = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    chat = data.get("chat") or {}
    active = chat.get("active_provider") or ""
    providers = chat.get("providers") or {}
    print(f"配置：{config_path}")
    print(f"启用：{chat.get('enabled')}　当前 provider：{active or '(未设置)'}")
    if not providers:
        print("providers：空（还没配过）")
        return 0
    kr = _keyring()
    for pid, prov in providers.items():
        ref = str(prov.get("api_key_ref") or "")
        stored = ""
        if kr is not None and ref:
            try:
                stored = str(kr.get_password(SERVICE, ref) or "")
            except Exception:
                stored = ""
        mark = " ←当前" if pid == active else ""
        print(f"  [{pid}]{mark} {prov.get('name')} · {prov.get('base_url')} · {prov.get('model')}")
        print(f"      key: {_mask(stored)}")
    return 0


def probe(base_url: str, model: str, key: str, chat_path: str, timeout: float = 20.0) -> bool:
    url = base_url.rstrip("/") + chat_path
    payload = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1, "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(400).decode("utf-8", "replace")
        print(f"测试连接：OK（{response.status}）{body[:120]}")
        return True
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode("utf-8", "replace")
        print(f"测试连接：HTTP {exc.code} —— {detail[:200]}")
        return False
    except Exception as exc:
        print(f"测试连接：失败 —— {type(exc).__name__}: {exc}")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配置桌宠 AI 对话 provider")
    parser.add_argument("--provider-id", default="openai-main")
    parser.add_argument("--config-dir", default="", help="桌宠数据目录（默认自动探测）")
    parser.add_argument("--name", default="DeepSeek")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--chat-path", default="/v1/chat/completions")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--key", default="", help="API key；只写进系统钥匙串")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--show", action="store_true", help="只打印当前配置")
    parser.add_argument("--dry-run", action="store_true", help="不写盘，只打印将要写入的内容")
    parser.add_argument("--test", action="store_true", help="写完立刻发一次最小请求")
    args = parser.parse_args(argv)

    directory = config_dir(args.config_dir)
    config_path = directory / "config.json"
    if args.show:
        return show(config_path)
    if not args.key:
        print("缺少 --key（或用 --show 查看当前配置）", file=sys.stderr)
        return 2

    data: dict = {}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"config.json 解析失败，拒绝覆盖：{exc}", file=sys.stderr)
            return 1
    chat = data.get("chat")
    if not isinstance(chat, dict):
        chat = {}
        data["chat"] = chat
    providers = chat.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        chat["providers"] = providers

    ref = f"provider/{args.provider_id}"
    provider = providers.get(args.provider_id)
    if not isinstance(provider, dict):
        provider = {}
        providers[args.provider_id] = provider
    provider.update(
        {
            "name": args.name,
            "base_url": args.base_url,
            "chat_path": args.chat_path,
            "model": args.model,
            "api_key_ref": ref,
            "timeout": 60.0,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
        }
    )
    chat["enabled"] = True
    chat["active_provider"] = args.provider_id

    if args.dry_run:
        preview = json.loads(json.dumps(data))
        print(f"[dry-run] 将写 {config_path}：")
        print(json.dumps(preview.get("chat", {}), ensure_ascii=False, indent=2))
        print(f"[dry-run] 将把 key {_mask(args.key)} 写入 keyring {SERVICE}/{ref}")
        return 0

    kr = _keyring()
    if kr is None:
        print("keyring 不可用（venv 里没装？），拒绝把 key 落进 config.json", file=sys.stderr)
        return 1
    try:
        kr.set_password(SERVICE, ref, args.key)
    except Exception as exc:
        print(f"写系统钥匙串失败：{exc}", file=sys.stderr)
        return 1

    if config_path.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = config_path.with_name(f"config.json.ai-backup-{stamp}")
        shutil.copy2(config_path, backup)
        print(f"已备份：{backup}")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入：{config_path}")
    print(f"  provider = {args.provider_id}　{args.name} · {args.base_url} · {args.model}")
    print(f"  key = {_mask(args.key)}（存于系统钥匙串 {SERVICE}/{ref}）")

    if args.test:
        return 0 if probe(args.base_url, args.model, args.key, args.chat_path) else 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
