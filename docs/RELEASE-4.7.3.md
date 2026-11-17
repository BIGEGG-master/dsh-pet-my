# v4.7.3 更新日志（2026-11-16）

> 4.7.2 → 4.7.3。修两个观感问题：**睡觉姿态不再抖动/忽大忽小**，**切姿态不再硬切**。

## 一、抖动 / 放大缩小（素材层，根因是我上一版的错）

4.7.2 的转码脚本对**每一帧**单独计算缩放与偏移（`fit_placement` 按当帧包围盒算），
于是素材本身 3~6% 的呼吸起伏被逐帧"补偿"：补偿后的画面反而**逐帧跳变**，
看起来就是抖动 + 忽大忽小；再加上 `scale = min(0.5, 目标宽/帧宽)` 在边界上抖动，
个别帧会被缩小 1.6% —— 叠加起来就是用户看到的"放大缩小"。

**修法**：整段用**中位包围盒**算一次缩放/偏移，全程固定，逐帧只做粘贴：

```python
scale = min(0.5, (TARGET_W * MAX_WIDTH_PCT) / median_width)
dx = TARGET_W / 2 - median_cx * scale
dy = TARGET_H * BOTTOM_PCT - median_bottom * scale
```

修完实测（逐帧包围盒的相邻帧变化，px）：

| 片段 | 宽 | 高 | 中心X | 底边 |
| --- | --- | --- | --- | --- |
| `睡觉-主` | 平均 0.33 / 最大 3 | 平均 0.29 / 最大 3 | 平均 0.16 / 最大 1 | 极差仅 2 |

即只剩素材自身的呼吸起伏（源视频本身就是 3~6%），没有人为抖动。

## 二、过渡生硬（渲染层）

**现象**：点「去睡觉」她"啪一下"就趴下了。

**做法**：在 overlay 绘制层加 **sprite 级淡入**（`overlay_window.py`）：

- `fade_sprite_in(sprite, duration)`：记录 `(起始时间, 时长)`；
- `paintEvent` 里对淡入中的 sprite 用 `painter.setOpacity()` 绘制，其余照旧；
- 淡入期间用 `QTimer.singleShot(16ms)` 链强制重绘（sprite 停播时也能推完）。

**为什么不动 sprite 的帧**：淡入只影响绘制不透明度，不碰帧缓存、mask 与命中判定——
风险最低，也不会引入"淡入时点不到"以外的语义变化（这 0.35s 内不可交互是刻意的）。

接线：`app._on_pet_life_sleep_changed` 在「切到睡觉段 / 解除常驻」之后调用
`shell.fade_in_sprite(sprite, 0.35)`，所以入睡与醒来都是淡入。

## 三、素材重出

4 段全部按新几何重转（`out-v2`），文件名沿用 `睡觉-主 / 睡觉-备1 / 睡觉-备2 / 睡觉-备3`，
首末帧闭合度与上一版一致（主姿态 IoU 0.932，未做淡化）。

## 四、测试

- `pytest -k "overlay or sprite or pet_life or catalog"` → **1432 passed**
  （唯一 failed 是 `test_agent_settings_hot_reload`，端口探活，v4.6.0 起就有）
- 运行验证：`素材加载完成：shenshen 110 段动画`，无异常日志

## 五、回滚

- `D:\dsh-pet-dev\_backup-v4.7.3-<时间戳>\` 里的上一版 exe。
- 素材回滚：`D:\材料\gemini_睡觉\out-v2`（新版）与仓库 `assets/characters/shenshen/videos/sleep/` 对调即可。
