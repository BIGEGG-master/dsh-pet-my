# v4.7.2 更新日志（2026-11-16）

> 4.7.1 → 4.7.2。这一版把**真素材**接进睡觉姿态：用户用 AI 生成的 4 段绿幕睡觉动画
> 已转码入库，并新增「姿态专用目录」——睡觉段不再污染随机动作池。

## 一、新增 `videos/sleep/` 姿态专用目录

问题：`videos/random/` 里的每一段都会进 `acts` 随机动作池。把"躺平睡觉"丢进去，
醒着的时候也会被随机抽到——观感是错的。

做法（`pet/catalog.py`）：

| 改动 | 说明 |
| --- | --- |
| 新增 `DIR_SLEEP = 'sleep'` | `videos/sleep/**` 归为 `sleeps` 池 |
| `known` 集合加入 `DIR_SLEEP` | 该目录**不再**被塞进 `acts` 随机池 |
| 返回新增 `'sleeps'` | 与 `idles/turns/moves/clicks/acts` 并列 |

配套（`pet/sprite_behavior.py` / `pet/app.py`）：

- `_categories()` 多带一个 `sleeps` 键（不影响既有池）；
- `app.pet_life_clip_pool(cats)` 把 `sleeps` 拼在 `acts` 前面，只给"点名播放"用。

效果实测：

```
目录: click 5 / drag 1 / idle 1 / move 3 / random 89 / sleep 4 / turn 1
sleeps: ['睡觉-主', '睡觉-备1', '睡觉-备2', '睡觉-备3']
sleep 段混进随机池: []          ← 干净
pick_clip(sleep) -> 睡觉-主      ← 点名挑到新素材
兜底(无新素材时) -> 原地小憩沉眠  ← 老素材仍可用
```

## 二、素材入库（用户自制 4 段）

源：4 段 1280×720 / 24fps / 10s 绿幕 HEVC（AI 生成）→ 本机转码：

1. 绿幕键出 alpha（四角取背景色 + 色距阈值 + 绿溢抑制）
2. 构图对齐到现有口径：水平居中、**底部落在画布 92%**、宽度上限 58%
3. 缩放 640×360
4. 首尾交叉淡化（仅当首末帧前景 IoU < 0.9；0.25s）
5. `libvpx-vp9` + `yuva420p` + `ALPHA_MODE=1`，24fps

| 入库名 | 源 | 首末帧 IoU | 大小 |
| --- | --- | --- | --- |
| `睡觉-主.webm` | 55bb…mp4 | **0.914**（无需淡化） | 965 KB |
| `睡觉-备1.webm` | 34ea…mp4 | 0.52（已淡化） | 936 KB |
| `睡觉-备2.webm` | 4d27…mp4 | 0.474（已淡化） | 1434 KB |
| `睡觉-备3.webm` | 3811…mp4 | 0.00（首末完全不同） | 772 KB |

- `CLIP_POOLS["sleep"]` 首位加 `睡觉-主`，所以常驻姿态优先用它；
- 四段都在 `videos/sleep/`，**不参与随机**，也不影响既有 89 段随机动作。

## 三、工具链沉淀（本机可用）

本机的 ffmpeg 现状与解法（值得记下来，下次换素材直接用）：

| 来源 | 结论 |
| --- | --- |
| `imageio_ffmpeg` 自带 ffmpeg | ❌ 无 `libvpx`（编不了 VP9） |
| 剪映 / 游戏录像机自带 ffmpeg | ❌ 同样无 `libvpx` |
| PyAV（已装） | ✅ 有 `libvpx-vp9`，但**写 webm 会丢 alpha side-data**（输出无 `ALPHA_MODE`） |
| `@ffmpeg-installer/win32-x64`（npm，21MB） | ✅ 解压出 61MB ffmpeg，含 `libvpx-vp9`，`ALPHA_MODE=1` 正常 |

所以转码拆两步：**PyAV 解码 + 抠像 + 几何对齐 → 导 PNG 序列 → ffmpeg（npm 那个）编 VP9-alpha**。
ffmpeg 放在 `D:\材料\_tools\ff\package\ffmpeg.exe`（不进仓库）。

## 四、测试

- `pytest -k "pet_life or sprite_behavior or catalog or library or menu_parity or architecture"`
  → **325 passed**
- 新增分类字段不影响既有断言（`build_categories` 只加键，不改既有键的语义）

## 五、回滚

- 想退回"只用包里原有的打盹段"：删掉 `videos/sleep/` 目录即可，`pick_clip` 会自动回落到
  `原地小憩沉眠`（实测过）。
- 程序回滚：`D:\dsh-pet-dev\_backup-v4.7.2-<时间戳>\`。
