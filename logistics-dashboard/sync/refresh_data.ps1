# refresh_data.ps1 —— 从 WorkBuddy「发布为网站」页面拉取资料库数据，刷新站点数据快照
# 用法：powershell -File refresh_data.ps1 -PageUrl "https://www.workbuddy.link/p/<pageId>"
#
# 降级策略（2026-11-02 用户定）：
#   拉不到 WorkBuddy（发布页下线 / 接口失败 / 两个库取不齐）时，**不抛错中断**，
#   改用工作区「最后一次好快照」data\records_wb_snapshot.json，打醒目告警
#   「本次用快照，快照时间=xxx」，退出码 0；
#   只有从来就没有过任何快照时，才退出码 1。
#   降级信息写入状态文件 data\wb_refresh_status.json，供 nightly_audit_logistics.ps1
#   读出后在抽检报告里注明「本次哪些字段没有独立回源」。
param(
  [Parameter(Mandatory = $true)][string]$PageUrl,
  [string]$OutDir = '',
  [string]$SnapshotPath = '',
  [string]$StatusPath = ''
)

$ErrorActionPreference = 'Stop'

$base = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $OutDir) { $OutDir = Join-Path $base 'shandi-v4' }
if (-not $SnapshotPath) { $SnapshotPath = Join-Path $base 'data\records_wb_snapshot.json' }
if (-not $StatusPath) { $StatusPath = Join-Path $base 'data\wb_refresh_status.json' }

$API = 'https://www.workbuddy.link/space/api/page/share/database/query'
$stage = 'init'

function Write-Info($m) { Write-Host "[refresh] $m" }

