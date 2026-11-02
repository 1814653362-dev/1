param([string]$OutDir, [int]$Days = 400)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$APP_ID = $env:LX_APP_ID
$APP_SECRET = $env:LX_APP_SECRET
$BASE = 'https://openapi.lingxing.com'
if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'wh_raw' }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-Md5Upper([string]$s) {
    $md5 = [System.Security.Cryptography.MD5]::Create()
    (($md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($s)) | ForEach-Object { $_.ToString('x2') }) -join '').ToUpper()
}
function Get-AesEcbBase64([string]$plain, [string]$keyStr) {
    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.Mode = [System.Security.Cryptography.CipherMode]::ECB
    $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
    $aes.Key = [System.Text.Encoding]::UTF8.GetBytes($keyStr)
    $enc = $aes.CreateEncryptor()
    $d = [System.Text.Encoding]::UTF8.GetBytes($plain)
    [Convert]::ToBase64String($enc.TransformFinalBlock($d, 0, $d.Length))
}
function Get-LxToken {
    $body = 'appId=' + [uri]::EscapeDataString($APP_ID) + '&appSecret=' + [uri]::EscapeDataString($APP_SECRET)
    (Invoke-RestMethod -Uri ($BASE + '/api/auth-server/oauth/access-token') -Method Post -Body $body -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 30).data.access_token
}
function Invoke-Lx([string]$token, [string]$path, [hashtable]$params) {
    $ts = [string][int][double]::Parse(([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()))
    $sp = @{}; foreach ($k in $params.Keys) { $sp[$k] = $params[$k] }
    $sp['access_token'] = $token; $sp['app_key'] = $APP_ID; $sp['timestamp'] = $ts
    $raw = (@($sp.Keys | Sort-Object) | ForEach-Object { $_ + '=' + $sp[$_] }) -join '&'
    $sign = Get-AesEcbBase64 (Get-Md5Upper $raw) $APP_ID
    $qs = 'access_token=' + [uri]::EscapeDataString($token) + '&app_key=' + [uri]::EscapeDataString($APP_ID) + '&timestamp=' + $ts + '&sign=' + [uri]::EscapeDataString($sign)
    $bp = @{}; foreach ($k in $params.Keys) { $bp[$k] = $params[$k] }
    $json = $bp | ConvertTo-Json -Depth 5 -Compress
    try {
        $resp = Invoke-RestMethod -Uri ($BASE + $path + '?' + $qs) -Method Post -Body $json -ContentType 'application/json' -TimeoutSec 90
    } catch {
        return @{ code = -1; message = $_.Exception.Message; data = $null }
    }
    Start-Sleep -Milliseconds 400
    return $resp
}

$token = Get-LxToken
$sl = Invoke-Lx $token '/erp/sc/data/seller/lists' @{}
$sids = (@($sl.data) | ForEach-Object { $_.sid }) -join ','
Write-Host ('店铺 sid: ' + $sids)

$end = (Get-Date).ToString('yyyy-MM-dd')
$start = (Get-Date).AddDays(-$Days).ToString('yyyy-MM-dd')
Write-Host ("出库明细窗口 $start ~ $end")

$all = New-Object System.Collections.ArrayList
$offset = 0
$total = $null
while ($true) {
    $r = Invoke-Lx $token '/erp/sc/data/fba_report/shipmentList' @{ sid = $sids; start_date = $start; end_date = $end; offset = $offset; length = 200 }
    if ($r.code -ne 0 -and $r.code -ne '0') { throw ("shipmentList -> code=" + $r.code + ' ' + $r.message) }
    $list = @($r.data.list)
    if ($null -eq $total) { $total = $r.data.total; Write-Host ('total=' + $total) }
    if ($list.Count -eq 0) { break }
    foreach ($x in $list) { [void]$all.Add($x) }
    Write-Host ('fetched=' + $all.Count)
    if ($total -and $all.Count -ge $total) { break }
    if ($all.Count -ge 20000) { break }
    $offset = $all.Count
}
Write-Host ('shipments=' + $all.Count)
[System.IO.File]::WriteAllText((Join-Path $OutDir 'shipments.json'), ($all | ConvertTo-Json -Depth 30), (New-Object System.Text.UTF8Encoding($false)))
Write-Host ('saved ' + (Join-Path $OutDir 'shipments.json'))
