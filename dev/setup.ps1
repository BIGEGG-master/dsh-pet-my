# 一次性开发环境准备：创建 .venv 并安装运行/构建依赖
#
#   powershell -ExecutionPolicy Bypass -File dev\setup.ps1
#   powershell -ExecutionPolicy Bypass -File dev\setup.ps1 -Force   # 重建虚拟环境
#
# 版本要求：Python 3.11 ~ 3.13（源码 target-version = py313，打包产物是 3.11 运行时）。
# 本机默认用 D:\Python313；也可用 -PythonExe 指定。
param(
    [string]$PythonExe = '',
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'

if (-not $PythonExe) {
    foreach ($candidate in @('D:\Python313\python.exe', 'D:\Python312\python.exe', 'D:\Python311\python.exe')) {
        if (Test-Path $candidate) { $PythonExe = $candidate; break }
    }
    if (-not $PythonExe) {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if (-not $cmd) { throw '找不到 Python。请安装 3.11~3.13，或用 -PythonExe 指定解释器路径。' }
        $PythonExe = $cmd.Source
    }
}

$version = & $PythonExe -c "import sys;print('%d.%d' % sys.version_info[:2])"
Write-Host "[setup] python = $PythonExe ($version)"
if (-not ($version -match '^3\.(11|12|13)$')) {
    Write-Warning "[setup] 推荐 3.11~3.13，当前 $version 可能遇到依赖缺 wheel 的问题"
}

if ($Force -and (Test-Path $venv)) {
    Write-Host '[setup] 删除旧虚拟环境'
    Remove-Item -Recurse -Force $venv
}
if (-not (Test-Path $venv)) {
    & $PythonExe -m venv $venv
}
$vpy = Join-Path $venv 'Scripts\python.exe'

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& $vpy -m pip install --quiet -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
Write-Host '[setup] 安装运行依赖 + PyInstaller（首次约 500MB，请耐心）'
& $vpy -m pip install -r (Join-Path $root 'requirements.txt') pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
if ($LASTEXITCODE -ne 0) { throw '[setup] 依赖安装失败' }
& $vpy -m pip list | Select-String -Pattern 'PySide6|pyinstaller|numpy|onnxruntime|psutil'
Write-Host '[setup] 完成。运行：dev\run.ps1 ；构建：dev\build.ps1'
