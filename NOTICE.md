# NOTICE — 关于本仓库的来源与许可

## 上游项目

本仓库是以下项目的**修改版（fork / derivative）**，不是原创项目：

- **项目**：dsh-pet-indesktop
- **上游仓库**：https://github.com/MerZlin/dsh-pet-indesktop
- **上游基线版本**：4.4.0（`pet/__init__.py` 的 `__version__` 在本次修改前为 `4.4.0`）
- **许可证**：MIT License，Copyright (c) 2026 Merzlin（见仓库根 `LICENSE`，未做任何修改）

MIT 允许复制、修改、再分发与商用，但**要求保留原版权声明与许可文本**。因此：

- `LICENSE` 保持上游原文，不得删除或替换；
- `THIRD_PARTY_NOTICES.md` 保持上游内容；
- 本文件说明衍生关系，避免让人误以为上游作者参与了本修改版。
- 本仓库**不代表**上游作者的任何背书或官方发布。

## 本修改版相对上游 4.4.0 的改动

版本号已升为 **4.4.1**。改动集中在 DSH 联动与开发工具链，全部为新增或小改，
没有重写既有架构：

### 新增文件

| 路径 | 作用 |
| --- | --- |
| `pet/chat/dsh_memory.py` | 把 DSH 桌宠插件的对话记忆并入本机四层记忆 |
| `pet/persona_cards.py` | 角色卡模型（人设 + 显示名 + 事件台词） |
| `pet/persona_cards/builtin/feiyu.json` | 内置角色卡「小肥鱼」（30 组台词） |
| `tests/test_dsh_memory.py` | 记忆同步：分类 / 解析 / 幂等 / 节流 |
| `tests/test_persona_cards.py` | 角色卡：加载 / 应用 / 模板 / 用户卡覆盖 |
| `tests/test_dsh_quit_follow.py` | 随 DSH 退出的决策逻辑 |
| `integrations/dsh-pet-memory-bridge/` | 同一件事的独立脚本版（含反向导出） |
| `integrations/dsh-pet-persona/` | 角色卡提取与应用脚本 |
| `dev/` | 开发脚本与文档（见下） |
| `start_pet.py` | 启动器：探测 DSH 端口后注入 `DSH_PORT` 再拉起桌宠 |

### 修改文件

| 路径 | 改动 |
| --- | --- |
| `pet/harness_launcher.py` | 新增 `discover_dsh_ports()`：从桥文件写者 pid 动态发现 DSH 端口 |
| `pet/agent_link/__init__.py` | `DshMonitor._probe_online()` 叠加动态端口 |
| `pet/app.py` | 新增 `_follow_dsh_lifecycle` / `_quit_for_dsh_exit`：随 DSH 退出 |
| `pet/config.py` | 新增 `dsh_quit_with_dsh`、`dsh_quit_grace_seconds` 两个全局键 |
| `pet/chat/widgets.py`、`pet/chat/legacy_widgets.py` | 发问前调用 DSH 记忆同步 |
| `pet/chat/ai_settings_page.py` | 新增「角色卡」设置分组 |
| `scripts/build_onedir.ps1` | `-SkipCheck` 也跳过 frameseq 门；`--add-data` 带上 `pet/persona_cards` |
| `tests/test_config_schema.py` | 白名单快照登记两个新键 |

### `dev/` 工具链

```
dev/
├─ setup.ps1        建 .venv 并装依赖
├─ run.ps1          源码直跑
├─ build.ps1        升版本 + 打包（-Bump patch|minor|major）
├─ publish.ps1      部署到安装目录并启动
├─ pack_source.ps1  打可分发的源码 zip（排除环境/构建产物/缓存）
├─ configure_ai.py  配 AI provider（key 进系统钥匙串）
├─ bump_version.py  版本号读写（唯一来源 pet/__init__.py）
├─ README.md        完整流程与两个必读的坑
├─ 增强说明.md       4.4.1 四项功能的设计与验证
└─ plans/           设计记录
```

## 与上游同步

如果你想把上游后续更新合进来：以上游 tag 为远端分支（如
`git remote add upstream https://github.com/MerZlin/dsh-pet-indesktop.git`），
再按文件级冲突处理——`pet/` 下的改动都是局部增补，冲突面很小；
`scripts/build_onedir.ps1` 与 `tests/test_config_schema.py` 是唯一两处
「插入式」改动，合并时优先保留双方的意图。

## 第三方资源

仓库内的动画素材、表情包、字体、OCR 模型、PresentMon 等各自的许可证见
`THIRD_PARTY_NOTICES.md` 与 `resources/*/LICENSE*`；再分发时请不要移除这些文件。
