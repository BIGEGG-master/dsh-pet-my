# PR 报告：AI 对话全局记忆（档 A：手动钉记忆）2026-10-22

> **基线**：`e80c31f`（feat/feature-modules 期 4 门控修正，test(features)）
> **分支**：`feat/chat-memory`　**日期**：2026-10-22
> **范围**：14 个文件（实现 9、测试 4、文档 1）
> **关联**：设计稿 `.scratch/feature-modules/CHAT-GLOBAL-MEMORY.md`（档 A 先行）；
> 存储纪律照抄 `pet/proactive_memory.py` 的三层锁模式（主动识屏陪伴记忆）

## 一、核心特性

会话间零记忆：每个会话独立，`build_messages` 只截断不压缩，用户每开一轮新对话
都要重新自我介绍。本 PR 落地设计稿档 A（零 LLM 成本、完全可审计）：

| # | 能力 | 说明 |
|---|---|---|
| 1 | 「记住：……」指令 | 对话输入以「记住：」/「记住:」（中英文冒号）开头时不发网络，写入全局记忆并回一条确认气泡；指令与确认都入会话记录（user + assistant），落盘后随历史参与后续对话 |
| 2 | 气泡「钉为记忆」 | modern 窗气泡工具条新增图钉按钮；legacy 窗镜像为气泡右键菜单「钉为记忆」；`source="manual"`，重复钉同一文本按文本去重（updated_at 刷新 + hits+1，不新增条目） |
| 3 | system 注入 | `PromptBuilder.build_messages` 新增 `memory_text` 参：system 最末（time_context 之后）追加「关于用户的记忆」段，条列、硬字符上限 1200，超出按 hits 高 → 最近更新截 |
| 4 | 设置「记忆」组 | 「AI 与对话」域新增组：`chat_memory_enabled`（默认开，只管注入）+ 记忆管理对话框（查看 / 单条删除 / 全部清空，清空走确认） |

**红线 / 不变量**：无记忆 / 关开关时 `build_messages` 输出与现状逐字节一致
（`test_build_messages_byte_identical_without_memory` 参数化钉死）；存储纪律与
proactive_memory 完全一致——「读不到」≠「没有条目」，读失败时写链放弃修改，
绝不把只含新条目的快照盖到盘上旧记忆头上。

