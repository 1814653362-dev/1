# sync_sku_batch_lx.ps1 —— SKU 批次明细维护（每周一、周三各一次）
#
# 用法： powershell -NoProfile -ExecutionPolicy Bypass -File sync_sku_batch_lx.ps1 [-Force]
#
# 频次：只在周一、周三各触发一次（minimax-bot 的 create_schedule 没有 cron，
#       所以建成 daily + 脚本内判定星期几；与 audit_plan.py 同风格，
#       但这条是固定周一周三、不需要随机种子，不动 audit_plan.py 的抽检规则）。
#       非周一/周三：只回一行提示就退出，不调接口、不发布。
#
# 数据来源口径（用户 2026-10-30 亲口纠正，以此为准）：
#   · SKU 批次明细 / 主表「货件状态」= 抓领星 API 的 shipment_status 维护的
#     （shipment_id = 主表「FBA货件号」本体）。
#   · 「预估到仓时间」才是系统推算的，页面每次打开实时重算 —— 本脚本不碰推算逻辑。
#   · 主表「货件状态」平时是从 WorkBuddy 旧记录继承的（那边一周才同步一次），
#     所以只重跑构建 ≠ 生效；必须在建表阶段按 FBA 货件号用领星状态直接覆盖。
#
# 边界：只做「SKU 批次明细 + 领星货件状态」这一件事，
#       不重跑 00:00 那条「FBA数据工作日更新」的整链路（不重复消耗接口和额度）。
#
# 退出码：0 = 成功或非执行日；非 0 = 某一步失败。
param(
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
$WS = $PSScriptRoot

# 每个步骤的输出单独落临时文件再回显末尾若干行（不用管道捕获：
# publish_update.py 会输出上万字符的单行 JSON，走管道被掐断会让上游收到断管信号、
# $LASTEXITCODE 变 -1，被误判成失败）。Start-Process 还能保证子进程异常退出不连带杀宿主。
function RunStep {
  param(
    [string]$Name,
    [string[]]$Arguments,
    [int]$Tail = 12,
    [int]$MaxTry = 1,
    [switch]$NonFatal
  )
  # 解释器分流：.py 走 python，其余走 powershell -File
  $isPy = ($Arguments[0] -like '*.py')
  if ($isPy) {
    $exe = 'python'
    $argList = @($Arguments)
  } else {
    $exe = 'powershell'
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File') + $Arguments
  }
  for ($i = 1; $i -le $MaxTry; $i++) {
    $log = Join-Path $env:TEMP ("lxbatch_{0}_{1}_{2}.log" -f (Get-Date -Format 'HHmmss'), $i, [guid]::NewGuid().ToString('N').Substring(0, 6))
    $err = "$log.err"
    Write-Host ("`n=== [{0}] SKUBATCH {1}{2} ===" -f (Get-Date -Format 'HH:mm:ss'), $Name, $(if ($MaxTry -gt 1) { " (第{0}/{1}次)" -f $i, $MaxTry } else { '' }))
    $p = Start-Process -FilePath $exe `
      -ArgumentList $argList `
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
        Write-Warning ("$Name 第 $i/$MaxTry 次失败（exit=$($p.ExitCode)），$($i * 10) 秒后重试")
        Start-Sleep -Seconds (10 * $i)
        continue
      }
      if ($NonFatal) {
        Write-Warning ("⚠ $Name 失败（exit=$($p.ExitCode)）——本步不中断整条流水线，后续步骤照常跑")
        return
      }
      throw ("步骤失败：$Name (exit=$($p.ExitCode))")
    }
    return
  }
}

$now = Get-Date
$wdName = @('周一','周二','周三','周四','周五','周六','周日')[[int]$now.DayOfWeek - 1]
Write-Host ("SKUBATCH start now={0} weekday={1}" -f $now.ToString('yyyy-MM-dd HH:mm:ss'), $wdName)

