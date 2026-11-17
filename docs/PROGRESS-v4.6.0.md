https://github.com/BIGEGG-master/dsh-pet-my

# 工作进度报告 — dsh-pet 养成系统（v4.6.0）

> 生成时间：2026-11-15 22:26（Asia/Shanghai）
> 仓库：`D:\浏览器\dsh-pet-my-4.5.0\dsh-pet-my-4.5.0`（v4.5.0 源码基线 + 本轮改动）
> 运行目录：`D:\dsh-pet-dev`

---

## 一、当前状态速览

| 项 | 值 |
| --- | --- |
| 版本号 | **4.6.0**（`pet/__init__.py` 唯一来源） |
| 正在运行 | **打包版 exe**：`D:\dsh-pet-dev\dsh-pet-standalone-webm-chat.exe` |
| 进程 | PID 29056，2026-11-15 18:13 启动，内存约 259 MB |
| 渲染拓扑 | overlay（单合成窗） |
| 数据目录 | `%APPDATA%\dsh-pet-standalone-webm-chat`（配置 / 会话 / 记忆都在这） |
| 便携包 | `D:\dsh-pet-dev\_archive\dsh-pet-v4.6.0-portable-20261115-1814.zip`（242.5 MB） |
| 源码压缩包 | `D:\dsh-pet-dev\_archive\dsh-pet-my-v4.5.0-source.zip`（113.4 MB，v4.5.0 时的快照） |
| 回归结果 | 本轮涉及范围 **617 项通过**；全量跑剩余 10 项既有红点（见第七节） |

---

## 二、本轮目标（已完成）

给桌宠加一套**养成系统（Pet Life）**：她有自己的饥饿、口渴、心情、精力、健康，
会饿会困会闷，能打工赚钱、去商店补给，状态还会影响她说话的语气。
另外把状态条做成**可拖动、可贴边、悬停展开**的悬浮件。

全部按"四层架构"落地，数值平衡只改一张数据表，规则逻辑可纯函数单测。

---

## 三、四层架构（已实现）

| 层 | 文件 | 职责 | 依赖 |
| --- | --- | --- | --- |
| 数据表 | `pet/pet_life_data.py` | 衰减速率、4 份工作、4 件商品、3 种玩耍、动画关键词池、阈值与台词 | 无 |
| 纯逻辑 | `pet/pet_life.py` | 夹紧、衰减、睡觉、工作结算、商店交易、注入文案、动画挑选 | 无 Qt / 无 IO |
| 运行时服务 | `pet/pet_life_service.py` | 60s 心跳、指纹去重落盘、把结果发成 Qt 信号 | Qt Core |
| 呈现 | `pet/pet_life_hud.py`、`pet/pet_life_dialog.py` | 状态条 / 「嘟嘟的生活」面板 | Qt Widgets |

**分层收益**：调平衡改数据表；规则错在纯逻辑层被 40 项单测当场钉住；服务与界面
都能在无窗口环境构造（测试不需要真桌面）。

---

## 四、功能清单

### 4.1 五维属性

| 属性 | 每小时掉 | 行为影响 |
| --- | --- | --- |
| 饥饿 | −6 | 见底开始掉健康（−2/h）；< 20 主动喊饿 |
| 口渴 | −8 | 同上；< 20 主动要水 |
| 心情 | 不自然衰减 | 只由事件驱动；< 20 会求陪 |
| 精力 | −5 | ≤ 15 自动去睡；睡眠时 +20/h；< 40 回话变短、多撒娇 |
| 健康 | 见底惩罚 | = 0 时「病倒」：工作/玩耍被拒，只有喂食喝水能救 |

- **离线保护**：单次心跳最多结算 2 小时（`MAX_TICK_HOURS`），关机一周回来不会一开机就病倒
- **睡觉滞回**：精力 ≤ 15 入睡、≥ 70 醒，不在阈值上反复横跳

### 4.2 工作 / 玩耍 / 商店

| 工作 | 收入 | 消耗 | 时长 |
| --- | --- | --- | --- |
| 基础打字 | +8 币 | 精力 −8、心情 −2 | 10 分钟 |
| AI 编程助手 | +20 币 | 精力 −15、饥饿 −6 | 10 分钟 |
| 研究狭义相对论 | +45 币 | 精力 −25、健康 −3、心情 −4 | 10 分钟 |
| 直播大肥鲸表演 | +30 币 | 心情 −12、精力 −18 | 10 分钟 |