## 二、修改文件说明

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/chat/memory.py` | +352 / −0（新增） | `ChatMemory` 存储（条目结构 `{id,text,source,created_at,updated_at,hits}`，100 条 / 4000 字符 / 单条 500 上限，超限按 hits 少 + 最老淘汰，新条目受保护）；三层锁直接复用 `proactive_memory` 的进程内锁表与 `<name>.lock` 约定（不新造轮子）；`parse_remember_command`（指令解析，空正文与"非指令"严格区分）；`render_injection`（hits 高 → 最近更新选取，硬上限截断）；`injection_text`（开关 + 按角色读盘的总入口）；`memory_path`（经 SessionStore 继承实例后缀目录） |
| `pet/chat/prompt.py` | +6 / −2 | `build_messages` 新增 `memory_text=None` 参；非空才在 system 末尾追加并 strip，None/空串/纯空白一律不追加（逐字节回归钉的前提） |
| `pet/chat/widgets.py` | +65 / −1 | modern 窗：`MessageBubble.pin_requested` 信号 + 工具条图钉按钮（`_add`/`_prepend` 都接线，历史气泡同样可钉）；`send_message` 指令拦截（先于附件处理，指令路径清输入与附件、不入网）；`_handle_remember_command`（确认气泡 + 原子 append_messages 落会话）；`_pin_bubble`（反馈走 composer 提示条，不弹窗）；`_begin_generation` 传 `memory_text=self._memory_injection()` |
| `pet/chat/legacy_widgets.py` | +84 / −1 | legacy 镜像：气泡存 `_raw_text` + `content` 属性（assistant 气泡渲染成 HTML 后原文不可恢复，钉记忆必须用源码）；右键菜单「钉为记忆」；composer `_flash_hint`；指令拦截与注入接线同 modern |
| `pet/chat/ai_settings_page.py` | +142 / −1 | 「记忆」组两个 SettingRow（`chat_memory_enabled` 开关 + `chat_memory_manage` 按钮，行建在 AI 页上随 chat 模块存在）；`save()` 写回开关；`ChatMemoryDialog`（列表 / 单条删除 / 全部清空走 `QMessageBox.question` 确认；每次操作从盘上重读重排——设置页常是独立进程） |
| `pet/chat/session_store.py` | +5 / −1 | **自审查出的真实缺陷**：memory.json 与会话文件同目录，`list()` 的 `*.json` glob 会把它收进去、`load()` 按会话解析失败（缺 `session_id`）后**当损坏会话改名** `.corrupt-<ts>.json`——记忆文件直接消失。修复 = glob 处按文件名跳过（注释说明为什么），回归测试 `test_memory_file_is_never_listed_or_renamed_as_session` 钉死（已用「直接 load 该文件会被改名」验证断言能区分新旧实现） |
| `pet/config.py` | +2 / −0 | `_initial_data` 新增 `chat_memory_enabled: True`；reload 白名单登记（非 NULL 接受键：盘上显式 null 不采纳） |
| `pet/modern_settings_dialog.py` | +3 / −0 | AI 域 claim 装配新增「记忆」组一行 + 门控注释两行（行不进 claim 会掉「待分类」；组随 chat 模块挂出，域本身已按 `include_ai` 门控，不另加闸） |
| `pet/settings_page_guide.py` | +1 / −0 | `SECTION_GUIDE` 补「记忆」组描述（页头跳转条的覆盖率守卫 `test_every_group_has_a_description` 要求每个可见组都有描述，缺了即红——settings 族复跑时抓到） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_chat_memory.py` | +560 / −0（新增） | 40 项：存储往返 / 去重 hits / 空文本拒收 / 条目数与字符双上限淘汰 / 损坏 JSON 降级空 / 读失败不写回空快照 / 跨进程锁互斥与双实例交错写 / remove / clear / memory.json 不被会话列表收走或改名；指令解析参数化 9 例；注入渲染（头部、上限、hits 优先、按角色隔离）；build_messages 注入与逐字节回归；modern/legacy 指令与钉记忆端到端（mock `service.send` 证明零网络）；真实发送路径注入 + 关开关逐字节基线；设置组写回 / reload 采纳与 null 不采纳 / claim 装配防「待分类」/ 管理对话框删与清空确认 |
| `tests/test_config_schema.py` | +3 / −0 | 白名单快照 +1（chat_memory_enabled），带日期注释，白名单 157 |
| `tests/test_chat_subsystem.py` | +6 / −3 | 工具条断言按产品意图更新为 pin + copy（测试名同步改为 `_pin_and_copy`，原名 `copy_only` 已与事实不符） |
| `tests/test_architecture.py` | +1 / −1 | modern_settings_dialog.py 行数预算 2666 → 2669（AI 域「记忆」组装配 +3，按文件约定随实测校准、带日期注释） |

### 未改动（有意）

- `pet/quick_chat.py` / `pet/file_interpret.py`：也用 `build_messages`，但档 A 范围
  只挂两个完整聊天窗；`memory_text` 缺省 None，这两处输出逐字节不变。
- 档 B（LLM 自动抽取、`chat_memory_auto_extract` 键）：设计稿明确档 A 先行，
  本 PR 不含任何自动抽取代码。
- 历史压缩：设计稿 §6 已裁定不做。

## 三、实现要点

- **锁的复用而非复制**：进程内宽锁/窄锁表与锁文件路径约定直接 import 自
  `pet/proactive_memory.py`（`_lock_for` / `_io_lock_for` / `lock_path_for` /
  `DEFAULT_LOCK_TIMEOUT_MS`），`ChatMemory` 只实现自己语义的 读→改→写。三条
  读路径只拿窄锁（注入读在 GUI 线程，实测 1.9ms），写路径才进宽锁 + QLockFile。
- **淘汰受保护条目**：`_enforce_limits` 的候选排除刚加入的条目（单条已截 500
  字符，必然装得进 4000 预算），循环可证终止；同 hits 并列时按 created_at 最老
  先走，与「hits 少 + 最老淘汰」逐字对齐。
- **hits 语义**：首次钉 = 1，重复钉 +1；注入不自动加 hits（档 A 无隐式写）。
- **确认气泡的会话落盘**：复用 `store.append_messages` 的原子「读-追加-提交」，
  与 send_message 同款的 absorbed 处理（另一前端写入时整页重载），不发明第二套。
