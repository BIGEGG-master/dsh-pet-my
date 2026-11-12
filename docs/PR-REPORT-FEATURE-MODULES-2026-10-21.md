# PR 报告：功能模块化先行版——14 模块激活层 +「功能」管理页（2026-10-21）

> **基线**：`1d12820`（Merge PR #316）
> **分支**：`feat/feature-modules`　**日期**：2026-10-21
> **范围**：43 个文件，+4999/−259，17 个提交（期 1–5）
> **关联**：设计 `.scratch/feature-modules/SPEC.md`；入口清单 `ENTRY-INVENTORY.md`；
> astra 架构评审（2026-10-21）；DLC 线 `docs/plugin-phase-01-foundation/PLUGIN-DLC-ARCHITECTURE.md`

## 一、核心特性

设置页与右键菜单多年累积了大量「为社区需求加的」功能，单个用户用不到这么多。
作者长期路线是真插件化（v5 DLC 线）；本 PR 是它的**先行版**：把 14 个非核心功能
做成**随包自带、勾选启用、重启生效**的内置模块——不做插件加载器、不搬代码、
不动态加载，先建「激活层」。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 模块清单 | `pet/features.py`：14 模块（天气/抽签/待办/节日/语音/音乐/AI 对话/文件解读/手动视觉/主动识屏/Agent 联动/灵动岛/快捷启动/系统工具），含硬依赖边（文件解读·识屏·视觉→AI 硬；抽签·待办·节日→语音可选增强；岛→AI/Agent 可选） |
| 2 | 激活层 | `pet/feature_activation.py`：`feature_activation` 配置键（`{"version":1,"enabled":[...]}`，None=未判定）；主进程启动早期冻结快照；设置进程按盘上待生效集合冻结 |
| 3 | 迁移 | 升级用户**继承全部模块**（内部开关一个不动，现有数据无法可靠判「没用过」）；新装默认**纯核心**（期 5，14 模块全过验收后才切的开关） |
| 4 | 「功能」管理页 | 设置侧栏第 11 域：按分类分组的卡片（徽标=联网/收费/外部程序）+ 依赖提示 + 推荐套件/全部开启/全部关闭；staged 保存，重启生效 |
| 5 | 三层门控 | 菜单投影（未激活项消失、空子菜单/分隔线自动清理、**用户自定义布局一字节不写回**）；设置层（标签/组/页不构造不写回，照常 claim 防「待分类」，空域整域隐藏）；执行层（构造前挡：不建服务、不起定时器/线程/快捷键/预缓存） |
| 6 | 历史误绑解耦 | harness 菜单可用性与自启门不再误绑 chat 回调（新立 `chat_build_capable` 构建变体真值链）；harness/dsh 归系统工具、余额归灵动岛、AI 域「助手回复朗读」归语音依赖 |

**红线 / 不变量**：行为开关语义零改动（模块激活是第二层，不与 `weather_enabled`
这类开关合并）；升级用户零行为变化；停用模块的业务数据/凭据/配置一个不删；
快照未冻结（测试/工具）一切照旧。

## 二、修改文件说明