function Write-Status([hashtable]$st) {
  try {
    $dir = Split-Path -Parent $StatusPath
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $st['updatedAt'] = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    [System.IO.File]::WriteAllText($StatusPath, ($st | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
  } catch {
    Write-Host "[refresh] 状态文件写入失败（忽略）：$($_.Exception.Message)"
  }
}

try {
  # ---------- 1. 解析 pageId ----------
  $stage = 'pageid'
  if ($PageUrl -match '/p/([A-Za-z0-9_-]+)') {
    $pageId = $Matches[1]
  } else {
    throw "无法从链接解析 pageId：$PageUrl"
  }
  Write-Info "pageId = $pageId"

  # ---------- 2. 读取发布信息，确认页面在线 ----------
  $stage = 'publish-page'
  $r = Invoke-WebRequest -Uri "https://www.workbuddy.link/p/$pageId" -UseBasicParsing -TimeoutSec 40
  $m = [regex]::Match($r.Content, 'window\.__PUBLISH_BOOTSTRAP__=(\{.*?\});')
  if (-not $m.Success) { throw "页面未返回发布信息（可能已下线或不是发布页）" }
  $boot = $m.Groups[1].Value | ConvertFrom-Json
  if ($boot.error) { throw "发布信息返回错误 code=$($boot.error.code)（页面可能已取消发布或已换库）" }
  $artUrl = $boot.artifact.url.TrimEnd('/')
  Write-Info "artifacts = $artUrl"
  $paths = @($boot.artifact.artifacts | ForEach-Object { $_.path })
  Write-Info ("artifact files: " + ($paths -join ', '))

  # ---------- 3. 下载页面源码，提取数据库 ID ----------
  $stage = 'download-artifact'
  $tmp = Join-Path $env:TEMP ("wb_art_" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  $mainHtml = $null
  foreach ($p in $paths) {
    $local = Join-Path $tmp (Split-Path $p -Leaf)
    Invoke-WebRequest -Uri ($artUrl + '/' + $p) -OutFile $local -UseBasicParsing -TimeoutSec 90
    Write-Info "downloaded $p ($((Get-Item $local).Length) bytes)"
    if ($local -like '*.html') { $mainHtml = $local }
  }
  if (-not $mainHtml) { throw "发布产物里没有 html 页面文件" }
  $html = [System.IO.File]::ReadAllText($mainHtml, [System.Text.Encoding]::UTF8)

  $dbIds = New-Object System.Collections.Generic.List[string]
  foreach ($mm in [regex]::Matches($html, 'databaseId:\s*"([A-Za-z0-9_-]{10,})"')) { $dbIds.Add($mm.Groups[1].Value) }
  foreach ($mm in [regex]::Matches($html, 'var DATABASE_ID\s*=\s*"([A-Za-z0-9_-]{10,})"')) { $dbIds.Add($mm.Groups[1].Value) }
  $dbIds = @($dbIds | Select-Object -Unique)
  if ($dbIds.Count -eq 0) { throw "页面里没有解析到数据库 ID" }
  Write-Info ("database ids: " + ($dbIds -join ', '))

  # ---------- 4. 逐库拉全量 ----------
  function Pull-Database([string]$dbId) {
    $rows = @(); $cursor = $null; $page = 0
    while ($true) {
      $body = @{ pageId = $pageId; databaseId = $dbId; pageSize = 200 }
      if ($cursor) { $body.startCursor = $cursor }
      $resp = Invoke-RestMethod -Uri $API -Method POST -Body ($body | ConvertTo-Json -Compress) -ContentType 'application/json' -TimeoutSec 60
      if ($resp.code -ne 0) { throw "拉取 $dbId 失败：code=$($resp.code) $($resp.msg)" }
      $rows += @($resp.data.results)
      $page++
      $cursor = $resp.data.nextCursor
      if (-not $resp.data.hasMore -or -not $cursor -or $page -gt 60) { break }
    }
    Write-Info ("$dbId -> $($rows.Count) records")
    return , $rows
  }

  $stage = 'pull-database'
  $out = [ordered]@{}
  $mainId = ''
  $skuId = ''
  $mMain = [regex]::Match($html, 'var DATABASE_ID\s*=\s*"([A-Za-z0-9_-]{10,})"')
  if ($mMain.Success) { $mainId = $mMain.Groups[1].Value }
  foreach ($db in $dbIds) {
    $rows = Pull-Database $db
    if ($rows.Count -eq 0) { continue }
    if ($db -eq $mainId) { $out['main'] = $rows; $skuId = '' }
    else { $out['sku'] = $rows }
  }
  if (-not $out.Contains('main')) {
    # 没有匹配到主表：按表结构判定（含「FBA货件号」的是主表）
    foreach ($k in @($out.Keys)) {
      $first = @($out[$k])[0]
      if ($first -and $first.PSObject.Properties.Name -contains 'FBA货件号') { $out['main'] = $out[$k]; break }
    }
  }
  if (-not $out.Contains('main') -or -not $out.Contains('sku')) { throw "没同时拿到主表和 SKU 表（main=$($out.Contains('main')) sku=$($out.Contains('sku'))）" }
  $out['_meta'] = [ordered]@{
    fetchedAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    source    = "WorkBuddy published page $pageId"
    mainDbId  = $mainId
    skuDbId   = $skuId
  }

  # ---------- 5. 写出 + 存快照 ----------
  $stage = 'write'
  New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
  $json = $out | ConvertTo-Json -Depth 8 -Compress
  $outFile = Join-Path $OutDir 'records.json'
  [System.IO.File]::WriteAllText($outFile, $json, (New-Object System.Text.UTF8Encoding($false)))
  Write-Info ("WROTE " + $outFile + " ($((Get-Item $outFile).Length) bytes)")

  # 存「最后一次好快照」：下次 WorkBuddy 拉不到时降级用
  $snapDir = Split-Path -Parent $SnapshotPath
  if ($snapDir -and -not (Test-Path $snapDir)) { New-Item -ItemType Directory -Force -Path $snapDir | Out-Null }
  [System.IO.File]::WriteAllText($SnapshotPath, $json, (New-Object System.Text.UTF8Encoding($false)))
  Write-Info ("SNAPSHOT " + $SnapshotPath + " ($((Get-Item $SnapshotPath).Length) bytes)")

  Write-Status @{
    degraded       = $false
    fetchedAt      = $out['_meta'].fetchedAt
    snapshotAt     = (Get-Item $SnapshotPath).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
    snapshotPath   = $SnapshotPath
    outRecords     = $outFile
    error          = ''
    failedStage    = ''
    missingFields  = @()
  }
  Write-Info "DONE"
  exit 0
}
catch {
  $errMsg = $_.Exception.Message
  Write-Warning ("WorkBuddy 回源失败（阶段=" + $stage + "）：" + $errMsg)

  if (Test-Path $SnapshotPath) {
    # ---- 降级：用最后一次好快照 ----
    $snapAt = (Get-Item $SnapshotPath).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    [System.IO.File]::Copy($SnapshotPath, (Join-Path $OutDir 'records.json'), $true)
    Write-Status @{
      degraded      = $true
      fetchedAt     = ''
      snapshotAt    = $snapAt
      snapshotPath  = $SnapshotPath
      outRecords    = (Join-Path $OutDir 'records.json')
      error         = $errMsg
      failedStage   = $stage
      missingFields = @(
        'SKU表',
        '对账单价', '对账计费重', '对账物流费', '对账报关费', '对账合计', '对账差异', '对账渠道',
        '送达日期', '时效天数', '全程天数', '箱规',
        '货件状态', '物流状态', '入仓日期', '到港日期', '船开日期', '海运天数', '渠道',
        '货拉拉费', '船名航次', '费用完整'
      )
    }
    Write-Host ''
    Write-Host '############################################################'
    Write-Host '#  ⚠ 本次回源降级：WorkBuddy 拉取失败，本次用快照'
    Write-Host ("#    快照时间 = {0}" -f $snapAt)
    Write-Host ("#    失败阶段 = {0}；原因 = {1}" -f $stage, $errMsg)
    Write-Host '#    本次未独立回源的字段：SKU表 / 对账字段 / 送达日期 / 时效天数 /'
    Write-Host '#      箱规 / 货件状态等继承字段 —— 这些字段与站侧同源，不可独立核验'
    Write-Host '############################################################'
    Write-Host ''
    exit 0
  }

  # ---- 从来没有过任何快照：真失败 ----
  Write-Status @{
    degraded      = $true
    fetchedAt     = ''
    snapshotAt    = ''
    snapshotPath  = $SnapshotPath
    outRecords    = ''
    error         = $errMsg
    failedStage   = $stage
    missingFields = @()
  }
  Write-Error ("WorkBuddy 回源失败且没有任何可用快照，退出码 1。原因：" + $errMsg)
  exit 1
}