- 可中断；中断 = 白干（不结算，防"开了就关"白拿钱）
- 关机期间到点的活，下次启动第一拍自动结算
- 玩耍：深海大冒险（心情 +30 / 精力 −10）、练习拍地（健康 +20 / 精力 −5）、追逐光点（心情 +15 / 精力 −20）
- 商店：深海气泡水 10、深海蓝藻奶昔 25、鲸鱼尾巴按摩器 60、量子纠缠零食 40（25% 概率额外 +20 精力）
- **免费动作有冷却**：喂食 30 分钟、喝水 20 分钟（没冷却就能无限刷）

### 4.3 自主生命感

服务每 60 秒检查，命中阈值就冒气泡 + 换表情：

| 触发 | 台词示例 | 动画关键词 |
| --- | --- | --- |
| 饥饿 < 20 | 「哥哥…嘟嘟肚子在叫了嘟。」 | 吃\* |
| 口渴 < 20 | 「好渴嘟，想喝水…」 | 吐泡泡 / 喝 |
| 精力 ≤ 15 | 「好困…嘟嘟先眯一会儿可以吗？」 | 原地小憩沉眠 / 打瞌睡 |
| 心情 < 20 | 「有点闷…哥哥陪我说说话嘛。」 | 碎碎念 |

- 同类事件 30 分钟冷却，不刷屏；睡着时不喊饿
- **动画名不硬编码**：在素材库 `acts` 里按关键词子串匹配，匹配不到就静默不播

### 4.4 AI 语气联动

聊天时把状态快照注入 System Prompt（`pet/chat/prompt.py`）：

```
【嘟嘟当前状态】饥饿 62/100（有点饿）、口渴 41/100（渴）、心情 78/100（还不错）、
精力 33/100（有点困）、健康 100/100（很健康）、嘟嘟币 120。
【表达要求】她有点困：回话比平时短一点、语气软一点；她饿坏了：会惦记吃的、容易分心。
不要复述这些数字，也不要解释这份状态。
```

- **空状态 = 逐字节不变**（有断言钉住），关掉养成后提示词与 v4.5.0 完全一致
- 状态段放在「时间感知」之后、「记忆」之前：它是当下事实，不参与记忆召回
- `ChatSettings.pet_status_text` 是运行时字段，`to_dict` 不含它 → 不落盘

### 4.5 状态条（HUD）

- 五条细进度条 + 嘟嘟币，颜色分级（≥60 绿 / ≥30 黄 / 其余红）
- 展示位三档（菜单「嘟嘟的生活 → 状态条显示位置」循环）：跟随桌宠 / 贴在灵动岛 / 隐藏
- **拖动**：左键按住任意位置拖动，松手落位
- **贴边**：松手时离屏幕边 < 60px 吸附到那条边
- **悬停展开 / 移开缩回**：贴边后鼠标移开 2.5 秒缩成 18px 细把手（三条短横线），移回即展开
- **位置记忆**：`pet_life.hud_x / hud_y / hud_edge`，重开还记得
- 拖动过之后不再跟随桌宠（否则刚摆好位置，桌宠一走面板又飘走）
- 取舍：为了让面板能拖，撤掉了鼠标穿透——它覆盖处会挡住下层点击，拖走或切「隐藏」即可

### 4.6 为什么状态条没做进灵动岛

- 岛胶囊内容走 `_content_cache` 位图缓存，状态每秒变就要反复失效重绘
- 岛卡片有固定四区 + 像素级高度对账，插一行要改整套高度算术
- 岛的第三方段只能出**文字**（`island_segments.register_segment` 拿不到 QPainter），画不了彩条

独立窗只需一个 `set_anchor(rect)` + 自己的拖动/贴边状态机，风险小得多。

---

## 五、沿袭的 v4.5.0 能力（本次未改动）

