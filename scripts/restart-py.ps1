# EA Bot - restart HANYA service Python API (:8000), memuat .env.runtime.
# Dipakai setelah perubahan kode Python agar kode baru aktif tanpa restart
# service lain. Pola sama dengan killweb.ps1 (kill listener + start ulang).
$ErrorActionPreference = 'SilentlyContinue'
$root = 'C:\xampp\htdocs\project-ea-bot'

# 1) Muat .env.runtime
$envMap = @{}
Get-Content (Join-Path $root '.env.runtime') | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#')) { return }
  $i = $line.IndexOf('=')
  if ($i -lt 1) { return }
  $envMap[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim()
}
Write-Host ('[env] ' + $envMap.Count + ' entri dimuat')

# 2) Kill listener :8000 (dan hanya itu)
$pids = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess | Sort-Object -Unique
foreach ($p in $pids) {
  Write-Host ('[kill] pid ' + $p)
  Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# 3) Export env untuk service
$env:MT5_LIVE_DATA = $envMap['MT5_LIVE_DATA']
$env:NINE_ROUTER_BASE_URL = $envMap['NINE_ROUTER_BASE_URL']
if ($envMap['NINE_ROUTER_API_KEY']) { $env:NINE_ROUTER_API_KEY = $envMap['NINE_ROUTER_API_KEY'] }
if ($envMap['TELEGRAM_BOT_TOKEN']) { $env:TELEGRAM_BOT_TOKEN = $envMap['TELEGRAM_BOT_TOKEN'] }
if ($envMap['TELEGRAM_ALLOWED_CHAT_IDS']) { $env:TELEGRAM_ALLOWED_CHAT_IDS = $envMap['TELEGRAM_ALLOWED_CHAT_IDS'] }
$env:MARKET_FEED_ENABLED = $envMap['MARKET_FEED_ENABLED']
$env:MARKET_FEED_SYMBOLS = $envMap['MARKET_FEED_SYMBOLS']
$env:MARKET_FEED_TIMEFRAME = $envMap['MARKET_FEED_TIMEFRAME']
$env:MARKET_FEED_INTERVAL_S = $envMap['MARKET_FEED_INTERVAL_S']
$env:MARKET_FEED_EVENT_COOLDOWN_S = $envMap['MARKET_FEED_EVENT_COOLDOWN_S']
if ($envMap['TELEGRAM_DIGEST_ENABLED']) { $env:TELEGRAM_DIGEST_ENABLED = $envMap['TELEGRAM_DIGEST_ENABLED'] }
if ($envMap['TELEGRAM_DIGEST_WINDOW_S']) { $env:TELEGRAM_DIGEST_WINDOW_S = $envMap['TELEGRAM_DIGEST_WINDOW_S'] }
if ($envMap['TELEGRAM_DIGEST_MAX_ITEMS']) { $env:TELEGRAM_DIGEST_MAX_ITEMS = $envMap['TELEGRAM_DIGEST_MAX_ITEMS'] }

# 4) Start ulang (hidden, detached)
$pyDir = Join-Path $root 'services\python'
$pyExe = Join-Path $pyDir '.venv\Scripts\python.exe'
$logDir = Join-Path $root 'logs'
Start-Process -FilePath $pyExe `
  -ArgumentList '-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', '8000' `
  -WorkingDirectory $pyDir -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logDir 'python.log') `
  -RedirectStandardError (Join-Path $logDir 'python.err.log')
Write-Host '[start] python uvicorn dipanggil'

# 5) Tunggu sehat (maks 45 dtk)
$deadline = (Get-Date).AddSeconds(45)
$ok = $false
while ((Get-Date) -lt $deadline) {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3
    if ($r.StatusCode -eq 200) { $ok = $true; break }
  } catch { Start-Sleep -Milliseconds 800 }
}
if ($ok) { Write-Host '[OK] python :8000 sehat' } else { Write-Host '[X] python :8000 TIDAK sehat - cek logs\python.err.log' }
