param([string]$OutDir)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$APP_ID = $env:LX_APP_ID
$APP_SECRET = $env:LX_APP_SECRET
$BASE = 'https://openapi.lingxing.com'
$OUT = if ($OutDir) { $OutDir } else { (Join-Path $PSScriptRoot 'wh_raw') }
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

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
    $sign = Get-AesEcbBase64 (Get-Md5Upper $raw) $APP_ID
    $qs = 'access_token=' + [uri]::EscapeDataString($token) + '&app_key=' + [uri]::EscapeDataString($APP_ID) + '&timestamp=' + $ts + '&sign=' + [uri]::EscapeDataString($sign)
    $json = $params | ConvertTo-Json -Depth 5 -Compress
    $resp = Invoke-RestMethod -Uri ($BASE + $path + '?' + $qs) -Method Post -Body $json -ContentType 'application/json' -TimeoutSec 90
    Start-Sleep -Milliseconds 300
    return $resp
}

$token = Get-LxToken
Write-Host 'token ok'

$all = New-Object System.Collections.ArrayList
$offset = 0
$total = $null
while ($true) {
    $r = Invoke-Lx $token '/erp/sc/routing/data/local_inventory/productList' @{ offset = $offset; length = 1000 }
    if ($null -eq $total) { $total = $r.total; Write-Host ('total=' + $total) }
    $rows = @($r.data)
    if ($rows.Count -eq 0) { break }
    foreach ($x in $rows) { [void]$all.Add($x) }
    Write-Host ('  fetched=' + $all.Count)
    if ($total -and $all.Count -ge $total) { break }
    if ($all.Count -gt 20000) { break }
    $offset = $all.Count
}
Write-Host ('rows=' + $all.Count)
if ($all.Count -gt 0) {
    Write-Host ('keys=' + (($all[0].PSObject.Properties.Name) -join ','))
    $all[0] | ConvertTo-Json -Depth 3 -Compress | Write-Host
}
[System.IO.File]::WriteAllText((Join-Path $OUT 'local_products.json'), (@{ total = $total; rows = $all } | ConvertTo-Json -Depth 12), (New-Object System.Text.UTF8Encoding($false)))
Write-Host ('saved -> ' + (Join-Path $OUT 'local_products.json'))