| 能力 | 落点 |
| --- | --- |
| 记忆卡（深层记忆的可视面 + 照片附件 + 她的感受） | `pet/memory_card.py`、`pet/memory_card_dialog.py` |
| 对话日记（按天编日记、跨天搜索、导出） | `pet/diary.py`、`pet/diary_dialog.py` |
| 角色卡两种格式（JSON / Markdown）+ 人设两段式 | `pet/persona_cards.py`、`pet/chat/ai_settings_page.py` |
| 内置角色卡「嘟嘟」 | `pet/persona_cards/builtin/dudu.json` |

---

## 六、本轮修的三个真 bug（都会让功能"看起来没做"）

| # | 现象 | 根因 | 修法 |
| --- | --- | --- | --- |
| 1 | 养成数值落盘后只剩 4 个键，`mood`/`coins`/`hud` 全丢 | `_merge_config_changes` 对 dict 做叶合并；盘上还没有该键时只写"变化过的叶" | `pet_life` 改为整值提交（`_WHOLE_VALUE_KEYS`） |
| 2 | 菜单里根本看不到「嘟嘟的生活」 | 你的 `feature_activation.enabled` 是已判定状态，新模块不会自动加入 | 把 `pet_life` 补进该列表（原始配置备份 `config.json.bak-460`） |
| 3 | 重启后两段式人设退化（v4.5.0 遗留） | `prompt_base` / `prompt_supplement` / `prompt_merge` 设置页会写，但 config 默认值与 `reload` 白名单不认 | 三个键补进 `_initial_data()` 与白名单 |

另外修了：心跳每分钟无条件写盘 → 改成**指纹去重**（数值没变不写），
避免触发桌宠 legacy 拓扑"档案按 mtime 判变化"的重建分支。

---

## 七、测试状态

### 7.1 本轮涉及范围：617 项通过

```
pytest tests/test_pet_life.py tests/test_pet_life_service.py tests/test_pet_life_hud.py \
       tests/test_menu_layout.py tests/test_features.py tests/test_feature_modules_gating.py \
       tests/test_sprite_menu_parity.py tests/test_config_schema.py \
       tests/test_settings_default_marks.py tests/test_settings_features.py \
       tests/test_settings_reset_defaults.py tests/test_desktop_pet_features.py \
       tests/test_architecture.py tests/test_chat_memory.py -q
→ 617 passed
```

### 7.2 新增测试（72 项）

| 文件 | 覆盖 |
| --- | --- |
| `tests/test_pet_life.py`（40） | 夹紧 / NaN / 衰减 / 离线截断 / 饥饿掉血 / 睡觉滞回 / 工作结算（不重复结算、中断不结算）/ 商店（钱不够、概率零食）/ 冷却 / 动画挑选（素材缺失静默）/ 注入文案 |
| `tests/test_pet_life_service.py`（23） | 心跳 / 落盘跨实例 / 信号 / 启动即结算不刷需求 / **首次落盘保留全部键**（bug#1 的回归） |
| `tests/test_pet_life_hud.py`（9） | 拖动 / 贴边吸附 / 屏幕中间不吸附 / 悬停展开 / 移开缩回 / 位置恢复 |

### 7.3 全量跑剩余 10 项红点（与本次改动无关）

| 测试 | 原因 |
| --- | --- |
| `test_agent_settings_hot_reload`（3） | 端口探活断言候选集，本机实际监听端口（3442 / 9230 / 25209）超出文档集 |
| `test_balance`（2） | 节假日日历数据缺失 |
| `test_frameseq_bundle_gate`（2） | 构建脚本里没有测试期望的 `if (-not $isGif) {` 块 |
| `test_island_status_dot`（2） | 岛状态点实测 13×12，断言仍是 8×8 |
| `test_memory_recall::test_manual_pin_remember_topic_unarchives`（1） | 手动钉解除归档，v4.5.0 基线就有 |

我改动的过程中新引入的 8 处失败已全部修复（并同步了默认布局、模块清单、
配置键快照、设置页行数预算等硬断言）。

---

## 八、构建与部署

