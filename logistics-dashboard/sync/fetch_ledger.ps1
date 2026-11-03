param([string]$AsOf)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$APP_ID = $env:LX_APP_ID; $APP_SECRET = $env:LX_APP_SECRET; $BASE='https://openapi.lingxing.com'
function Get-Md5Upper([string]$s){$m=[System.Security.Cryptography.MD5]::Create();(($m.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($s))|ForEach-Object{$_.ToString('x2')}) -join '').ToUpper()}
function Get-AesEcbBase64([string]$p,[string]$k){$a=[System.Security.Cryptography.Aes]::Create();$a.Mode='ECB';$a.Padding='PKCS7';$a.Key=[System.Text.Encoding]::UTF8.GetBytes($k);$e=$a.CreateEncryptor();$d=[System.Text.Encoding]::UTF8.GetBytes($p);[Convert]::ToBase64String($e.TransformFinalBlock($d,0,$d.Length))}
function Get-LxToken{$b='appId='+[uri]::EscapeDataString($APP_ID)+'&appSecret='+[uri]::EscapeDataString($APP_SECRET);(Invoke-RestMethod -Uri ($BASE+'/api/auth-server/oauth/access-token') -Method Post -Body $b -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 30).data.access_token}
function Invoke-Lx3([string]$token,[string]$epPath,[string[]]$sellerIds,[hashtable]$rest){
  $json='['+(($sellerIds|ForEach-Object{'"'+$_+'"'}) -join ',')+']'
  $sp=@{sellerIds=$json}; foreach($k in $rest.Keys){$sp[$k]=$rest[$k]}
  $ts=[string][int][double]::Parse(([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()))
  $sp['access_token']=$token; $sp['app_key']=$APP_ID; $sp['timestamp']=$ts
  $raw=(@($sp.Keys|Sort-Object)|ForEach-Object{$_+'='+$sp[$_]}) -join '&'
  $sign=Get-AesEcbBase64 (Get-Md5Upper $raw) $APP_ID
  $qs='access_token='+[uri]::EscapeDataString($token)+'&app_key='+[uri]::EscapeDataString($APP_ID)+'&timestamp='+$ts+'&sign='+[uri]::EscapeDataString($sign)
  $body=@{sellerIds=$sellerIds}; foreach($k in $rest.Keys){$body[$k]=$rest[$k]}
  $r=$null
  for($try=1;$try -le 4;$try++){
    try{$r=Invoke-RestMethod -Uri ($BASE+$epPath+'?'+$qs) -Method Post -Body ($body|ConvertTo-Json -Depth 8 -Compress) -ContentType 'application/json' -TimeoutSec 120}catch{return @{code=-1;message=$_.Exception.Message}}
    if($r.code -eq '103' -or $r.code -eq 103){ Write-Host ("  rate-limited code=103, retry {0}/4" -f $try); Start-Sleep -Seconds (3*$try); $r=$null; continue }
    break
  }
  if($null -eq $r){ return @{code=103;message='请求过于频繁，重试 4 次仍失败'} }
  Start-Sleep -Milliseconds 200; return $r
}
$token=Get-LxToken
# 领星店铺 ID（sellerId）列表：从环境变量读取，逗号分隔。取不到时退化为占位值。
$SELL_RAW = if ($env:LX_SELLER_IDS) { $env:LX_SELLER_IDS } else { 'SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER,SELLER_ID_PLACEHOLDER' }
$SELL = @($SELL_RAW -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$EP='/cost/center/ods/summary/query'
$OUTDIR=Join-Path $PSScriptRoot 'wh_raw'

function Save-Json($obj,$file){
  $p=Join-Path $OUTDIR $file
  $json=$obj|ConvertTo-Json -Depth 6 -Compress
  [System.IO.File]::WriteAllText($p,$json,(New-Object System.Text.UTF8Encoding($false)))
  Write-Host ("SAVED {0} -> {1} ({2} KB)" -f $file,$p,[math]::Round((Get-Item $p).Length/1024,1))
}

# 失败标记：任何一页请求失败（含网络异常 code=-1）都不许静默丢页
$script:fetchFailed=@()

# ---- 窗口自动滚动：CLOSE=AsOf，OPEN6=AsOf-180天，OPEN3=AsOf-90天 ----
if([string]::IsNullOrWhiteSpace($AsOf)){ $AsOf=(Get-Date).ToString('yyyy-MM-dd') }
$asOfDate=[datetime]::ParseExact($AsOf,'yyyy-MM-dd',[System.Globalization.CultureInfo]::InvariantCulture)
$open6=$asOfDate.AddDays(-180)
$open3=$asOfDate.AddDays(-90)
$curMonthStart=New-Object datetime($asOfDate.Year,$asOfDate.Month,1)
function EndOfMonth([datetime]$d){ (New-Object datetime($d.Year,$d.Month,1)).AddMonths(1).AddDays(-1) }
Write-Host ("WINDOW asOf={0} open3={1} open6={2}" -f $asOfDate.ToString('yyyy-MM-dd'),$open3.ToString('yyyy-MM-dd'),$open6.ToString('yyyy-MM-dd'))

# ---- 日维度（边界日 + 当月）：OPEN6..月末, OPEN3..月末, 当月1日..AsOf ----
$ranges=@(
  @($open6.ToString('yyyy-MM-dd'), (EndOfMonth $open6).ToString('yyyy-MM-dd')),
  @($open3.ToString('yyyy-MM-dd'), (EndOfMonth $open3).ToString('yyyy-MM-dd')),
  @($curMonthStart.ToString('yyyy-MM-dd'), $asOfDate.ToString('yyyy-MM-dd'))
)
# ---- 月维度（完整月）：OPEN6 所在月 ~ 上一整月 ----
$months=@()
$cur=New-Object datetime($open6.Year,$open6.Month,1)
$lastClosed=$curMonthStart.AddDays(-1)
$mEnd=New-Object datetime($lastClosed.Year,$lastClosed.Month,1)
while($cur -le $mEnd){ $months+=$cur.ToString('yyyy-MM'); $cur=$cur.AddMonths(1) }
$all=New-Object System.Collections.ArrayList
foreach($m in $months){
  $off=0
  while($true){
    $r=Invoke-Lx3 $token $EP $SELL @{queryType=1;startDate=$m;endDate=$m;disposition='01';offset=$off;length=1000}
    if([int]$r.code -ne 1){ Write-Host ("month {0} offset {1} FAIL code={2} msg={3}" -f $m,$off,$r.code,$r.message); $script:fetchFailed+=("month {0} offset {1} code={2} {3}" -f $m,$off,$r.code,$r.message); break }
    $tot=[int]$r.data.total; $recs=@($r.data.records)
    foreach($x in $recs){ [void]$all.Add($x) }
    $off += $recs.Count
    Write-Host ("month {0} offset {1} got {2}/{3}" -f $m,$off,$recs.Count,$tot)
    if($recs.Count -eq 0 -or $off -ge $tot){ break }
  }
}
$allD=New-Object System.Collections.ArrayList
foreach($rg in $ranges){
  $s=$rg[0]; $e=$rg[1]; $off=0
  while($true){
    $r=Invoke-Lx3 $token $EP $SELL @{queryType=2;startDate=$s;endDate=$e;disposition='01';offset=$off;length=1000}
    if([int]$r.code -ne 1){ Write-Host ("day {0}..{1} offset {2} FAIL code={3} msg={4}" -f $s,$e,$off,$r.code,$r.message); $script:fetchFailed+=("day {0}..{1} offset {2} code={3} {4}" -f $s,$e,$off,$r.code,$r.message); break }
    $tot=[int]$r.data.total; $recs=@($r.data.records)
    foreach($x in $recs){ [void]$allD.Add($x) }
    $off += $recs.Count
    Write-Host ("day {0}..{1} offset {2} got {3}/{4}" -f $s,$e,$off,$recs.Count,$tot)
    if($recs.Count -eq 0 -or $off -ge $tot){ break }
  }
}

$monthObj=@{kind='month';months=$months;total=$all.Count;records=$all}
$dayObj=@{kind='day';asOf=$asOfDate.ToString('yyyy-MM-dd');open3=$open3.ToString('yyyy-MM-dd');open6=$open6.ToString('yyyy-MM-dd');ranges=$ranges;total=$allD.Count;records=$allD}

if($script:fetchFailed.Count -gt 0){
  # 有分页失败：只落 .partial 备查，绝不覆盖上一次的好数据；退出码非 0 让流水线停在这里
  Write-Host ("PARTIAL: {0} 个分页失败" -f $script:fetchFailed.Count)
  foreach($f in $script:fetchFailed){ Write-Host ("  FAIL {0}" -f $f) }
  Save-Json $monthObj 'fba_ledger_month.json.partial'
  Save-Json $dayObj   'fba_ledger_day.json.partial'
  Write-Host "FAILED"
  exit 1
}

Save-Json $monthObj 'fba_ledger_month.json'
Save-Json $dayObj   'fba_ledger_day.json'
Write-Host "DONE"
