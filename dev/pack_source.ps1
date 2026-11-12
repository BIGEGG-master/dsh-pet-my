# 把当前源码打包成可分发的 zip（清掉环境、构建产物、缓存与个人数据）
#
#   powershell -ExecutionPolicy Bypass -File dev\pack_source.ps1
#   powershell -ExecutionPolicy Bypass -File dev\pack_source.ps1 -OutFile D:\dsh-pet-src.zip
#   powershell -ExecutionPolicy Bypass -File dev\pack_source.ps1 -KeepTemp   # 保留暂存目录供检查
#
# 排除（与 .gitignore 同口径，另加本机环境）：
#   .venv / dist-onedir / build-onedir / build / .pytest_cache / __pycache__
#   *.pyc / *.log / *.spec / assets/icon-preview.png / packaging/build_variant.py
#   assets/characters/*/frameseq（.gitignore 的派生物，构建时按需生成）
#   dev/backups（个人配置快照，含本机 profile / 记忆）
param(
    [string]$OutFile = '',
    [switch]$KeepTemp
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vpy = Join-Path $root '.venv\Scripts\python.exe'

$version = if (Test-Path $vpy) { (& $vpy (Join-Path $root 'dev\bump_version.py')).Trim() } else { 'dev' }
$stamp = Get-Date -Format 'yyyyMMdd'
if (-not $OutFile) { $OutFile = Join-Path (Split-Path -Parent $root) "dsh-pet-indesktop-$version-src-$stamp.zip" }

$sevenZip = @('C:\Program Files\7-Zip\7z.exe', 'D:\7-Zip\7z.exe') | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sevenZip) { $sevenZip = (Get-Command 7z -ErrorAction SilentlyContinue).Source }
if (-not $sevenZip) { throw '找不到 7z.exe（装 7-Zip 或把 7z 加进 PATH）' }

$tempRoot = Join-Path $env:TEMP ("dsh-pet-pack-" + (Get-Date -Format 'HHmmss'))
$stage = Join-Path $tempRoot "dsh-pet-indesktop-$version"
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# robocopy 的 /XD 按目录名匹配任意层级：frameseq 一次就全排掉
$excludeDirs = @('.venv', 'dist-onedir', 'build-onedir', 'build', '.pytest_cache', '__pycache__', '.git', 'node_modules', 'frameseq', 'backups')
$excludeFiles = @('*.pyc', '*.log', '*.spec', 'icon-preview.png', 'build_variant.py')

Write-Host "[pack] 复制源码 -> $stage"
$roboArgs = @($root, $stage, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/R:1', '/W:1', '/XD') + $excludeDirs + @('/XF') + $excludeFiles
& robocopy @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "[pack] robocopy 失败（exit=$LASTEXITCODE）" }

$files = Get-ChildItem $stage -Recurse -File
$sizeMb = [math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "[pack] 暂存：$($files.Count) 个文件 / $sizeMb MB"

if (Test-Path $OutFile) { Remove-Item $OutFile -Force }
Write-Host "[pack] 压缩 -> $OutFile"
& $sevenZip a -tzip -mx=7 -bso0 -bsp0 $OutFile $stage | Out-Null
if ($LASTEXITCODE -ne 0) { throw "[pack] 7z 压缩失败（exit=$LASTEXITCODE）" }

$zipMb = [math]::Round((Get-Item $OutFile).Length / 1MB, 1)
$hash = (Get-FileHash $OutFile -Algorithm SHA256).Hash
Write-Host "[pack] 完成：$OutFile" -ForegroundColor Green
Write-Host "[pack] 大小：$zipMb MB　SHA256：$hash"

if ($KeepTemp) {
    Write-Host "[pack] 暂存目录保留：$stage"
} else {
    Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue
}
