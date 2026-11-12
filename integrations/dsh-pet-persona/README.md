# dsh-pet-persona

把插件里的**角色卡**（`pet-pack/skins/feiyu-*/persona.md` 的人设 + 口吻）应用到独立版桌宠。

独立版没有第二套立绘（webm 视频驱动），所以迁移的是角色卡层：

| 桌宠字段 | 取值 |
| --- | --- |
| `chat.default_system_prompt` | 小肥鱼人设正文 |
| `character_aliases.<角色>` | `小肥鱼` |
| `dialogue_mode` | `custom` |
| `dialogue_phrases` | 30 组事件台词（本鱼口吻，保留 `{name}/{sessionName}/{tool}` 等占位符） |

## 文件

- `feiyu.persona-card.json` —— 角色卡源（人设、口头禅、台词）
- `apply_persona.py` —— 应用 / 回滚 / 打印模板
- `feiyu.persona-phrases.json` —— 生成物，标准 `persona-phrases/v1`，可在设置页「导入模板」复用
- `backups/` —— 每次应用前的 config 快照

## 命令

```
python apply_persona.py            # 应用（自动备份）
python apply_persona.py --revert   # 回滚到最近一次备份
python apply_persona.py --print    # 只打印 persona-phrases/v1 模板
```

## 注意

- 写的是桌宠的 `config.json`，和设置页改的是**同一份文件**；请在桌宠退出时运行，
  否则它退出时会把内存里的配置写回。
- 只有独立版真实存在对应素材的角色 id 才能挂别名（当前是 `shenshen`）。
- 应用后 `dialogue_mode` 变成 `custom`；以后在设置页切换模式会覆盖这套台词。
