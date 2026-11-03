$ErrorActionPreference = 'Stop'
# 从共享盘同步「发货记录」到本地 data/（Windows 下 Python 读不了共享盘的 UTF-8 中文名，故由 PowerShell 拷贝）
# 源： 共享盘根目录\发货记录.xlsx   （用户口径：共享盘发货记录）
# 落： data\shipments_share.xlsx  （构建脚本读这个 ASCII 名的本地副本）
$WS = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$Dst = Join-Path $WS 'data\shipments_share.xlsx'

function Find-Src {
  $roots = @($env:WB_SHARE_ROOT, 'W:\物流部') | Where-Object { $_ } | Where-Object { $_ }
  foreach ($r in $roots) {
    if (-not (Test-Path -LiteralPath $r)) { continue }
    # 优先精确名，再退到 发货记录*.xlsx
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
if (-not $Src) { throw '共享盘发货记录找不到（请设置 WB_SHARE_ROOT 环境变量）' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dst) | Out-Null
Copy-Item -LiteralPath $Src -Destination $Dst -Force
$f = Get-Item -LiteralPath $Dst
Write-Host ("[sync] " + $Src + "  ->  " + $f.FullName + " (" + [math]::Round($f.Length / 1KB, 1) + " KB)")