# ---- 1) 星期判定：只在周一、周三执行 ----
$isMon = ($now.DayOfWeek -eq [DayOfWeek]::Monday)
$isWed = ($now.DayOfWeek -eq [DayOfWeek]::Wednesday)
if (-not ($isMon -or $isWed) -and -not $Force) {
  Write-Host ("SKIP_DAY weekday={0} 本任务只在周一/周三执行，未调用任何接口" -f $wdName)
  exit 0
}
if ($Force) { Write-Host "FORCE=1 跳过星期判定（手动触发）" }

# ---- 2) 同步共享盘发货记录（本地文件拷贝，不耗接口额度）----
RunStep -Name '同步共享盘发货记录' -Arguments @("$WS\sync_share_xlsx.ps1") -Tail 2

# ---- 3) 抓领星货件状态（shipmentList）----
#   窗口 400 天（2026-11-02 主管定）：领星 receiving_time 要覆盖到 9 月之前，
#   写回共享盘才能把历史月份也换成领星口径的送达日期。
RunStep -Name '领星-FBA出库明细(货件状态)' -Arguments @("$WS\fetch_ship.ps1", '-OutDir', "$WS\lx_raw", '-Days', '400') -Tail 3

# ---- 3b) 落盘「货件号 → receiving_time」映射（2026-11-02 用户提、主管定）----
#   领星 receiving_time = 仓库开始接收时刻 = 真正的到仓时间，回填主表「送达日期」用。
#   每次拉完领星就顺手落盘，保证写回用最新值而不是一次性快照。
RunStep -Name '落盘领星接收时间映射' -Arguments @("$WS\lx_recv_time.py", '--lx', "$WS\lx_raw\shipments.json", '--out', "$WS\data\lx_recv_time.json") -Tail 3

# ---- 3c) 生成写回计划（本地副本 + 领星快照 → data\lx_writeback_plan.json）----
RunStep -Name '生成共享盘写回计划' -Arguments @("$WS\build_lx_writeback_plan.py", '--lx', "$WS\lx_raw\shipments.json", '--share', "$WS\data\shipments_share.xlsx", '--out', "$WS\data\lx_writeback_plan.json") -Tail 4

# ---- 3d) 写回共享盘（Excel COM；Delivery window / 送达时间 两列）----
#   主管定：共享盘是唯一事实源，records.json 从它构建。
#   共享盘正被 Excel 打开时脚本会报错停下 → 这里用 -NonFatal，只告警不中断，
#   本轮时效数据就按共享盘里已有的值构建（不会写坏）。
RunStep -Name '写回共享盘(领星送达时间)' -Arguments @("$WS\write_share_lx.ps1", '-SkipBackup') -Tail 8 -NonFatal

# ---- 3e) 写回后重新同步共享盘 → 本地副本（构建脚本读的是本地副本）----
RunStep -Name '同步共享盘(写回后)' -Arguments @("$WS\sync_share_xlsx.ps1") -Tail 2

# ---- 4) 建表：按 FBA 货件号用领星状态直接覆盖主表「货件状态」----
#    --old/--out 默认同一个 records.json；脚本内部先写 .tmp → 校验 → 原子替换，失败不动正式文件。
#    --no-lx-recv：送达日期只用共享盘「送达时间」列 + 旧记录继承值，不做系统侧二次回填。
RunStep -Name '重建主表(领星覆盖货件状态)' -Arguments @("$WS\build_records_from_share.py", '--no-lx-recv') -Tail 14

# ---- 5) 发布上线 + 线上校验 ----
RunStep -Name '发布上线' -Arguments @("$WS\publish_update.py") -Tail 6
RunStep -Name '线上校验' -Arguments @("$WS\verify_page.py", 'https://REPLACE_WITH_YOUR_SITE_URL/index.html') -Tail 12

Write-Host ("`nSKUBATCH DONE ok at {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
exit 0
