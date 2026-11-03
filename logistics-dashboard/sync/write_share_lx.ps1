param(
  [string]$Plan,
  [switch]$DryRun,
  [switch]$SkipBackup
)

# write_share_lx.ps1 —— 用 Excel COM 把领星数据写回共享盘发货记录的两列
#
# 口径（2026-11-02 用户定）：
#   · Delivery window 列 ← 领星 shipment_status（照原样写英文枚举）
#   · 送达时间 列         ← 领星 receiving_time 的日期部分，统一 YYYY-MM-DD（写成真日期，不是文本）
#   · 缺这两列的 tab（7/6/5/4/1/2/3/12/11月）→ 在表尾新增这两列再写
#   · 领星查不到的行一律不动（保留原值和原公式）
#   · 已有值也覆盖（时效口径统一切到领星）
#   · 共享盘不新增「仓库接收时间」列——送达时间列就是它的来源
#
# 用法： powershell -NoProfile -ExecutionPolicy Bypass -File write_share_lx.ps1
#        [-Plan <写回计划 json>] [-DryRun] [-SkipBackup]

$WS = $PSScriptRoot
if (-not $Plan) { $Plan = Join-Path $WS 'data\lx_writeback_plan.json' }
if (-not (Test-Path -LiteralPath $Plan)) { throw "写回计划不存在：$Plan" }