### 实现（按期）

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/features.py` | +745（新） | 14 模块静态清单（13 字段 FeatureSpec）+ normalize_enabled + resolve_dependencies（传递闭包 blocked）+ MIGRATION_BASELINE + feature_for_action 反查；纯数据无 Qt（启动边际 ~6ms） |
| `pet/feature_activation.py` | +189（新） | 一次性迁移判定（懒落盘：只进内存草稿，不破坏「AppShell 构造前零配置副作用」启动不变量）；进程快照 is_active（未冻结恒真/未知恒真/冻结含依赖求解）；write_enabled/pending_enabled；freeze_for_settings_process（slot 实例也直读主 config.json） |
| `pet/config.py` | +14/−1 | `feature_activation` 键（默认 None；入 reload 白名单；入 _NULL_ACCEPTING_KEYS=撤成未判定） |
| `pet/app.py` | +227/−44 | 主启动链 decide_and_freeze；enable_chat=构建∧模块复合 + chat_build_capable 真值链；天气/抽签/待办/节日判据函数闸；_chime_wanted/ensure_audio_channel/_self_talk_speak_wanted/台词预缓存 voice 闸；岛不创建（≠hide）+ 余额三入口；_dsh_tracker_wanted 复合 agent_link；harness 自启归 system_tools；托盘余额/dsh 按模块挂出；快捷键 vision 双守 |
| `pet/settings_features.py` | +237（新） | 「功能」域卡片页（staged 语义、快捷按钮、依赖提示、write_to_config 未改不 set） |
| `pet/modern_settings_dialog.py` | +163/−103 | 「功能」域接线 + 侧栏行高 34→31（11 域新预算，GATES 已登记）；天气/抽签/待办/节日/语音/音乐/岛/Agent/快捷启动/视觉组按激活挂出或整页不构造，保存同步跳键；festival/voice_chime 页 is-not-None 守卫；余额组归岛、隐藏对话行判据复合 chat |
| `pet/context_menus/registry.py` | +21/−2 | available_ids 激活投影（一个点，全局生效）+ harness 可用性改 chat_build_capable |
| `pet/settings_interaction.py` | +40/−20 | 天气/趣味标签不构造；点击音效里朗读两行、点击余额行按激活挂出 |
| `pet/multi_window_shared.py` | +10/−4 | agent_link/proactive 构造前挡（None）+ stop_all/apply_config 缺席守卫 |
| `pet/window_optional_services.py` | +44/−3 | legacy 懒创建路径（file_interpret/proactive/agent_link/music）按激活返回 None |
| `pet/__main__.py` | +12/−1 | 设置进程冻结 + include_ai 复合 chat 模块 |
| 其余（overlay_shell/sprite_menu_facade/window_alerts/settings_*/festival/voice_chime/music 各页守卫） | — | 同模式守卫与接线，见各提交 |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_feature_modules_gating.py` | +2183（新） | **84 例门控三件套**：菜单投影/依赖 blocked/布局不回写/设置不出现不写回/执行零活动/快照语义/设置进程冻结/语音通道聚合/岛不创建/harness 解耦 |
| `tests/test_features.py` | +339（新） | 46 例：清单自洽（无环/依赖存在/键非空）、normalize、resolve 闭包 |
| `tests/test_feature_activation.py` | +164（新） | 18 例：迁移（新装纯核心/升级继承/slot 痕迹）、损坏保守全激活、未知 ID 留盘、合法空列表不回退、write/pending |
| `tests/test_settings_features.py` | +248（新） | 12 例：功能页 staged/取消丢弃/快捷按钮/未知 ID 保留 |
| `tests/test_config_schema.py` 等快照类 | +30 | 白名单 155→156、行数预算 2535→2666（逐次带日期校准）、_NULL_ACCEPTING_KEYS 登记 |
| `tests/test_harness_*.py` `test_sprite_menu_parity.py` | ±40 | 三个钉旧耦合（enable_chat↔harness）的测试按 chat_build_capable 新真值改写 |

### 未改动

- 菜单**编辑器**仍列全部动作（与运行菜单投影是两层；重开模块布局不丢）；
- 快捷键**绑定行**（看看屏幕/截图提问）保持可见——输入绑定不是入口，注册与回调已双守；
- 外部 Agent 桥/hook 残留不自动卸载（停用=宠端不监视/不自启，明示文案在功能卡片）；
- `dynamic_island.enabled` 缺省两处不一致未顺手修（清单陷阱已绕开，单独立项）。

## 三、实现要点

- **激活层而非插件框架**：静态清单 + 启用集合 + 三层门控 + 重启生效；
  「下次启动配置」与「本次运行快照」分开——改集合只写盘，主进程快照在创建任何
  可选服务前冻结。「未激活零活动」= 零模块定时任务/线程/网络/子进程/热键/hook，
  不承诺零 import。
- **菜单投影选点**：布局解析器原生就会丢不可用动作、丢空子菜单、规整分隔线、
  不回写用户布局——所以菜单层只改了 `available_ids` 一个点。这是全 PR 杠杆最高的
  一个发现。
- **设置层三形态**（按模块落点选）：标签级（整 tab 不构造 + save 跳过）、组级
  （照常 claim 防「待分类」、按激活挂载）、页级（整页不构造 + is-not-None 守卫）；
  空域整域隐藏（domain_content 给 None）。
- **共享语音通道**：voice 关 = `_chime_wanted` 一票否决，六消费者的「念出来」
  全部降级出文字（调用方早已 None 容忍）——不拆消费者，不动通道所有权。
- **构造前挡**：Agent/识屏的共享容器构造即 apply_config，必须 is_active 在构造
  之前判（容器成员为 None + 全部消费点缺席降级），不是建完再 stop。
- **迁移的保守原则**：只有「可能用过」的正证据、没有「肯定没用」的负证据——
  升级一律继承全集；损坏/版本不认识保留原数据 + 保守全激活；未知 ID 留盘不进
  快照；合法空列表是明确选择绝不回退。

