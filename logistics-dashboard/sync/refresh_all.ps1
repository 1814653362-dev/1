# refresh_all.ps1 —— 一条命令刷新「供应链货流」站点全部领星数据
# 用法： powershell -NoProfile -ExecutionPolicy Bypass -File refresh_all.ps1 [-SkipFetch] [-SkipPublish]
# 流程：领星抓取 → 快照/索引构建 → 主页注入 → 资料库记录刷新 → 发布 → 校验
# 注意：输出改为「先整体捕获再取末尾 N 行」。旧写法用 | Select-Object -First N 会在截断时
#       掐断上游 python 进程，导致 $LASTEXITCODE=-1 被误判为步骤失败（2026-10-28 踩过）。
param([switch]$SkipPublish, [switch]$SkipFetch)

$ErrorActionPreference = 'Stop'
$WS = $PSScriptRoot
$PY = 'python'
function Step($name, $cmd, [int]$tail = 0) {
  Write-Host ("`n=== [{0}] {1} ===" -f (Get-Date -Format 'HH:mm:ss'), $name)
  $out = Invoke-Expression $cmd
  $code = $LASTEXITCODE
  $lines = @($out)
  if ($tail -gt 0 -and $lines.Count -gt $tail) { $lines = $lines | Select-Object -Last $tail }
  foreach ($l in $lines) { Write-Host $l }
  if ($code -ne 0) { throw ("步骤失败：$name (exit=$code)") }
}

if (-not $SkipFetch) {
  Step '领星-仓库/店铺/库存明细' "& powershell -NoProfile -ExecutionPolicy Bypass -File `"$WS\fetch_wh.ps1`"" 3
  Step '领星-本地仓商品清单'   "& powershell -NoProfile -ExecutionPolicy Bypass -File `"$WS\fetch_products.ps1`"" 2
  Step '领星-FBA出库明细'      "& powershell -NoProfile -ExecutionPolicy Bypass -File `"$WS\fetch_ship.ps1`"" 2
  Step '领星-库存分类账(月+日)' "& powershell -NoProfile -ExecutionPolicy Bypass -File `"$WS\fetch_ledger.ps1`"" 4
  Step '库存分类账历史源' "& `"$PY`" `"$WS\lx_ledger.py`"" 8
}

Step '国内仓快照'  "& `"$PY`" `"$WS\build_wh_snapshot.py`" `"$WS\wh_raw`" `"$WS\wh_raw\wh_snapshot.json`"" 8
Step '主页注入__WH' "& `"$PY`" `"$WS\inject_wh_inplace.py`"" 3
Step 'FBA SPU'      "& `"$PY`" `"$WS\build_spu2.py`"" 8
Step '国内仓 SPU'   "& `"$PY`" `"$WS\build_spu_local.py`"" 3
Step '国内仓SKU索引' "& `"$PY`" `"$WS\build_sku_index.py`"" 3
Step 'FBA SKU索引'  "& `"$PY`" `"$WS\build_fba_sku_index2.py`"" 9
Step '库容计算'     "& `"$PY`" `"$WS\build_vol_v5.py`"" 2
Step '库容注入主页' "& `"$PY`" `"$WS\patch_vol_v5.py`"" 6
# 必须在 patch_vol_v5.py 之后跑：patch_vol_v5 会整段替换「国内仓库容占用 → FBA 合并卡」之间的 CSS
Step 'FBA库龄×款号数据' "& `"$PY`" `"$WS\build_age_spu.py`"" 3
Step 'FBA库龄×款号注入' "& `"$PY`" `"$WS\patch_age_spu_fba.py`"" 4
Step 'SPU运营标注'   "& `"$PY`" `"$WS\patch_spu_owner.py`"" 4
Step 'FBA指标风格统一' "& `"$PY`" `"$WS\patch_fba_kpi_style.py`"" 3
Step '资料库发货记录' "& powershell -NoProfile -ExecutionPolicy Bypass -File `"$WS\refresh_data.ps1`" -PageUrl '$env:WB_PAGE_URL' -OutDir `"$WS\shandi-v5`"" 4
Step '同步共享盘发货记录' "& powershell -NoProfile -ExecutionPolicy Bypass -File `"$WS\sync_share_xlsx.ps1`"" 2
Step '生成发货记录主表' "& `"$PY`" `"$WS\build_records_from_share.py`"" 6

Step '归档FBA库龄快照' "& `"$PY`" `"$WS\archive_wh_snapshot.py`"" 2
Step 'FBA周趋势计算' "& `"$PY`" `"$WS\build_trend.py`"" 6
Step 'FBA趋势交互注入' "& `"$PY`" `"$WS\patch_trend_ui.py`"" 4
Step '店级库龄趋势数据' "& `"$PY`" `"$WS\build_age_trend.py`"" 6
Step '店级库龄趋势注入' "& `"$PY`" `"$WS\patch_age_trend_ui.py`"" 4
# 到仓进度补丁必须排在最后：前面任何步骤若整段替换 ⑥ SKU 批次面板的 JS，这里兜底补回
Step '到仓进度修复'   "& `"$PY`" `"$WS\patch_sku_progress.py`"" 3

if (-not $SkipPublish) {
  Step '发布上线' "& `"$PY`" `"$WS\publish_update.py`"" 6
  Step '线上校验' "& `"$PY`" `"$WS\verify_page.py`" 'https://bok46b7dgj8iz.space.mcode.cn/index.html'" 20
} else {
  Step '本地校验' "& `"$PY`" `"$WS\verify_page.py`"" 20
}
Write-Host "`nDONE"