# ---------- 1. 定位共享盘源文件 ----------
function Find-Src {
  $roots = @('\\Sd-fwq\F\物流部', 'W:\物流部')
  foreach ($r in $roots) {
    if (-not (Test-Path -LiteralPath $r)) { continue }
    foreach ($n in @('发货记录xlsx.xlsx', '发货记录.xlsx')) {
      $p = Join-Path $r $n
      if (Test-Path -LiteralPath $p) { return $p }
    }
    $hit = Get-ChildItem -LiteralPath $r -Filter '发货记录*.xlsx' -File -ErrorAction SilentlyContinue |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  return $null
}
$Src = Find-Src
if (-not $Src) { throw '共享盘发货记录找不到（已试 \\Sd-fwq\F\物流部 与 W:\物流部）' }
Write-Host ("[write] SRC = " + $Src)

# ---------- 2. 锁检测：文件被 Excel 打开就报错停下，绝不硬写 ----------
try {
  $fs = [System.IO.File]::Open($Src, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
  $fs.Close()
  Write-Host '[write] 锁检测：文件未被占用'
} catch {
  throw ("共享盘发货记录正被占用（很可能 Excel 打开中），已停止、未做任何修改：" + $_.Exception.Message)
}

# ---------- 3. 备份（整份复制到工作目录，只留一份）----------
if (-not $SkipBackup) {
  $bak = Join-Path $WS 'share_backup_before_lx.xlsx'
  Copy-Item -LiteralPath $Src -Destination $bak -Force
  Write-Host ("[write] 备份 → " + $bak + " (" + [math]::Round((Get-Item $bak).Length/1KB,1) + " KB)")
}

# ---------- 4. 读计划 ----------
$pl = Get-Content -Raw -Encoding UTF8 -LiteralPath $Plan | ConvertFrom-Json
Write-Host ("[write] 计划：{0} 个 tab / {1} 行待写" -f $pl.sheets.Count, $pl._meta.plannedRows)

if ($DryRun) { Write-Host '[write] DryRun：不做任何写入'; exit 0 }

# ---------- 5. Excel COM 写入 ----------
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$wb = $null
try {
  $wb = $xl.Workbooks.Open($Src, 0, $false)
  $nDw = 0; $nDt = 0; $nNewCol = 0

  foreach ($s in $pl.sheets) {
    $ws = $wb.Worksheets.Item($s.name)
    $used = $ws.UsedRange
    $lastCol = $used.Column + $used.Columns.Count - 1
    $lastRow = $used.Row + $used.Rows.Count - 1
    # 找表头行（第一行）
    $hdr = @{}
    for ($c = 1; $c -le $lastCol; $c++) {
      $v = $ws.Cells.Item(1, $c).Text
      if ($v) { $hdr[[string]$v] = $c }
    }
    $colFba = $hdr['FBA货件号']
    if (-not $colFba) { Write-Host ("[write] 跳过 tab {0}：无 FBA货件号 列" -f $s.name); continue }

    # 缺列就补（在表尾新增两列）
    $colDw = $hdr['Delivery window']
    if (-not $colDw) {
      $colDw = $lastCol + 1
      $ws.Cells.Item(1, $colDw).Value2 = 'Delivery window'
      $nNewCol++
      Write-Host ("[write] tab {0}：新增列 {1} = Delivery window" -f $s.name, $colDw)
      $lastCol = $colDw
    }
    $colDt = $hdr['送达时间']
    if (-not $colDt) {
      $colDt = $lastCol + 1
      $ws.Cells.Item(1, $colDt).Value2 = '送达时间'
      $nNewCol++
      Write-Host ("[write] tab {0}：新增列 {1} = 送达时间" -f $s.name, $colDt)
      $lastCol = $colDt
    }

    foreach ($r in $s.rows) {
      $row = $r.row
      if ($r.dw_chg -and $r.dw_new) {
        $ws.Cells.Item($row, $colDw).Value2 = $r.dw_new
        $nDw++
      }
      if ($r.dt_chg -and $r.dt_new) {
        # 写成真日期（不是文本）：转成 Excel 的日期序列值 + 设日期格式。
        # ⚠ 本机 Excel COM 是 12.0（Excel 2007），Value2 直接吃 Double 会报
        #   "Unable to cast object of type 'System.Double' to type 'System.String'"，
        #   必须先显式 [double] 转换再赋值。
        $dt = [datetime]::ParseExact($r.dt_new, 'yyyy-MM-dd', $null)
        $cell = $ws.Cells.Item($row, $colDt)
        $cell.NumberFormat = 'yyyy-mm-dd'
        $cell.Value2 = [double]$dt.ToOADate()
        $nDt++
      }
    }
  }

  $wb.Save()
  Write-Host ("[write] 已保存：Delivery window 写 {0} 行 | 送达时间 写 {1} 行 | 新增列 {2} 个" -f $nDw, $nDt, $nNewCol)

  # ---- 写后校验：抽查每个 tab 的第一行写入结果 ----
  Write-Host '[write] 写后校验（抽查每个 tab 第一条写入行）：'
  foreach ($s in $pl.sheets) {
    $ws2 = $wb.Worksheets.Item($s.name)
    $first = $s.rows[0]
    $row = $first.row
    $h2 = @{}
    for ($c = 1; $c -le 40; $c++) {
      $v = $ws2.Cells.Item(1, $c).Text
      if ($v) { $h2[[string]$v] = $c }
    }
    $cdw = $h2['Delivery window']
    $cdt = $h2['送达时间']
    $dwTxt = '(无列)'
    if ($cdw) { $dwTxt = [string]$ws2.Cells.Item($row, $cdw).Text }
    $dtTxt = '(无列)'
    if ($cdt) { $dtTxt = [string]$ws2.Cells.Item($row, $cdt).Text }
    Write-Host ("     [{0}] 行{1}: DW='{2}' (期望 '{3}') | DT='{4}' (期望 '{5}')" -f $s.name, $row, $dwTxt, $first.dw_new, $dtTxt, $first.dt_new)
  }

  $ok = $true
}
catch {
  # 写一半失败 → **不保存**，直接丢弃（共享盘保持原样），并报错停下
  $ok = $false
  Write-Warning ("[write] 写入失败，已放弃保存（共享盘未被修改）：" + $_.Exception.Message)
  throw
}
finally {
  if ($wb) { $wb.Close($ok) | Out-Null; [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wb) | Out-Null }
  $xl.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
  [GC]::Collect()
}
Write-Host '[write] DONE'
exit 0