- **legacy 气泡补 `_raw_text`**：assistant 气泡 body 是渲染后的 HTML，钉记忆
  若取 `body.text()` 会把 HTML 钉进去；与 modern 气泡一样存源码。

## 四、性能分析

**方法（可复现）**：`python <内联脚本>`（ChatMemory 满 100 条，n=300 循环计
`time.perf_counter` 均值）　环境：Windows 11 / Python 3.13.7 / PySide6 6.11.2

| 指标 | 实测 | 归属 |
|---|---|---|
| 满 100 条 memory.json 体积 | 30,773 字节（JSON 缩进开销，正文 ≤4000 字符有硬上限） | 新增 |
| `injection_text`（读盘 + 选取 + 渲染） | 1.888 ms/次（n=300） | 新增，每轮发送一次（GUI 线程） |
| `add` 重复钉（读-改-写全链，含跨进程锁 + fsync + 原子替换） | 21.966 ms/次（n=300） | 新增，仅用户主动钉/指令时触发 |

**结论**：① 稳态开销：关开关 / 无记忆时注入返回空串前只有一次 dict.get +
一次布尔判断，`build_messages` 输出逐字节不变——零新增成本；② 新增路径成本：
注入读 ~1.9ms/轮发送，与 proactive_memory 的 latest() 同量级（同为窄锁小文件
读），不占宽锁不被写者拖住；写入 ~22ms 只在用户点击/指令时发生，无后台周期
触发；③ 新系统调用：无网络、无线程、无定时器；磁盘为每角色一个小 JSON +
旁路 `.lock`（与会话文件同目录）；④ 内存：条目常驻内存 ≤100 条 × 500 字符，
无缓存增长。

## 五、实机运行记录

- **真实 system prompt 注入形态**（本机临时目录跑通 ChatMemory.add ×3（含一次
  重复钉）→ injection_text → PromptBuilder.build_messages，非 mock）：

  ```
  你是一只可爱的桌面宠物，请用自然、友善的中文和用户交流。

  【时间信息】当前时间：2026-10-21 周三 11:55。……

  【关于用户的记忆】以下是你记住的关于用户的事，回答时自然地参考这些偏好与事实；不要在回复里逐字复述这份清单。
  - 我不吃辣
  - 我周三下午有课
  ```

  落盘的 memory.json：重复钉的那条 `hits: 2`、`updated_at` 晚于 `created_at`，
  另一条 `hits: 1`（原始输出见工作记录）。
- **用户可见行为确认（offscreen 真实组件，非 mock UI）**：modern 窗输入
  「记住：我不吃辣」→ `service.send` 零调用、会话落 user+assistant 两条、末尾
  气泡为确认；点气泡图钉 → memory.json 出现 `source="manual"` 条目，再点一次
  hits 变 2 不新增；legacy 窗右键菜单同路径验证。设置对话框真实装配：两行挂在
  「AI 与对话」域页、「记忆」组标题在、无「待分类（开发期）」。
- **边界与失败路径实机观察**：持 `QLockFile` 占住旁路锁后另一实例 `add` 返回
  None 且盘上无文件（不无锁写）；损坏 JSON → `load()` 空且 add 后可重建；
  `_retry_with_narrow_lock` 注入 OSError(28) → add 放弃修改、盘上旧记忆原样。
