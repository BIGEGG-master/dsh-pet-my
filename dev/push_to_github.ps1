# 把当前仓库推到 GitHub（创建仓库 + push 一条龙）
#
#   powershell -ExecutionPolicy Bypass -File dev\push_to_github.ps1 `
#       -Token ghp_xxxxxxxx -Repo dsh-pet-indesktop-fork
#
#   powershell -ExecutionPolicy Bypass -File dev\push_to_github.ps1 `
#       -Token ghp_xxxxxxxx -Repo my-pet -Private
#
# Token 需要什么权限：
#   - classic PAT：勾 `repo`（要建私有库还要 `repo`；公开库同样需要 `repo` 才能建仓库）
#   - fine-grained PAT：Repository permissions → Administration: Read and write（建仓库）、
#     Contents: Read and write（推送）、Metadata: Read
#
# 安全：token 只出现在这一次 `git push` 的 URL 里，**不写进 .git/config**；
#       推完 origin 会设成不带 token 的 https 地址。命令行参数仍可能留在你的
#       PowerShell 历史里，介意的话用完去 GitHub 撤销这个 token。
param(
    [Parameter(Mandatory = $true)][string]$Token,
    [Parameter(Mandatory = $true)][string]$Repo,
    [string]$Description = '基于 MerZlin/dsh-pet-indesktop 的修改版：DSH 联动 + 可迭代开发脚本',
    [switch]$Private,
    [string]$Branch = 'main',
    [string]$GitExe = '',
    # 本地代理（如 Clash 的 http://127.0.0.1:7897）。留空则自动读系统代理设置；
    # 国内网络直连 github.com:443 常常超时，但 api.github.com 可能仍然通——
    # 于是会出现「仓库建好了、push 却连不上」，这里必须显式处理。
    [string]$Proxy = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not $Proxy) {
    try {
        $ie = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop
        if ($ie.ProxyEnable -eq 1 -and $ie.ProxyServer) {
            $Proxy = if ($ie.ProxyServer -match '^https?://') { $ie.ProxyServer } else { "http://$($ie.ProxyServer)" }
        }
    } catch {
        $Proxy = ''
    }
    if ($Proxy) { Write-Host "[push] 自动使用系统代理：$Proxy" }
}

if (-not $GitExe) {
    $GitExe = @('D:\MinGit\cmd\git.exe', 'C:\Program Files\Git\cmd\git.exe') | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $GitExe) { $GitExe = (Get-Command git -ErrorAction SilentlyContinue).Source }
}
if (-not $GitExe) { throw '找不到 git.exe（先跑 dev\setup.ps1 或装 Git / 放一份 MinGit）' }

$headers = @{
    Authorization          = "Bearer $Token"
    Accept                 = 'application/vnd.github+json'
    'User-Agent'           = 'dsh-pet-fork-publisher'
    'X-GitHub-Api-Version' = '2022-11-28'
}

Write-Host '[push] 校验 token…'
try {
    $me = Invoke-RestMethod -Uri 'https://api.github.com/user' -Headers $headers -TimeoutSec 20
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
    throw "[push] token 无效或网络不通（HTTP $code）：$($_.Exception.Message)"
}
$user = $me.login
Write-Host "[push] 账号：$user"

Write-Host "[push] 创建/确认仓库 $user/$Repo …"
$payload = @{
    name        = $Repo
    description = $Description
    private     = [bool]$Private
    has_issues  = $true
    has_wiki    = $false
} | ConvertTo-Json
try {
    $repoInfo = Invoke-RestMethod -Method Post -Uri 'https://api.github.com/user/repos' `
        -Headers $headers -Body $payload -ContentType 'application/json' -TimeoutSec 40
    Write-Host "[push] 已创建：$($repoInfo.html_url)"
} catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
    if ($code -eq 422) {
        Write-Host '[push] 仓库已存在，继续推送'
        $repoInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/$user/$Repo" -Headers $headers -TimeoutSec 20
    } else {
        throw "[push] 创建仓库失败（HTTP $code）：$($_.Exception.Message)"
    }
}

Set-Location $root
$workBranch = (& $GitExe rev-parse --abbrev-ref HEAD).Trim()
Write-Host "[push] 推送分支 $workBranch → $Branch（仓库约 114MB，按网速可能要几分钟）…"
$remoteUrl = "https://x-access-token:$Token@github.com/$user/$Repo.git"
$proxyArgs = @()
if ($Proxy) { $proxyArgs = @('-c', "http.proxy=$Proxy", '-c', "https.proxy=$Proxy") }
& $GitExe @proxyArgs push $remoteUrl "${workBranch}:refs/heads/$Branch" --progress 2>&1 | ForEach-Object { $_ }
if ($LASTEXITCODE -ne 0) { throw "[push] git push 失败（exit=$LASTEXITCODE）" }

# 推完把 origin 设成干净地址（不带 token）；代理留在仓库级配置里，后续 fetch/push 不再踩墙
& $GitExe remote remove origin 2>$null | Out-Null
& $GitExe remote add origin "https://github.com/$user/$Repo.git"
if ($Proxy) {
    & $GitExe config http.proxy $Proxy | Out-Null
    & $GitExe config https.proxy $Proxy | Out-Null
}
& $GitExe fetch origin 2>$null | Out-Null
& $GitExe branch "--set-upstream-to=origin/$Branch" $workBranch 2>$null | Out-Null

Write-Host ''
Write-Host "[push] 完成：$($repoInfo.html_url)" -ForegroundColor Green
Write-Host "[push] clone：git clone https://github.com/$user/$Repo.git"
