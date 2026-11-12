# 打一个版本：升版本号（可选）→ 走仓库自带的 onedir 构建
#
#   powershell -ExecutionPolicy Bypass -File dev\build.ps1
#   powershell -ExecutionPolicy Bypass -File dev\build.ps1 -Bump patch
#   powershell -ExecutionPolicy Bypass -File dev\build.ps1 -SkipZip
#
# 产物：dist-onedir\dsh-pet-standalone-webm-chat\
# 部署：dev\publish.ps1 （把产物覆盖到安装目录，会先备份）
param(
    [ValidateSet('webm-chat', 'webm', 'gif-chat', 'gif')]
    [string]$Variant = 'webm-chat',
    [ValidateSet('none', 'patch', 'minor', 'major')]
    [string]$Bump = 'none',
    [switch]$SkipZip,
    [switch]$SkipSlim,
    [switch]$SkipCheck
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) { throw '缺少 .venv，先运行 dev\setup.ps1' }

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

if ($Bump -ne 'none') {
    $result = & $vpy (Join-Path $root 'dev\bump_version.py') $Bump
    Write-Host "[build] 版本：$result" -ForegroundColor Yellow
}
$version = (& $vpy (Join-Path $root 'dev\bump_version.py')).Trim()
Write-Host "[build] 当前版本 $version, 变体 $Variant"

# build_onedir.ps1 里用裸 `python`，把 venv 放到 PATH 最前面
$env:PATH = (Join-Path $root '.venv\Scripts') + ';' + $env:PATH

$buildArgs = @('-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'scripts\build_onedir.ps1'), '-Variant', $Variant)
if ($SkipZip) { $buildArgs += '-SkipZip' }
if ($SkipSlim) { $buildArgs += '-SkipSlim' }
if ($SkipCheck) { $buildArgs += '-SkipCheck' }
& powershell @buildArgs
if ($LASTEXITCODE -ne 0) { throw "[build] 构建失败（exit=$LASTEXITCODE）" }

$outDir = Join-Path $root "dist-onedir\dsh-pet-standalone-$Variant"
if (-not (Test-Path $outDir)) { throw "[build] 没找到产物目录：$outDir" }
Write-Host "[build] 完成：$outDir (v$version)" -ForegroundColor Green
Write-Host '[build] 下一步：dev\publish.ps1 部署到安装目录'
