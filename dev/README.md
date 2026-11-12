# dev —— 版本化迭代工作流

这套脚本把「改源码 → 升版本 → 打包 → 部署」固定成四步，避免每次手工回忆参数。
**版本号只有一个来源**：`pet/__init__.py` 的 `__version__`。

## 目录约定

```
<源码根>
├─ pet/                    产品源码（唯一改动入口）
├─ dev/                    本目录：开发/构建/部署脚本（不参与打包）
├─ scripts/build_onedir.ps1  仓库自带的打包脚本（PyInstaller onedir）
└─ dist-onedir/            构建产物（dsh-pet-standalone-webm-chat/）
```

## 一次性准备

```powershell
powershell -ExecutionPolicy Bypass -File dev\setup.ps1
```

建 `.venv` 并装 `requirements.txt` + `pyinstaller`（首次约 500MB）。本机默认用
`D:\Python313\python.exe`；换机器用 `-PythonExe` 指定。

## 日常循环

```powershell
# 1) 开发调试（直接跑源码，不打包）
powershell -ExecutionPolicy Bypass -File dev\run.ps1

# 2) 改完代码，升版本并打包
powershell -ExecutionPolicy Bypass -File dev\build.ps1 -Bump patch   # 4.4.0 -> 4.4.1
#    -Bump minor / major 按语义化版本升；-Bump none 只重打包不升版本
#    -SkipZip 跳过便携 zip（只出 onedir 目录，本地迭代更快）
#    -SkipSlim 保留 slim_bundle 会删掉的模块（排查“打包后缺模块”时用）

# 3) 部署到安装目录（自动关旧的、备份 exe、复制、启动）
powershell -ExecutionPolicy Bypass -File dev\publish.ps1
```

只想更新版本号不打包：

```powershell
.venv\Scripts\python.exe dev\bump_version.py patch
.venv\Scripts\python.exe dev\bump_version.py set 4.4.2
```

## 其他常用脚本

```powershell
# 配 AI 对话（key 只进系统钥匙串，config.json 里只留 ref）
.venv\Scripts\python.exe dev\configure_ai.py --show                    # 看当前配置
.venv\Scripts\python.exe dev\configure_ai.py --key sk-xxxx             # 写 DeepSeek 官方
.venv\Scripts\python.exe dev\configure_ai.py --key sk-xxxx --test      # 写完立刻验一次
.venv\Scripts\python.exe dev\configure_ai.py --key sk-xxxx `
    --base-url http://127.0.0.1:11434/v1 --model qwen2.5 --name Ollama  # 任意 OpenAI 兼容端点

# 版本号
.venv\Scripts\python.exe dev\bump_version.py            # 打印当前版本
.venv\Scripts\python.exe dev\bump_version.py patch      # 4.4.1 -> 4.4.2
```

## 注意

- **源码直跑与打包版的数据目录不是同一个**：
  - 打包变体（`dist-onedir\dsh-pet-standalone-webm-chat`）→ `%APPDATA%\dsh-pet-standalone-webm-chat\`
  - `dev\run.ps1` 源码直跑 → `%APPDATA%\dsh-pet-standalone\`
    （没有 `packaging/build_variant.py` 时 `_app_dir_name()` 回退到共享名）

  所以「在源码里改了配置/记忆，打包版看不到」是正常的：两边各有一份数据。
  `dev\configure_ai.py` 会自动挑**存在 config.json 的那个**目录，也可以用
  `--config-dir` 显式指定。

- **开发模式与安装版共用同一个用户数据目录**（`%APPDATA%\dsh-pet-standalone-webm-chat`），
  同一时间只能跑一个；`dev\run.ps1` 前请先退出安装版。
- 构建脚本要求 `python` 能在 PATH 里找到 —— `dev\build.ps1` 已自动把 `.venv\Scripts` 放最前。
- 打包会跑一堆校验（编码、TTS、OCR 模型、slim 后的导入闭包）。任何一个失败都别绕过，
  它们守的是“产物能启动”这条线。
- 部署后服务端数据（配置、记忆、会话）全部保留；安装目录里已有的 `unins000.*`、
  `start_pet.py` 等不会被删除（`robocopy /E` 不做镜像删除）。

## 回滚

`dev\publish.ps1` 会在安装目录下留一份 `_backup-v<版本>-<时间戳>\`（旧 exe）。
把它复制回去即可；或者 `git` 里 checkout 旧源码重打包。
