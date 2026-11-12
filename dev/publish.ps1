# 把构建产物部署到安装目录（会先关桌宠、备份旧 exe）
#
#   powershell -ExecutionPolicy Bypass -File dev\publish.ps1
#   powershell -ExecutionPolicy Bypass -File dev\publish.ps1 -Target 'D:\dsh-pet-standalone-webm-chat'
#   powershell -ExecutionPolicy Bypass -File dev\publish.ps1 -NoStart     # 只复制不启动
#
# 只会覆盖同名文件（robocopy /E），不动安装目录里的卸载器 unins000.*、
# 以及你自己放的 start_pet.py / 说明文档。用户数据在 %APPDATA%，不受影响。
param(
    [string]$Target = 'D:\dsh-pet-standalone-webm-chat',
    [ValidateSet('webm-chat', 'webm', 'gif-chat', 'gif')]
    [string]$Variant = 'webm-chat',
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vpy = Join-Path $root '.venv\Scripts\python.exe'
$version = if (Test-Path $vpy) { (& $vpy (Join-Path $root 'dev\bump_version.py')).Trim() } else { 'unknown' }
$src = Join-Path $root "dist-onedir\dsh-pet-standalone-$Variant"
if (-not (Test-Path $src)) { throw "没有构建产物：$src。先跑 dev\build.ps1" }
if (-not (Test-Path $Target)) { throw "安装目录不存在：$Target" }

# 1) 关掉正在跑的桌宠（否则 exe 被占用，复制会失败）
$procs = Get-Process -Name "dsh-pet-standalone-$Variant" -ErrorAction SilentlyContinue
if ($procs) {
    Write-Host "[publish] 关闭运行中的桌宠：$($procs.Id -join ',')"
    $procs | ForEach-Object { $null = $_.CloseMainWindow() }
    Start-Sleep -Seconds 2
    Get-Process -Name "dsh-pet-standalone-$Variant" -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1
}

# 2) 备份旧 exe（_internal 太大，不整份备份；源码在仓库里随时可重建）
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $Target "_backup-v$version-$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Get-ChildItem $Target -File | Where-Object { $_.Extension -in '.exe', '.dll' } | Copy-Item -Destination $backup -Force
Write-Host "[publish] 旧 exe 备份到 $backup"

# 3) 复制产物（/E 不删除目标多余文件，卸载器与自定义文件都会保留）
Write-Host "[publish] 复制 $src -> $Target"
& robocopy $src $Target /E /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "[publish] robocopy 失败（exit=$LASTEXITCODE）" }

Write-Host "[publish] 已部署 v$version" -ForegroundColor Green

if (-not $NoStart) {
    $exe = Join-Path $Target "dsh-pet-standalone-$Variant.exe"
    if (Test-Path $exe) {
        Write-Host "[publish] 启动 $exe"
        Start-Process -FilePath $exe -WorkingDirectory $Target
    }
}