```powershell
$repo = "D:\浏览器\dsh-pet-my-4.5.0\dsh-pet-my-4.5.0"

# 1) 首次准备环境（本机已建好 .venv，重装才需要）
powershell -ExecutionPolicy Bypass -File "$repo\dev\setup.ps1"

# 2) 打包（-SkipCheck 必带：frameseq 派生物不入库，该门在干净树必红）
powershell -ExecutionPolicy Bypass -File "$repo\dev\build.ps1" -SkipZip -SkipCheck

# 3) 部署到安装目录（自动关旧进程、备份旧 exe、启动）
powershell -ExecutionPolicy Bypass -File "$repo\dev\publish.ps1" -Target D:\dsh-pet-dev

# 4) 恰好源码调试（不打包）
$env:PYTHONPATH = "$repo\packaging"   # 不设会退化成空的 %APPDATA%\dsh-pet-standalone
& "$repo\.venv\Scripts\python.exe" -m pet --instance slot-0
```

> `PYTHONPATH=<repo>\packaging` 是关键：源码模式靠它认到 `webm-chat` 变体名，
> 否则读的是另一个空数据目录（看不到角色卡 / 记忆 / 会话）。

---

## 九、文件清单

### 新增（8 个）

```
pet/pet_life_data.py          数值表（工作 / 商店 / 玩耍 / 动画关键词 / 阈值 / 台词）
pet/pet_life.py               纯逻辑（零 Qt / 零 IO）
pet/pet_life_service.py       60s 心跳 + 指纹落盘 + Qt 信号
pet/pet_life_hud.py           可拖动状态条
pet/pet_life_dialog.py        「嘟嘟的生活」面板
docs/RELEASE-4.6.0.md         更新日志
tests/test_pet_life.py
tests/test_pet_life_service.py
tests/test_pet_life_hud.py
```

### 修改（11 个）

| 文件 | 改什么 |
| --- | --- |
| `pet/config.py` | `pet_life` 默认值 / reload 白名单 + 归一化 / `set()` 写前归一化 / `_WHOLE_VALUE_KEYS` 整值提交 / 补 `prompt_base`·`prompt_supplement`·`prompt_merge` |
| `pet/features.py` | 新 `FeatureSpec(pet_life)`；`MIGRATION_BASELINE` 加 `pet_life` |
| `pet/context_menus/registry.py` | `pet_life` 动作 + 中文名 + 图标 |
| `pet/context_menus/shared.py` | `add_pet_life_menu()`（喂食 / 喝水 / 打开面板 / 状态条位置） |
| `pet/menu_templates/modern-default-v1.json` | 默认布局插 `pet_life` 节点 |
| `pet/window.py` | `PetWindow` 四个回调占位 |
| `pet/sprite_menu_facade.py` | 四个 property（overlay 拓扑可用性判定要求） |
| `pet/app.py` | 服务懒创建 + 心跳 + HUD 轮询 + 面板 + 4 个菜单回调 + 信号接线 + HUD 位置恢复/落盘 |
| `pet/chat/models.py` | `ChatSettings.pet_status_text` 运行时字段 |
| `pet/chat/prompt.py` | `build_messages(pet_status_text=...)` 注入位 |
| `pet/chat/widgets.py` | 调用处传状态段（失败一律空串） |

**明确没动**：`pet/tick_driver.py`、`pet/overlay_shell.py`、`pet/island/*`、`pet/window.py` 的事件与物理、`pet/chat/memory*`。
养成系统只用它们的公开面（`switch_clip` / `show_bubble` / `show_alert` / `build_messages` 参数）。

---

## 十、已知限制

- **只服务主宠**：子肥鱼（多开）不建养成服务，HUD 也不跟随。每宠一份属性需要 slot 路由，v1 没做
- **HUD 位置用 250ms 轮询**：桌宠被拖到别的屏、DPR 变化时最多晚 1/4 秒跟上
- **动画依赖素材关键词**：素材库没有「喝\*」类动画时，喝水只弹气泡不表演
- **商店没有图标**：v1 是文字 + 强调色按钮
- **`owned` 字段预留未用**：永久解锁 / 成就是 v2
- **便携包不含 frameseq 派生物**（242.5 MB）：首次运行会按启动预算自行补转帧序列，与官方 4.4.1 发布包一致

---

## 十一、待办 / 下一步

按价值排序，等你点菜：

