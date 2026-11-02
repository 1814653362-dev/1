param([string]$OutDir)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$APP_ID = $env:LX_APP_ID
$APP_SECRET = $env:LX_APP_SECRET
$BASE = 'https://openapi.lingxing.com'
$OUT = $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $OUT 'wh_raw' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-Md5Upper([string]$s) {
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($s)
    $hash = $md5.ComputeHash($bytes)
    (($hash | ForEach-Object { $_.ToString('x2') }) -join '').ToUpper()
}

function Get-AesEcbBase64([string]$plain, [string]$keyStr) {
    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = [System.Security.Cryptography.CipherMode]::ECB
    $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
    $aes.Key = [System.Text.Encoding]::UTF8.GetBytes($keyStr)
    $enc = $aes.CreateEncryptor()
    $data = [System.Text.Encoding]::UTF8.GetBytes($plain)
    $out = $enc.TransformFinalBlock($data, 0, $data.Length)
    [Convert]::ToBase64String($out)
}

function Get-LxToken {
    $body = 'appId=' + [uri]::EscapeDataString($APP_ID) + '&appSecret=' + [uri]::EscapeDataString($APP_SECRET)
    $r = Invoke-RestMethod -Uri ($BASE + '/api/auth-server/oauth/access-token') -Method Post -Body $body -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 30
    if ($r.code -ne '200' -and $r.code -ne 200) { throw ("token failed: " + ($r | ConvertTo-Json -Compress)) }
    return $r.data.access_token
}

function Invoke-Lx([string]$token, [string]$path, [hashtable]$params) {
    $ts = [string][int][double]::Parse(([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()))
    $signParams = @{}
    foreach ($k in $params.Keys) { $signParams[$k] = $params[$k] }
    $signParams['access_token'] = $token
    $signParams['app_key'] = $APP_ID
    $signParams['timestamp'] = $ts
    $keys = @($signParams.Keys | Sort-Object)
    $raw = ($keys | ForEach-Object { $_ + '=' + $signParams[$_] }) -join '&'
    $m = Get-Md5Upper $raw
    $sign = Get-AesEcbBase64 $m $APP_ID
    $qs = 'access_token=' + [uri]::EscapeDataString($token) + '&app_key=' + [uri]::EscapeDataString($APP_ID) + '&timestamp=' + $ts + '&sign=' + [uri]::EscapeDataString($sign)
    $bodyParams = @{}
    foreach ($k in $params.Keys) { $bodyParams[$k] = $params[$k] }
    $json = $bodyParams | ConvertTo-Json -Depth 5 -Compress
    $resp = $null
    for ($try = 1; $try -le 4; $try++) {
        $resp = Invoke-RestMethod -Uri ($BASE + $path + '?' + $qs) -Method Post -Body $json -ContentType 'application/json' -TimeoutSec 60
        if ($resp.code -eq '103' -or $resp.code -eq 103) {
            Write-Host ("  rate-limited (code=103), retry {0}/4 after {1}s" -f $try, (3 * $try))
            Start-Sleep -Seconds (3 * $try)
            $resp = $null
            continue
        }
        break
    }
    Start-Sleep -Milliseconds 400
    if ($null -eq $resp) { throw ("$path -> code=103 请求过于频繁，重试 4 次仍失败") }
    if ($resp.code -ne 0 -and $resp.code -ne '0') { throw ("$path -> code=" + $resp.code + ' ' + $resp.message + ' ' + $resp.msg) }
    return $resp
}

Write-Host '== 获取 token =='
$token = Get-LxToken
Write-Host ('token OK: ' + $token.Substring(0, [Math]::Min(12, $token.Length)) + '...')

Write-Host '== [1] 本地仓列表 =='
$wh = Invoke-Lx $token '/erp/sc/data/local_inventory/warehouse' @{ type = 1; sub_type = 2; is_delete = 0; offset = 0; length = 1000 }
Write-Host ('total=' + $wh.total + ' count=' + @($wh.data).Count)
$wh.data | ForEach-Object { Write-Host ("  wid=" + $_.wid + ' ' + $_.name) }
[System.IO.File]::WriteAllText((Join-Path $OutDir 'wh_local.json'), ($wh | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding($false)))

Write-Host '== [2] 店铺列表 =='
$sl = Invoke-Lx $token '/erp/sc/data/seller/lists' @{}
Write-Host ('sellers=' + @($sl.data).Count)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'sellers.json'), ($sl | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding($false)))

Write-Host '== [3] 本地仓库存明细 =='
$widStr = (@($wh.data) | ForEach-Object { $_.wid }) -join ','
$all = New-Object System.Collections.ArrayList
$offset = 0
$total = $null
while ($true) {
    $r = Invoke-Lx $token '/erp/sc/routing/data/local_inventory/inventoryDetails' @{ wid = $widStr; offset = $offset; length = 800 }
    if ($null -eq $total) { $total = $r.total; Write-Host ('  total=' + $total) }
    $rows = @($r.data)
    if ($rows.Count -eq 0) { break }
    foreach ($x in $rows) { [void]$all.Add($x) }
    Write-Host ('  fetched=' + $all.Count)
    if ($total -and $all.Count -ge $total) { break }
    $offset = $all.Count
}
Write-Host ('  rows=' + $all.Count)
if ($all.Count -gt 0) { Write-Host ('  keys=' + (($all[0].PSObject.Properties.Name) -join ',')) }
[System.IO.File]::WriteAllText((Join-Path $OutDir 'local_inventory.json'), (@{ total = $total; rows = $all } | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding($false)))

Write-Host '== [4] FBA 库存明细 =='
$fba = New-Object System.Collections.ArrayList
$fo = 0
$ftotal = $null
while ($true) {
    $r = Invoke-Lx $token '/basicOpen/openapi/storage/fbaWarehouseDetail' @{ offset = $fo; length = 1000; is_hide_zero_stock = 0; is_cost_page = 0; is_parant_asin_merge = 0; is_contain_del_ls = 0 }
    if ($null -eq $ftotal) { $ftotal = $r.total; Write-Host ('  total=' + $ftotal) }
    $rows = @($r.data)
    if ($rows.Count -eq 0) { break }
    foreach ($x in $rows) { [void]$fba.Add($x) }
    Write-Host ('  fetched=' + $fba.Count)
    if ($ftotal -and $fba.Count -ge $ftotal) { break }
    if ($fba.Count -ge 40000) { break }
    $fo = $fba.Count
}
Write-Host ('  rows=' + $fba.Count)
if ($fba.Count -gt 0) { Write-Host ('  keys=' + (($fba[0].PSObject.Properties.Name) -join ',')) }
[System.IO.File]::WriteAllText((Join-Path $OutDir 'fba_inventory.json'), (@{ total = $ftotal; rows = $fba } | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding($false)))

Write-Host ('DONE -> ' + $OutDir)