- **无法自动验证的能力**：真实模型端「看到记忆后回答是否更贴」属模型行为，
  不在本机可验证范围；视觉样式（图钉按钮 hover 态、管理对话框排版）未截图
  核对——沿用既有 `_chat_tool_button` / 设置页 ghost 按钮样式，无新增视觉语言。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check <全部改动文件>` | All checks passed |
| 聚焦 | `pytest tests/test_chat_memory.py -q` | 40 passed |
| 架构红线 + 模块门控 | `pytest tests/test_architecture.py tests/test_feature_modules_gating.py -q` | 100 passed |
| 回归族 | `pytest tests/ -k "chat or prompt or config_schema or session_store" -q` | 574 passed, 2 skipped |
| settings 族 | `pytest tests/ -k "settings and not chat" -q` | 878 passed + 1 failed（「记忆」组漏登记 SECTION_GUIDE 描述，补上后 `test_settings_page_guide.py + test_settings_copy_lint.py` 36 passed） |
| 断言有效性 | 直接 `store.load("memory", …)` 复现修复前行为：memory.json 被改名 `.corrupt-<ts>` | 已验证新测试能区分新旧实现 |
| 全量 | 未跑（聚焦 + 相邻域族已覆盖改动面；行数预算/打包守卫含在 architecture 门内） | — |

## 七、已知限制与后续

- 档 B（自动抽取）未做：注入段 `source` 字段已预留 `manual|auto` 区分，管理
  对话框未按 source 分列（档 A 只有 manual）。
- 快速对话（quick_chat）与文件解读不带记忆（有意未挂，见「未改动」）。
- 真实模型端效果与视觉像素核对未验（见 §五末条）。

## 八、风险与回滚

- 影响面：两个聊天窗发送路径（多一个前缀判断 + 一次 1.9ms 读盘）、system
  prompt 多长一段（有 1200 字符硬上限）、设置 AI 域多一组两行。
- 开关：`chat_memory_enabled=False` 即回到逐字节基线；删除 `sessions/<角色>/memory.json`
  即清空全部记忆（设置里有确认入口）。
- 配置迁移：新增 1 键（默认 True，非 NULL 接受），无迁移逻辑，旧配置加载即得默认。
- 回滚：`git revert` 后残留仅为各角色 `memory.json`（不再被读取）与配置键
  （不在白名单即不再采纳），无结构迁移、无密钥、无打包清单变化。


---

# 第二轮：档 B —— 回复后自动提炼记忆（静默，默认开）2026-10-22

> **基线**：`84f81c9`（merge 接入 feat/feature-modules，行数预算合并校准 2676）
> **分支**：`feat/chat-memory`　**提交**：本章节对应 `feat(chat): 记忆档 B——回复后被动静默自动形成（默认开）`
> **背景**：共创者产品反馈——记忆应该是**被动的、静默的自动形成**，档 B 升为主路径、
> 默认开启；档 A（「记住：」指令 + 气泡钉）保留不删。

## 一、行为与红线

每轮助手回复完成（`ChatService._finished`，三个对话前端共用的点）后，后台线程做一次
「记忆提炼」：本轮用户+助手文本（各截 1000、合计 ≤2000 字符）+ 现有记忆
（`render_injection`，≤1200 字符）→ 同一 provider 的轻量**非流式**小请求
（`stream:false / max_tokens:512 / temperature:0.2 / thinking 强制关闭`）→ 严格 JSON
操作列表 → `ChatMemory.apply_ops` 本地合并，新条目 `source="auto"`。

**红线**：静默——无气泡、无系统通知、不打断/不延迟正常回复；提炼失败只写日志；
任何异常绝不抛出到对话路径（调度侧与线程入口双层兜底，测试用「hook 直接 1/0」
与「provider 双侧炸穿」钉死）。护栏：①用户文本有效字符 <4 跳过；②30 秒限频
（按记忆文件路径，进程内 monotonic）；③`chat_memory_enabled` /
`chat_memory_auto_extract` 任一关 = 不发；④chat 模块未激活（`is_active` 既有口径）
= 不发。合并护栏：按文本归一去重（与档 A 同源，manual 条目被自动重申不改来源）、
FORGET 未命中忽略、UPDATE 未命中按 ADD。

## 二、修改文件说明（本轮）

### 实现

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/chat/memory_extract.py` | +213（新增） | 提炼调度与执行：`schedule_extraction`（同步护栏 µs 级，后台 daemon 线程）；`parse_ops`（整串 JSON → 首 `[` 末 `]` 截取兜底 → 逐项校验 op/text，超预算按无操作）；`_complete`（优先 provider 既有 `_complete_json`——联网检索同款非流式路径，没有则 drain `stream()`，**不新建网络层**）；提炼 prompt（system 规则 6 条 + user 模板） |
| `pet/chat/memory.py` | +82/−6 | `ChatMemory.apply_ops`：一批操作一次 读→改→写（同一宽锁+QLockFile，一次落盘）；`_enforce_limits` 的 protected 泛化为元组（多新条目场景） |
| `pet/chat/service.py` | +17/−2 | `ChatService` 增 `memory_extract_hook` 属性与 `_maybe_extract_memory`：send 时记录本轮最后一条纯文本用户消息 + ProviderConfig，`_finished` 发完信号后同步调 hook（hook 异常只写日志）；三前端共用、零 UI 依赖 |
| `pet/chat/widgets.py` / `legacy_widgets.py` / `pet/quick_chat.py` | +9×3 | 三前端构造后挂 `memory_extract_hook = self._schedule_memory_extract`（闭包取当前 character——切角色后下一次 finished 用新路径） |
| `pet/config.py` | +2 | `chat_memory_auto_extract: True`（默认开：被动形成）+ reload 白名单 |
| `pet/chat/ai_settings_page.py` | +22 | 「记忆」组新增「自动整理记忆」开关行（文案如实写「会多用一点模型调用」）+ save 写回；`ChatMemoryDialog` 每条加来源徽标（自动/手动） |
| `pet/modern_settings_dialog.py` | +1/−1 | 「记忆」组 claim 清单加 `chat_memory_auto_extract`（行数不变，预算 2676 不动） |

