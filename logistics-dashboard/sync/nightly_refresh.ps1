# nightly_refresh.ps1 —— 夜间数据刷新入口（定时任务专用，一条命令跑完整链路）
#
# 用法： powershell -NoProfile -ExecutionPolicy Bypass -File nightly_refresh.ps1
#
# 逻辑：
#   1) 判断「昨天」是不是工作日。周末只回一句提示，不调任何接口。
#   2) 工作日则按正确 AsOf 拉取领星数据（AsOf = 昨天，与定时任务口径一致）。
#   3) 跑 refresh_all.ps1 -SkipFetch，完成 构建 → 注入 → 发货记录 → 发布上线 → 线上校验。
#   （物流抽检不在这条链路里，见文末备注与 audit_plan.py）
#
# 为什么自己拉数而不用 refresh_all.ps1 自带的 fetch：
#   refresh_all.ps1 里的 fetch_ledger.ps1 不带 -AsOf，默认取「当天」，
#   窗口截止日会多一天；这里显式传 AsOf=昨天，与「周二 00:00 拉周一」的既定口径一致。
#
# 退出码：0 = 全链路成功（含发布与线上校验），或周末正常跳过；非 0 = 某一步失败。
$ErrorActionPreference = 'Stop'
$WS = $PSScriptRoot

# 每个步骤的输出单独落临时文件，结束后只回显末尾若干行。
# 不用管道捕获：publish_update.py 会输出上万字符的单行 JSON，
# 经过 PowerShell 管道时被掐断会让上游 python 收到断管信号、
# $LASTEXITCODE 变成 -1，被误判成「步骤失败」（2026-10-29 踩过）。
# Start-Process 还能保证子进程异常退出不会连带杀掉 PowerShell 宿主进程，
# 否则 try/catch 抓不到，重试形同虚设（实测 exit -1 会让宿主直接结束）。
function RunStep {
  param(
    [string]$Name,
    [string[]]$Arguments,
    [int]$Tail = 12,
    [int]$MaxTry = 1
  )
  for ($i = 1; $i -le $MaxTry; $i++) {
    $log = Join-Path $env:TEMP ("nightly_{0}_{1}_{2}.log" -f (Get-Date -Format 'HHmmss'), $i, [guid]::NewGuid().ToString('N').Substring(0, 6))
    $err = "$log.err"
    Write-Host ("`n=== [{0}] NIGHTLY {1}{2} ===" -f (Get-Date -Format 'HH:mm:ss'), $Name, $(if ($MaxTry -gt 1) { " (第{0}/{1}次)" -f $i, $MaxTry } else { '' }))
    $p = Start-Process -FilePath 'powershell' `
      -ArgumentList (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File') + $Arguments) `
      -Wait -PassThru -NoNewWindow `
      -RedirectStandardOutput $log -RedirectStandardError $err
    if (Test-Path $log) {
      $lines = @(Get-Content $log -Encoding UTF8 -ErrorAction SilentlyContinue)
      if ($Tail -gt 0 -and $lines.Count -gt $Tail) { $lines = $lines | Select-Object -Last $Tail }
      foreach ($l in $lines) { Write-Host $l }
    }
    if ($p.ExitCode -ne 0) {
      if (Test-Path $err) {
        $e = @(Get-Content $err -Encoding UTF8 -ErrorAction SilentlyContinue)
        if ($e.Count -gt 0) { Write-Warning ("stderr: " + ($e | Select-Object -Last 5 | Out-String)) }
      }
      if ($i -lt $MaxTry) {
        Write-Warning ("{0} 第 {1}/{2} 次失败（exit={3}），{4} 秒后重试" -f $Name, $i, $MaxTry, $p.ExitCode, (10 * $i))
        Start-Sleep -Seconds (10 * $i)
        continue
      }
      throw ("步骤失败：{0} (exit={1})" -f $Name, $p.ExitCode)
    }
    return
  }
}

$y = (Get-Date).AddDays(-1)
$yStr = $y.ToString('yyyy-MM-dd')
Write-Host ("NIGHTLY start now={0} AsOf={1} ({2})" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $yStr, $y.DayOfWeek)

# 周末（2026-11-02 小丁定）：**不再整条跳过**。
#   · 仓库每天都有出入库 → 库存快照（国内仓/FBA 库存 → 库容占用、库存卡）必须天天拉，
#     否则周一看到的还是周五的库存，落后 3 天。
#   · 「发货记录类」（库存分类账 / FBA出库明细 / 分类账历史源）周末照旧跳过 —— 周末本来就没货要发。
if ($y.DayOfWeek -eq [DayOfWeek]::Saturday -or $y.DayOfWeek -eq [DayOfWeek]::Sunday) {
  Write-Host ("WEEKEND 只拉库存快照 AsOf={0} ({1})，发货记录类跳过" -f $yStr, $y.DayOfWeek)
  RunStep -Name '领星-仓库/店铺/库存明细' -Arguments @("$WS\fetch_wh.ps1", '-OutDir', "$WS\wh_raw") -Tail 4
  RunStep -Name '领星-本地仓商品清单'   -Arguments @("$WS\fetch_products.ps1") -Tail 2
  RunStep -Name '构建+注入+发布+线上校验' -Arguments @("$WS\refresh_all.ps1", '-SkipFetch') -Tail 22 -MaxTry 3
  Write-Host ("`nNIGHTLY DONE ok at {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
  exit 0
}

# ---- 抓取（显式 AsOf = 昨天）----
RunStep -Name '领星-库存分类账(月+日)' -Arguments @("$WS\fetch_ledger.ps1", '-AsOf', $yStr) -Tail 4
RunStep -Name '领星-仓库/店铺/库存明细' -Arguments @("$WS\fetch_wh.ps1", '-OutDir', "$WS\wh_raw") -Tail 3
RunStep -Name '领星-本地仓商品清单' -Arguments @("$WS\fetch_products.ps1") -Tail 2
RunStep -Name '领星-FBA出库明细' -Arguments @("$WS\fetch_ship.ps1") -Tail 2

# ---- 构建 → 注入 → 发货记录 → 发布上线 → 线上校验 ----
# 这一段带重试：发布环节偶发 exit=-1，原样重跑即可成功（2026-10-29 实测）。
RunStep -Name '构建+注入+发布+线上校验' -Arguments @("$WS\refresh_all.ps1", '-SkipFetch') -Tail 22 -MaxTry 3

# 抽检已独立成「工作日随机三晚」定时任务（sch_ca0236f1ebbd → audit_plan.py 判定是否抽检夜 → nightly_audit_logistics.ps1）。
# 2026-10-30 小丁定：00:00 这条链路只保留「拉数→构建→注入→发布→线上校验」，
# 不再带抽检输出（抽检是抽样，不每晚做，省 token）。
Write-Host ("`nNIGHTLY DONE ok at {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
exit 0
