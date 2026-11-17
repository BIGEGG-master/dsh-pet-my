# v4.7.1 更新日志（2026-11-16）

> 4.7.0 → 4.7.1。这一版把**睡觉**做成两件事：
> ① 一个真正的生活动作（去睡觉 → 到点醒来恢复精神）；
> ② 一个**常驻姿态**（睡着就躺在那儿，不再"打一次哈欠继续乱走"）。

## 一、睡觉成为一个生活动作

| 项 | 值 |
| --- | --- |
| 睡多久 | `NAP_MINUTES` = **30 分钟** |
| 醒来给多少 | `NAP_ENERGY` = **精神 +40** |
| 提前叫醒 | 按**实际睡的比例**结算（睡一半 = +20） |

- 入口三处：右键「嘟嘟的生活 → 去睡觉 / 叫醒她」、面板「生活 → 睡觉」、愿望（喊困时仍会自己睡）。
- 拒绝条件与工作/玩耍同源：养成关闭、病倒（要先吃东西）、正在干活（先停下）、已经在睡。
- **精力见底的自动睡照旧保留**（≤15 入睡、≥70 醒）：那是"她撑不住了"，主动小睡是"你让她去睡"，
  两者收益路径不同——自动睡按 `SLEEP_PER_HOUR` 慢回，主动小睡到点一次性结算。
- 为什么不做"睡到精力满"：那等于一个免费满血按钮，精力就不再是资源了。固定时长 + 固定收益，
  与"工作 10 分钟赚 N 币"对称。

## 二、睡觉姿态常驻（核心改动）

**改之前**：`switch_clip` 的语义是"一次性插播，播完回掷骰链"。所以睡着时会播一段打瞌睡，
然后照常待机、乱走、随机蹦动作——v4.6.0 报告里把这条列为"已知限制"。

**改之后**：睡着时那一段**一直播着**。

| 层 | 改动 |
| --- | --- |
| `pet/sprite_behavior.py` | 新增 `hold_clip_provider`（签名 `callable(sprite) -> str \| None`，默认 `None` = 行为逐字节不变）、`_continue_hold()`（ACTS 播完原地续播，排在 gap/掷骰之前）、`_roll_next()` 开头的 hold 闸门（待机播完/移动播完/预测落空都回到姿态）、`release_hold()`（醒来腾挪回待机） |
| `pet/overlay_shell.py` | `set_sleep_hold_provider()` + `_pet_life_hold_clip()`：在 `_wire_host` 里一行接上（与唱歌续播 `sing_continue_provider` 同款注入形态） |
| `pet/pet_life_service.py` | 新增 `sleep_changed = Signal(bool)`；`apply_tick` 的 slept/woke 各发一次，启动首拍也发（关机期间可能已经睡了） |
| `pet/app.py` | 接 `sleep_changed`：睡着立刻切入姿态、醒来立刻 `release_hold`；`pet_life_sleep_clip(sprite)` 提供判据（**带缓存**，行为层每帧都会问一次） |

三个设计取舍：

1. **不借 `no_move`**：那个开关每次 `_sync_sprite_settings` 都会被 cfg 覆盖，用它禁走会在配置同步后立刻失效。
2. **判据是逐只的**（`provider(sprite)`）：主宠在睡，副宠不该跟着躺下。
3. **判据坏了只表现为"不常驻"**：provider 抛异常一律当 `None`，退回既有掷骰链——附加能力绝不能反过来把动画链弄断。

## 三、界面

- **面板**：新增「生活」分组 → 睡觉行（睡着时按钮变「叫醒她」）；状态行显示「正在小睡（还有 X 分钟）」。
- **状态条**：睡着显示「小睡 N 分」（带倒计时），自动睡显示「睡觉中」。
- **菜单**：右键「嘟嘟的生活」多一项，按状态显示「去睡觉 / 叫醒她」。
- **AI 注入**：小睡时把「她正在小睡（定了时间的觉）：说话含糊、声音轻，会想接着睡」写进表达要求。

## 四、素材：怎么做一段睡觉动画

规格与现有 106 段一致（探测自 `原地小憩沉眠.webm`）：

```
vp9 (Profile 0) + ALPHA_MODE=1 · 640×360 · 24fps · 约 10s · ~345 kb/s
```

- 绿幕源视频：纯 `#00FF00`、人物不出画（头顶 ~15%、脚底 ~10%）、**首尾帧闭合**（它要循环播）
- 命名带「睡」（如 `蜷缩入睡.webm`），放 `assets/characters/shenshen/videos/random/`
- 两处都要放：源码目录 + `D:\dsh-pet-dev\_internal\assets\characters\shenshen\videos\random\`
- 关键词池 `CLIP_POOLS["sleep"]` 已补宽关键词「睡」，新素材命名能直接命中
- 转码：本机 `imageio_ffmpeg` 的 ffmpeg **不含 libvpx-vp9**，但项目 `.venv` 已装 PyAV（含 `libvpx-vp9`），
  用它做"抠像 → 640×360 → 24fps → VP9 alpha"即可

## 五、测试

新增 24 项（全绿）：

- `tests/test_pet_life_sleep.py`（16）：小睡设置/拒绝条件、到点结算、期间不按小时回血、
  提前叫醒按比例、`nap_remaining`、`flags.napping`、`normalize` 兜底、注入文案；服务层信号与落盘/跨重启
- `tests/test_sprite_hold_clip.py`（8）：常驻续播不掷骰、别的动画播完回到姿态、无判据时行为不变、
  `release_hold`、判据抛异常/返回空串的安全降级、判据能看见 sprite（逐只）

回归：`test_pet_life*`、`test_sprite_behavior`、`test_sprite_acts_tail`、`test_sprite_idle_tail`、
`test_sprite_animation_gap`、`test_sprite_menu*`、`test_autostart` 共 306 项全绿；
动画/菜单/养成相关大盘 1828 项，仅 1 项既有红点（`test_agent_settings_hot_reload`，端口探活，与本次无关）。

## 六、兼容与回滚

- 旧 `config.json` 缺 `nap_started_at` / `nap_until` → 按 0 补齐，不影响既有存档。
- 想彻底关掉睡觉姿态：`pet_life_sleep_clip` 挑不到素材名时会静默不常驻（把素材移走即可），
  不需要改代码。
- 回滚程序：`D:\dsh-pet-dev\_backup-v4.7.1-<时间戳>\`。