### 测试

| 文件 | 增删 | 覆盖 |
|---|---|---|
| `tests/test_chat_memory_extract.py` | +403（新增） | 32 项：parse_ops 合法/混杂/围栏/坏输入参数化/未知 op/数量与文本截断；apply_ops 六种合并语义 + source 保持；护栏短文本参数化 6 例/限频（monotonic 拨快）/双开关/chat 模块未激活；静默（provider 炸穿不抛 + caplog、hook 1/0 不妨碍 finished 发出）；异步端到端（慢 fake provider 堵在事件上，断言回复先完成、memory.json 后落 auto 条目）；气泡/通知与关闭基线逐调用对比 |
| `tests/test_chat_memory.py` | +8/−3 | 设置组测试补 auto_extract 写回与重开读回；claim 测试补新行 |
| `tests/test_config_schema.py` | +3 | 白名单快照 +1（chat_memory_auto_extract），带日期注释，白名单 158 |

### 未改动（有意）

- 提炼只在「回复完成」触发：「记住：」指令路径本就不发请求，不会再被提炼一遍。
- 「清空自动记忆」按钮：规格明确预留——`source` 字段与管理对话框徽标已就位，
  `apply_ops(FORGET)`/按 source 过滤是现成数据面，UI 按钮下轮再加。
- 多模态消息（图片附件）不参与提炼（content 非 str 即跳过）。

## 三、实现要点

- **为什么 hook 挂在 ChatService 而不是三个前端各自 _finished**：规格指定的共用点
  就是它——三前端的 finished 处理各不相同（打字机/legacy/快速气泡），但
  `service._finished` 只有一个；hook 拿到的是 service 自己的 provider 与本轮
  ProviderConfig（api_key 已 resolve），前端只补 config/角色/路径上下文。
- **UPDATE 与 ADD 同构**：条目模型里没有「新文本」字段，UPDATE 命中 = 重申
  （hits+1 + updated_at），未命中按 ADD——与规格逐字一致，实现上共用一条路径。
- **限频键是文件路径不是角色**：多实例/多角色天然隔离（路径不同），进程内
  monotonic 不落盘（限频是成本控制，不是数据完整性）。
- **解析预算**：响应截读 4000 字符，ops ≤8 条、单条 ≤200 字符——模型输出失控
  时本地成本有界。

## 四、性能分析（本轮）

**方法**：内联脚本，Windows 11 / Python 3.13.7，满 100 条记忆文件。

| 指标 | 实测 | 归属 |
|---|---|---|
| finished 同步护栏段（限频命中，第二发起） | 8.5 µs/次（n=2000） | 新增，每轮回复一次 |
| `apply_ops` 8 条合并（读-改-写一次落盘） | 22.056 ms/次（n=50） | 新增，仅后台线程 |
| `parse_ops` | 3.11 µs/次（n=2000） | 新增，仅后台线程 |
| 提炼网络请求 | 每轮回复最多 1 次（30s 限频 + 短文本跳过），非流式、max_tokens 512、thinking 关闭 | 新增，后台线程，对话路径零等待 |

**结论**：① 稳态开销：对话路径只多一次 µs 级护栏检查；② 新增路径成本集中在
后台线程，触发频率有限频硬上限（2 次/分钟/角色封顶）；③ 新系统调用：每轮一次
daemon 线程 + 一次复用既有 provider 的非流式请求，无新网络层/定时器/磁盘 watcher；
④ 内存：提炼消息体 ≤3.2K 字符（2000 对话 + 1200 记忆 + prompt 骨架），响应截读 4K。

