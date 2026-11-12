# PR 报告：恢复跨屏抛掷——抛掷边界改回 legacy band 语义（2026-10-21）

> **基线**：`913cf4f`（main）
> **分支**：`fix/cross-screen-throw`　**日期**：2026-10-21
> **范围**：2 个文件（实现 1、测试 1）
> **关联**：issue #319 评论「4.3.4 开启后可以跨屏，但是碰撞不能跨屏了，之前可以从屏幕1弹到屏幕2」

## 一、核心特性

恢复 4.2.1/legacy 路径就有的「从屏幕1弹到屏幕2」能力。根因不是新鲜回归：
4.3.2（`b7a697f`，#288）把 overlay 拓扑的抛掷反弹边界收窄为「当前所在那块屏」
（注释当场写明不恢复跨屏抛掷）——墙挡着身体、身体中心过不去、墙就永远不收，
并列双屏下抛掷被永久锁在本屏。legacy 的 #186 band 机制（`cd7821b`，今天仍有
契约测试 `test_multi_screen_interaction.py::test_throw_bounds_span_both_screens`）
从未丢失——所以用户「之前可以」的记忆来自 4.2.1/捕获模式（共创者已确认）。

修法：`sprite_physics._effective_bounds` 在多矩形 clamp 域时改用
`window_placement.band_bounds` 同款语义（纯函数复用，零新增实现）。

| # | 能力 | 说明 |
|---|---|---|
| 1 | 并列双屏跨屏抛掷 | 右墙在副屏右缘，飞行穿缝（与 legacy 逐位同语义） |
| 2 | 错位拼接仍挡空洞 | 身体带不与副屏相交时右墙仍在主屏右缘（band 十年口径） |
| 3 | 单屏/未开跨屏零变化 | 单矩形域 band 结果恒等，行为逐位不变 |

**红线 / 不变量**：`set_pos` 逐点并集钳制、拖拽跨屏、`move_sprite_to_screen`
移交逻辑全部不动；混合 DPI 多窗模式暂不支持抛掷跨屏（如实登记，见 §七）。

## 二、修改文件说明

| 文件 | 增删 | 改动意图 |
|---|---|---|
| `pet/sprite_physics.py` | +30/−11 | `_effective_bounds`：多矩形 clamp 域不再取「离身体最近那块屏」（`_clamp_domain`/`_settling_rect`），改构造 `DesktopArea` 调 `band_bounds`；新增 `_united` 小助手与 import；旧注释（「不新增抛掷能跨屏的能力」）随语义反转更新 |
| `tests/test_sprite_physics.py` | +38/−0 | 契约 ×2（先红后绿）：双屏并列域右墙在副屏右缘+穿缝不反弹；错位布局（副屏下移 520px）仍在主屏右墙反弹 |

### 未改动

- `pet/pet_sprite.py` 的 `_settling_rect`/`_clamp_domain`：贴地判据（`_at_ground`）
  与 set_pos 钳制仍需要「最近一块屏」口径，只有抛掷反弹边界换语义；
- 多窗（混合 DPI）模式：见 §七。

## 三、实现要点

死锁结构：旧实现边界每 tick 取「离身体中心最近的那块屏」，身体中心不过缝墙
就永远在原屏。band 语义把边界改成「与身体 x 带相交的屏的左右并集、与 y 带
相交的屏的上下并集」——并列双屏恒等于两屏包围矩形（右墙在副屏右缘），错位
拼接收窄到真实存在的屏带（挡住建模外空洞）。`band_bounds` 是
`window_placement.py` 的纯函数，坐标系无关，clamp 域与身体框同在 overlay
局部坐标，直接复用；单矩形域 band 结果恒等于该矩形，故单屏路径零差异。

## 四、性能分析

**方法**：每 tick 每 thrown sprite 一次边界计算，对照旧实现（同样每 tick 一次）。
`_effective_bounds` 新增成本 = 一次 `O(屏数)` 的带计算（≤4 次矩形比较）+ 一次
`O(屏数)` 的包围矩形求并——与旧的 `_settling_rect`（同阶 O(屏数) 最近屏搜索）
同量级，实测 31 个物理用例总耗时与基线无差（3.24s vs 基线 3.2s 档）。
无新线程/网络/磁盘/系统调用；无内存增长。

## 五、实机运行记录

- **根因现场**：issue #319 评论原文「4.3.4开启后可以跨屏，但是碰撞不能跨屏了，
  之前可以从屏幕1弹到屏幕2」；调查报告（2026-10-21，k3 代理 + git log -S 证据）
  定位收窄点为 `b7a697f`，legacy 能力存活于捕获模式（契约测试为证）；
- **用户环境吻合**：报告者拖拽正常（拖拽不走物理边界）、只有抛掷被堵——与
  `_effective_bounds` 单点收窄完全一致；
- **用户可见行为**：修复后并列双屏从屏1甩出可飞入屏2（契约测试等价场景，
  右墙=副屏右缘-身宽）；真机双屏抛掷观感随 PR 构建由共创者复核；
- **无法自动验证**：混合 DPI 真双屏的跨窗飞行（需 150%/100% 实机，登记 §七）。

## 六、测试与验证

| 门 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `ruff check pet/sprite_physics.py tests/test_sprite_physics.py` | All checks passed |
| 契约（先红后绿） | `pytest tests/test_sprite_physics.py -k "multi_rect_domain or staggered_hole"` | 红 1/绿 1 → 全绿 |
| 物理族 | `pytest tests/test_sprite_physics.py` | 31 passed |
| 相关族 | multi_screen/throw/sprite/overlay_hosts/collision/screen_host 等 8 文件 | 242 passed |
| 全量 | `pytest tests/ -q` | 8566 passed / 1 failed（唯一红 = `test_every_group_has_a_description`，main 上 #316 遗留，与本改动无关，已由 `913cf4f` 修复） |

## 七、已知限制与后续

混合 DPI（任一屏缩放 ≠100%）走多窗模式（每屏一张窗），抛掷跨屏需要跨窗
飞行（活动区临时放宽 + 投影 + 换窗接管），依赖实机验证，**本期不做**——
单窗（同 DPR）场景即报告者环境。后续若做，验收基准同 legacy。

## 八、风险与回滚

影响面：overlay 拓扑 thrown 态的反弹边界；无配置/持久化变化。
回滚 `git revert` 即回到「锁本屏」语义，无残留状态。