1. **子肥鱼也养成**（slot 路由，每宠一份属性）
2. **永久解锁 / 成就**（用上 `owned`：小夜灯、装饰、称号）
3. **商店图标与分类**（消耗品 / 玩具 / 永久）
4. **状态影响动画常驻**（困了就换成打瞌睡的待机链，而不只是冒泡那一瞬）
5. **修复第七节那 10 项既有红点**（尤其 `island_status_dot` 的 13×12 与 `frameseq_bundle_gate` 的脚本不匹配）
6. **把七行 `system_prompt` / `persona_card*` 从 `modern_settings_dialog.py` 拆出去**（当前行数预算已校准到 2735，再涨就该拆了）

---

## 十二、回滚路径

| 场景 | 做法 |
| --- | --- |
| 回滚程序 | `D:\dsh-pet-dev\_backup-v4.6.0-<时间戳>\` 里有上一版 exe；或解压 `_archive\dsh-pet-v4.5.0-portable-*.zip` |
| 关掉养成系统 | 右键菜单「嘟嘟的生活」→ 打开面板 → 底部「关闭养成」；或 `config.json` 的 `pet_life.enabled = false` |
| 隐藏状态条 | 菜单「嘟嘟的生活 → 状态条显示位置」循环到「已隐藏」 |
| 恢复我的配置改动 | `config.json.bak-460`（补 `pet_life` 到 `feature_activation` 之前的那份） |
| 清空养成数据 | 删 `config.json` 里的 `pet_life` 节点，重启即回默认（诚如代码：缺键 = 默认值） |

---

## 十三、变更时间线（v4.5.0 → v4.6.0）

> 数据来源：构建日志 `_build-*.log` / `_publish-*.log`、部署备份目录
> `_backup-v4.6.0-*` 的创建时间、归档 zip 的 mtime、以及新增源码文件的
> CreationTime。均为本机实测时间戳，不是回忆。

### 13.1 起点：v4.5.0 产物（旧仓库时代）

| 时间 | 事件 | 产物 |
| --- | --- | --- |
| 11-12 22:23 | v4.4.1 整目录留档 | `_archive\dsh-pet-v4.4.1-20261112-2221.zip`（622.8 MB） |
| 11-13 09:35 | v4.5.0 便携包构建完成 | `_archive\dsh-pet-v4.5.0-portable-20261113-0933.zip`（923.7 MB） |
| 11-13 09:40 | v4.5.0 源码包（发 GitHub Release 用） | `_archive\dsh-pet-my-v4.5.0-source.zip`（113.4 MB） |
| 11-13 15:06 / 15:07 | 你要求的"动手前先备份" | `dsh-pet-v4.5.0-portable-backup.zip`、`dsh-pet-v4.5.0-source-backup.zip` |

注：v4.5.0 的便携包 923.7 MB，是因为旧仓库自带 `assets/characters/shenshen/frameseq/`（帧序列派生物）；
v4.6.0 的 242.5 MB 是从"干净源码基线"构建的，不含该派生物（首次运行自行补转，见第十节）。

### 13.2 新基线就位 + 写代码（11-13 晚）

| 时间 | 事件 |
| --- | --- |
| 11-13 约 22:30 | 干净源码基线落到 `D:\浏览器\dsh-pet-my-4.5.0\dsh-pet-my-4.5.0`（v4.5.0，无 `.venv`、无养成系统） |
| 11-13 22:57:31 | `dev\setup.ps1` 装完（`.venv` + PySide6 6.12 + pyinstaller 6.22 + pytest） |
| 11-13 22:57:40 | `pet/pet_life_data.py` 创建（数值表） |
| 11-13 22:58:51 | `pet/pet_life.py` 创建（纯逻辑） |
| 11-13 23:03:01 | `pet/pet_life_service.py` 创建（心跳服务） |
| 11-13 23:16:04 | `pet/pet_life_hud.py` 创建（状态条） |
| 11-13 23:17:20 | `pet/pet_life_dialog.py` 创建（「嘟嘟的生活」面板） |

### 13.3 接线 → 构建 → 修 bug（11-15 下午，共 4 轮构建 / 3 次部署）

| 时间 | 事件 | 触发原因 |
| --- | --- | --- |
| 11-15 约 16:40 | 接线：`config.py` / `features.py` / `registry.py` / `shared.py` / `menu_templates` / `window.py` / `sprite_menu_facade.py` / `app.py` | 让菜单、模块门控、HUD 全部接上 |
| 11-15 约 17:00 | `chat/models.py` + `prompt.py` + `widgets.py` 三处小改 | 状态注入 System Prompt |
| 11-15 约 17:05 | 顺手补 v4.5.0 遗留：`prompt_base` / `prompt_supplement` / `prompt_merge` 进默认值与白名单 | 设置页会写但 config 不认 → 重启退化 |
| **11-15 17:31:10** | **构建 #1** 完成（v4.6.0，`_build-460.log`） | 首次可跑 |
| 11-15 17:38–17:50 | 全量测试跑完（9180 passed / 18 failed），修其中 8 处本次引入的红点 | 布局断言、模块清单、配置快照、行数预算等 |
| **11-15 17:51:59** | **构建 #2**（`_build-460-final.log`） | 心跳从"每分钟无条件写盘"改成**指纹去重** |
| **11-15 17:52:22** | **部署 #1** → `_backup-v4.6.0-20261115-175222` | — |
| 11-15 17:54 | 启动实测：`pet_life` 落盘只剩 `energy/hunger/thirst/last_tick_at` 四个键 | 发现"叶合并丢键"bug |
| **11-15 18:03:22** | **构建 #3**（`_build-460-final2.log`） | `_WHOLE_VALUE_KEYS`：`pet_life` 改整值提交 |
| **11-15 18:03:51** | **部署 #2** → `_backup-v4.6.0-20261115-180351` | — |
| 11-15 18:08–18:09 | 重写 `pet_life_hud.py`（拖动 / 贴边吸附 / 悬停展开 / 移开缩回），服务加 `hud_x/hud_y/hud_edge` | 你的新需求 |
| **11-15 18:12:42** | **构建 #4**（`_build-hud.log`） | 含 HUD 交互 |
| **11-15 18:13:00** | **部署 #3** → `_backup-v4.6.0-20261115-181300`；**当前运行** PID 29056 | 最终部署 |
| 11-15 18:14:37 | 最终便携包 | `_archive\dsh-pet-v4.6.0-portable-20261115-1814.zip`（242.5 MB） |
| 11-15 22:26 | 本文档生成 | — |

### 13.4 每轮构建之间到底改了什么

| 构建 | 相对上一轮的新增 |
| --- | --- |
| #1 | 养成系统全量接线 + AI 注入 + 顺手修 v4.5.0 的 `prompt_*` 三键遗留 |
| #2 | 心跳落盘指纹去重（避免 legacy 拓扑按 mtime 反复重建） |
| #3 | `pet_life` 整值提交（修"首次落盘丢键"） |
| #4 | HUD 可拖动 / 贴边 / 悬停展开 + 位置记忆 |

### 13.5 测试通过数随时间变化

| 时点 | 结果 |
| --- | --- |
| 11-15 17:50（全量首跑） | 9180 passed / 18 failed（8 处本次引入 + 10 处既有） |
| 11-15 18:00（修完 8 处后） | 受影响集合 652 passed；9 项既有红点确认与改动无关 |
| 11-15 18:10（加 HUD 测试后） | 养成三件套 72 passed |
| 11-15 18:15（最终回归） | 涉及范围 **617 passed / 0 failed**（10 项既有红点不在该集合内） |

---

## 十四、v4.5.0 → v4.6.0 能力演进对照

| 能力 | v4.5.0 | v4.6.0 |
| --- | --- | --- |
| AI 对话 / 记忆 / 日记 | ✅ | ✅ 不变 |
| 记忆卡（照片 + 她的感受） | ✅ | ✅ 不变 |
| 角色卡 JSON / Markdown + 人设两段式 | ✅（有"重启退化"缺陷） | ✅ **缺陷已修** |
| 五维属性（饿/渴/心情/精力/健康） | ✗ | ✅ |
| 工作 / 玩耍 / 商店 / 嘟嘟币 | ✗ | ✅ |
| 自主需求气泡（饿/渴/困/闷） | ✗ | ✅（30 分钟冷却、免打扰时静默） |
| 状态注入 AI 语气 | ✗ | ✅（空状态逐字节不变） |
| 状态条 HUD | ✗ | ✅（三档展示位 + 可拖动 + 贴边缩回） |

