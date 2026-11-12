# dsh-pet-memory-bridge

把 **DSH 桌宠插件（dsh-pet）的对话记忆**接进独立版桌宠的四层记忆，并把桌宠侧沉淀的
记忆反向导出成 DSH 可读的文本。

## 文件

| 文件 | 作用 |
| --- | --- |
| `memory_bridge.py` | 核心：定位目录、转换、去重、加锁、原子写、导出；也是 CLI |
| `install.py` | 把灵动岛组件装到 `<配置目录>/island-extensions/dsh_memory/` |
| `island-component/island-component.json` | 灵动岛组件清单（id `dsh_memory`，label「记忆」） |
| `island-component/provider.py` | 组件入口：`read_count()` 读缓存，后台线程做同步 |

## 数据流

```
~/.dsh/dsh-pet/memory.json                   插件：{桶: {宠物: {messages: [...]}}}
  └─ classify_turn()  fact / lesson / topic，寒暄与废话跳过
      └─ <配置目录>/sessions/<角色>/memory.json   {version: 1, entries: [...]}
          └─ export_markdown() → ~/.dsh/dsh-pet/memory-bridge/memory.{json,md}
```

## 命令

```
python memory_bridge.py status        # 诊断：路径、插件轮次数、目标记忆分层统计
python memory_bridge.py sync          # 增量同步
python memory_bridge.py sync --full   # 忽略游标全量重扫
python memory_bridge.py export        # 反向导出
python memory_bridge.py watch         # 前台常驻（默认 60s，可 --interval=秒）
python install.py                     # 安装灵动岛组件
python install.py --remove            # 卸载组件（不删记忆数据）
```

环境变量：`DSH_PET_CONFIG_DIR`（桌宠配置目录）、`DSH_HOME`（默认 `~/.dsh`）。

## 纪律

- 记忆文件解析失败 → **不写盘**，只记日志；
- 写入 = 同目录临时文件 + fsync + `os.replace`；
- 跨进程锁 `memory.json.bridge-lock`（O_CREAT|O_EXCL + 超时 + 陈旧锁回收），
  不与桌宠自己的 QLockFile 抢文件名；
- 游标 `.memory-bridge-state.json` 记录已处理的轮次，重复运行是幂等的；
- 条数 / 总字数按桌宠上限（`MAX_ENTRIES=100`、`MAX_TOTAL_CHARS=4000`、单条 500）裁剪，
  裁剪时优先保留 `user/lesson/fact`。
