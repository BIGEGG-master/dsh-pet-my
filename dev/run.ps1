# 用源码目录里的虚拟环境直接运行桌宠（开发模式，不打包）
#
#   powershell -ExecutionPolicy Bypass -File dev\run.ps1
#   powershell -ExecutionPolicy Bypass -File dev\run.ps1 --settings
#
# 注意：开发模式与安装版共用同一个用户数据目录（%APPDATA%\dsh-pet-standalone-webm-chat），
# 两者不能同时运行（单实例锁会互相顶掉）。
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    throw "找不到虚拟环境：$vpy。先运行 dev\setup.ps1 安装依赖。"
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $root
& $vpy -m pet @args