## 四、性能分析

**方法**：offscreen 探针 + 调用计数（命令见各提交与 `.scratch/feature-modules/`）。

| 指标 | 实测 | 归属 |
|---|---|---|
| `import pet.features` 启动边际 | 冷启增量中位 **5.6ms**（n=15，dataclasses 已被核心模块加载后的增量） | 新增，启动一次 |
| `decide_and_freeze` | 读 1 个 JSON 键 + frozenset（<0.1ms）；迁移判定时一次 `config.set`（不落盘） | 新增，启动一次 |
| 菜单投影 | 每次开菜单 O(注册表数×1 次查表 + 14 项依赖求解)，微秒级 | 新增，每次菜单 |
| is_active 调用（设置页构造/保存） | 每次域装配 O(14) 依赖求解一次，微秒级 | 新增，低频 |
| 稳态线程/定时器/网络/磁盘 | **零新增**；停用模块反而是净减（服务/定时器/预缓存不建） | — |

**结论**：① 稳态开销零新增（快照是冻结的 frozenset 查表）；② 新增路径全部
一次性或用户动作级；③ 无新系统调用/网络/线程；④ 内存只减不增（停用模块的
服务对象不创建）。

## 五、实机运行记录

- **设置进程演练（真 ModernSettingsDialog + 真 Config，非 mock）**：音乐模块停
  用时三行不挂出、「音乐关联」组消失、无「待分类」、核心行在、`_write_config`
  成功且六项音乐配置原值零改写（期 3b 记录）；天气/待办/语音/岛/Agent 同口径
  84 例门控测试覆盖。
- **红绿验证（每批）**：`git stash` 产品改动后各批「停用」用例变红、「默认」
  用例仍绿——门是有效的，不是永远关。
- **实机部署验收（待 PR 构建）**：以下三项必须真机确认，已列入 PR 验收单：
  ① 功能页 UI 与勾选→重启→菜单/设置出现或消失的全流程；② vision 关 + chat 开
  时按已绑定热键，确认无采集无线程（仓内只能验到回调早退与注册表缺席）；
  ③ 停用若干模块后任务管理器实测线程/子进程数下降。
- **无法自动验证**：真机热键路径（offscreen 无全局热键）；真实音频通道释放的
  可闻验证（用服务对象不创建 + 通道判据 False 替代）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet/ tests/` | All checks passed（每批） |
| 门控套件 | `pytest tests/test_feature_modules_gating.py` | **84 passed** |
| 期 1 全量 | `pytest tests/ -q` | 8637 passed / 0 failed |
| 期 2 全量 | 同上 | 8664 passed / 0 failed |
| 期 3 全量 | 同上 | 8684 passed / 0 failed |
| 期 4 全量 | 同上 | 8721 passed / 0 failed |
| 期 5 全量（首跑） | 同上 | 88 failed —— 新装纯核心冻结污染：走 main() 的用例把进程级快照冻成 [] 不回收，污染后续设置页用例；conftest autouse 夹具全局回收（本报告期 5b 提交） |
| 期 5 复跑 | 同上 | **8721 passed / 0 failed** |
| 红绿验证 | git stash 对照（每批） | 停用用例红、默认用例绿 |

## 七、已知限制与后续

1. 真机验收三项未做（见 §五末），随 PR 构建执行；
2. 菜单编排编辑器仍列未激活模块的动作（标「所属功能未启用」是后续优化，
   不影响运行菜单）；
3. 外部 Agent 桥残留不自动卸载（设计决策，功能卡片有明示）；
4. 旧版本不认识激活层：降级后按旧行为全功能运行（回滚说明已含）；
5. 全局记忆/历史压缩是 AI 模块内部增强（设计 `.scratch/feature-modules/CHAT-GLOBAL-MEMORY.md`），
   不在本 PR；
6. 快捷键绑定行可见但无效（期 4b 裁决：绑定是输入面不是入口，与 hotkey_open_chat 同形态）。

## 八、风险与回滚

- **影响面**：14 个功能的显隐与启停判据；配置层新增一键（有迁移与 NULL 语义）；
  无持久化格式破坏、无配置键搬迁。
- **回滚**：`git revert` 后旧版不认识 `feature_activation` 键 → 全功能运行（=旧
  行为），用户数据零损失；激活集合键可留可删（显式 null = 下次重判）。
- **最坏情况分析**：门控判据全部失效（快照未冻结）时 is_active 恒 True → 行为
  与现状逐位一致——失败方向是「回到旧版」而不是「功能消失」。