## 五、实机运行记录（本轮）

- **静默异步端到端**（offscreen 真实 ChatWindow + QThread worker，fake provider
  主回复秒回、提炼堵在事件上）：提炼线程已起且卡住时，`service.busy is False`、
  助手消息已落会话、memory.json 尚不存在；放行后落 `source="auto"` 条目。
- **气泡/通知对比**：开启提炼完整一轮与关闭基线的 `set_chat_status`/系统通知调用
  序列逐一相等，`show_bubble` 零调用。
- **异常路径**：provider `_complete_json` 与 `stream` 双侧炸穿 → 线程只写
  「记忆提炼失败（已静默）」日志，对话路径无感；hook 直接 `1/0` → `finished`
  信号照常发出（性能实测脚本里一次 provider_config=None 的后台炸穿也被同一
  兜底正确接住，顺带实测了这条路径）。
- **提炼 prompt 实样**（真实 render_injection + 模板拼装）：

  ```
  【system】你是记忆整理助手。从「用户和桌宠的一轮对话」中挑出值得长期记住的关于用户的事实
  （偏好、习惯、明确说过的个人信息、约定），输出严格的 JSON 操作列表。
  规则：1. 只输出 JSON 数组本身，不要输出任何其它文字、解释或 Markdown 代码围栏。
  2. 每条操作形如 {"op":"ADD","text":"..."}；op 只能是 ADD / UPDATE / FORGET。
  3. 只记关于「用户」的长期事实；寒暄、闲聊、一次性请求、关于桌宠的事实都不记。
  4. text 是一句简短的第一人称陈述（与已有记忆风格一致，如「我不吃辣」），不超过 50 字。
  5. 已有记忆里已有同义事实时不要重复 ADD；事实有变化用 UPDATE；用户明确表示「别记了 / 忘掉」
     用 FORGET（text 填要删掉的那条已有记忆）。6. 没有值得记住的内容时，输出 []。
  【user】
  【本轮对话】
  用户：我不吃辣，而且周三下午都有课，晚上吃什么好？
  桌宠：那今晚试试清汤菌菇锅？周三下课回来正好吃。

  【已有记忆】
  【关于用户的记忆】……
  - 我不吃辣

  请输出记忆操作 JSON 数组。
  ```

  模型输出（含围栏的容错形态）→ `parse_ops`：`[{'op':'ADD','text':'我周三下午有课'},
  {'op':'UPDATE','text':'我不吃辣'}]`。
- **无法自动验证的能力**：真实模型提炼质量（哪些事实该记）属模型行为；设置页
  新开关与来源徽标的像素核对未做（沿用既有 ToggleSwitch/ghost 样式）。

## 六、测试与验证（本轮）

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet/ tests/test_chat_memory*.py tests/test_config_schema.py` | All checks passed |
| 聚焦 | `pytest tests/test_chat_memory_extract.py -q` | 32 passed |
| 档 A + schema + 架构 | `pytest tests/test_chat_memory.py tests/test_config_schema.py tests/test_architecture.py -q` | 124 passed（行数预算 2676 未动） |
| 回归族 | `pytest tests/ -k "chat or memory or config_schema" -q` | 732 passed, 3 skipped |
| 门控 + 页指南/文案 | `pytest tests/test_feature_modules_gating.py tests/test_settings_page_guide.py tests/test_settings_copy_lint.py -q` | 125 passed |

## 七、已知限制与后续（本轮）

- 「清空自动记忆」按钮未加（数据面已预留 source 过滤）。
- 提炼质量依赖模型：小模型可能记废话或不记——限频 + 预算把成本钉住，质量
  迭代只动 prompt（`_EXTRACT_SYSTEM` 一处）。
- 限频是进程内口径：重启后 30s 窗口重新计（可接受，提炼本身幂等去重）。

## 八、风险与回滚（本轮）

- 影响面：每轮回复后多一个后台小请求（默认开）；关掉 `chat_memory_auto_extract`
  即回到档 A 行为，关掉 `chat_memory_enabled` 连注入一起停。
- 配置迁移：新增 1 键（默认 True，非 NULL 接受），白名单 158。
- 回滚：`git revert` 后 auto 条目保留在 memory.json（source 可辨识，管理对话框
  可见/可删），无结构迁移。
