param(
  [string]$Plan,
  [string]$Src,
  [switch]$DryRun,
  [switch]$SkipBackup
)

# unify_share_formats.ps1 —— 共享盘《发货记录.xlsx》日期/状态列格式统一（2026-11-02 用户定）
#
# 口径：
#   · 「送达时间」列 → 全部非空值统一成「真 Excel 日期 + 数字格式 yyyy-mm-dd」
#       已是日期 → 值不动只统一格式；数字/文本型月.日 → 按所在 tab 年份转真日期；
#       '#N/A' 等错误文本 → 清空；解析不出来 → 不动（计划里已单列）
#   · 「Delivery window」「发货日期」「到港日期」「开船日期」→ 值一个不动，数字格式统一 '@'
#   · 其它列的格式一律不动
#   · 写回前把共享盘当前文件复制一份到工作目录（同名「填前备份」覆盖旧的，只留一份）
#   · 共享盘被 Excel 打开 → 报错停下，不硬写、不重试冲撞
#
# 坑（沿用 write_share_lx.ps1 的经验）：
#   · 本机 Excel 12.0，Value2 直接吃 Double 会报 "Unable to cast System.Double to System.String"，
#     必须先 [double] 转换再赋值
#   · 本簿有 1573 个公式，其中大量外部工作簿 VLOOKUP（[20]价格表 / [13]Sheet5 / [3]货件详情 …），
#     自动重算可能把缓存值变成 #REF!。所以打开前把 Calculation 设成手动（xlCalculationManual），
#     全程不 Calculate，让缓存值原样保留。
#   · 异常时绝不 Save（用 $ok 标志，finally 里 Close($ok)）
#
# 用法： powershell -NoProfile -ExecutionPolicy Bypass -File unify_share_formats.ps1 [-DryRun]

$ErrorActionPreference = 'Stop'
$WS = $PSScriptRoot
if (-not $Plan) { $Plan = Join-Path $WS 'data\fmt_unify_plan.json' }
if (-not (Test-Path -LiteralPath $Plan)) { throw "计划不存在：$Plan" }

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
$Src = if ($Src) { $Src } else { Find-Src }
if (-not $Src) { throw '共享盘发货记录找不到（已试 \\Sd-fwq\F\物流部 与 W:\物流部）' }
Write-Host ("[fmt] SRC = " + $Src)

# ---------- 2. 锁检测：被 Excel 打开就报错停下，绝不硬写 ----------
try {
  $fs = [System.IO.File]::Open($Src, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
  $fs.Close()
  Write-Host '[fmt] 锁检测：文件未被占用'
} catch {
  throw ("共享盘发货记录正被占用（很可能 Excel 打开中），已停止、未做任何修改：" + $_.Exception.Message)
}

# ---------- 3. 备份（整份复制到工作目录，同名覆盖，只留一份）----------
# -SkipBackup：补跑（只补格式、值不再动）时用，保留第一次跑留下的「填前备份」原件
if (-not $SkipBackup) {
  $bak = Join-Path $WS 'share_backup_before_lx.xlsx'
  Copy-Item -LiteralPath $Src -Destination $bak -Force
  Write-Host ("[fmt] 填前备份 → " + $bak + " (" + [math]::Round((Get-Item $bak).Length/1KB,1) + " KB)")
} else {
  Write-Host '[fmt] -SkipBackup：保留工作目录里已有的「填前备份」原件，不覆盖'
}

# ---------- 4. 读计划 ----------
$pl = Get-Content -Raw -Encoding UTF8 -LiteralPath $Plan | ConvertFrom-Json
if ($DryRun) {
  Write-Host ('[fmt] DryRun：计划 {0} 个 tab，不做任何写入' -f $pl.tabs.Count)
  exit 0
}

# ---------- 5. Excel COM 写入 ----------
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.EnableEvents = $false
$xl.AskToUpdateLinks = $false
$wb = $null
$log = @()
try {
  # 手动计算：外部链接公式不重算，缓存值原样保留（改格式不该改任何公式结果）
  $wb0 = $xl.Workbooks.Add()
  try { $xl.Calculation = -4135 } catch { Write-Warning '[fmt] 设置手动计算失败，继续（保存后靠值比对兜底）' }
  $wb0.Close($false) | Out-Null

  $wb = $xl.Workbooks.Open($Src, 0, $false)
  $nSetDate = 0; $nEnsure = 0; $nClear = 0; $nUnres = 0; $nFmt = 0

  foreach ($s in $pl.tabs) {
    # ⚠ 变量名不能叫 $ws（PowerShell 变量不区分大小写，会把 $WS 工作目录覆盖成 COM 对象）
    $sh = $wb.Worksheets.Item($s.name)
    $used = $sh.UsedRange
    $lastCol = $used.Column + $used.Columns.Count - 1
    $lastRow = $used.Row + $used.Rows.Count - 1

    # 按**列名**定位表头（各 tab 列位不同，绝不按列序）
    $hdr = @{}
    for ($c = 1; $c -le $lastCol; $c++) {
      $v = $sh.Cells.Item(1, $c).Text
      if ($v) { $hdr[[string]$v] = $c }
    }

    foreach ($col in $s.cols) {
      $ci = $hdr[[string]$col.name]
      if (-not $ci) {
        Write-Warning ("[fmt] tab {0}：没有「{1}」列，跳过" -f $s.name, $col.name)
        continue
      }
      if ($col.name -eq '送达时间') {
        foreach ($cell in $col.cells) {
          $r = $cell.row
          $c2 = $sh.Cells.Item($r, $ci)
          switch ([string]$cell.action) {
            'set_date' {
              $dt = [datetime]::ParseExact([string]$cell.iso, 'yyyy-MM-dd', $null)
              $c2.NumberFormat = 'yyyy-mm-dd'
              $c2.Value2 = [double]$dt.ToOADate()
              $nSetDate++
              $log += [pscustomobject]@{ tab=$s.name; col='送达时间'; row=$r;
                before_type=$cell.before_type; before_fmt=$cell.before_fmt; before_val=$cell.before_val;
                after_type='日期值'; after_fmt='yyyy-mm-dd'; after_val=[string]$cell.iso; action='月.日转真日期' }
            }
            'ensure_fmt' {
              $c2.NumberFormat = 'yyyy-mm-dd'
              $nEnsure++
              $log += [pscustomobject]@{ tab=$s.name; col='送达时间'; row=$r;
                before_type=$cell.before_type; before_fmt=$cell.before_fmt; before_val=$cell.before_val;
                after_type='日期值'; after_fmt='yyyy-mm-dd'; after_val=$cell.before_val; action='真日期值统一格式' }
            }
            'clear' {
              $c2.ClearContents() | Out-Null
              $nClear++
              $log += [pscustomobject]@{ tab=$s.name; col='送达时间'; row=$r;
                before_type=$cell.before_type; before_fmt=$cell.before_fmt; before_val=$cell.before_val;
                after_type='空'; after_fmt='yyyy-mm-dd'; after_val=''; action='错误文本清空' }
            }
            'unresolved' {
              $nUnres++
              $log += [pscustomobject]@{ tab=$s.name; col='送达时间'; row=$r;
                before_type=$cell.before_type; before_fmt=$cell.before_fmt; before_val=$cell.before_val;
                after_type=$cell.before_type; after_fmt=$cell.before_fmt; after_val=$cell.before_val; action='解析不出·保持不动' }
            }
          }
        }
        # 整列格式统一（逐格赋值）
        # ⚠ 实测坑（2026-11-02）：本机 Excel 12.0 对 **区域** 赋 Range.NumberFormat
        #   只对部分单元格生效（10月 U 列 132 格里只有 19 格变了），
        #   逐格赋值 100% 可靠，且不会改值的类型（10.17 仍是 Double、显示仍是 10.17）。
        for ($r = 2; $r -le $col.last_row; $r++) {
          $sh.Cells.Item($r, $ci).NumberFormat = 'yyyy-mm-dd'
        }
        $nFmt += ($col.last_row - 1)
      }
      else {
        # 只改数字格式，值一个不动（逐格赋值）
        $skip = @($col.skip_rows)
        for ($r = 2; $r -le $col.last_row; $r++) {
          if ($skip -contains $r) { continue }
          $sh.Cells.Item($r, $ci).NumberFormat = '@'
        }
        $nFmt += ($col.last_row - 1)
        $log += [pscustomobject]@{ tab=$s.name; col=$col.name; row=('2-' + $col.last_row);
          before_type='（原样）'; before_fmt='（混合）'; before_val='（未动）';
          after_type='（原样）'; after_fmt='@'; after_val='（未动）'; action='整列数字格式统一为文本' }
      }
    }
  }

  $wb.Save()
  Write-Host ("[fmt] 已保存：转真日期 {0} | 统一格式(已是日期) {1} | 清空错误文本 {2} | 解析不出 {3} | 格式格合计 {4}" -f $nSetDate, $nEnsure, $nClear, $nUnres, $nFmt)

  $ok = $true
}
catch {
  $ok = $false
  Write-Warning ("[fmt] 写入失败，已放弃保存（共享盘未被修改）：" + $_.Exception.Message)
  throw
}
finally {
  if ($wb) { $wb.Close($ok) | Out-Null; [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wb) | Out-Null }
  $xl.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
  [GC]::Collect()
}

# ---------- 6. 落改动清单 ----------
$res = Join-Path $WS 'data\fmt_unify_result.json'
$log | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $res -Encoding UTF8
Write-Host ("[fmt] 改动清单 → " + $res + "（" + $log.Count + " 条）")
Write-Host '[fmt] DONE'
exit 0
