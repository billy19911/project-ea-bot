# EA Bot - start semua service (Python API, Node API, Web Dashboard).
# Pakai: start.bat (atau: npm run up). Flag: -NoBrowser
param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Info($m) { Write-Host $m }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Fail($m) { Write-Host $m -ForegroundColor Red }

Info "=== EA Bot - start semua service ==="
Info "Root: $root"

# -- 0. Muat .env.runtime (rahasia lokal; gitignored) ----------------------
$envMap = @{}
$runtimeFile = Join-Path $root '.env.runtime'
if (Test-Path $runtimeFile) {
  Get-Content $runtimeFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $i = $line.IndexOf('=')
    if ($i -lt 1) { return }
    $envMap[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim()
  }
  Info "[env] .env.runtime dimuat ($($envMap.Count) entri)"
} else {
  Warn "[env] .env.runtime belum ada - memakai default"
}

function EnvOr([string]$key, [string]$fallback) {
  if ($envMap.ContainsKey($key) -and $envMap[$key]) { return $envMap[$key] }
  return $fallback
}

# --- Ports (non-default, configurable via .env.runtime) --------------------
$pyPort   = [int](EnvOr 'PY_PORT' '8787')
$nodePort = [int](EnvOr 'NODE_PORT' '3789')
$webPort  = [int](EnvOr 'WEB_PORT' '4321')

# --- Secrets / URLs ---------------------------------------------------------
$jwt      = EnvOr 'JWT_SECRET' ''
$devAuth  = EnvOr 'DEV_AUTH_ENABLED' 'true'
$pyUrl    = EnvOr 'PYTHON_SERVICE_URL' "http://127.0.0.1:$pyPort"
$eaApiUrl = EnvOr 'EA_API_URL' "http://127.0.0.1:$nodePort"
$mt5Live  = EnvOr 'MT5_LIVE_DATA' 'true'
$nineUrl  = EnvOr 'NINE_ROUTER_BASE_URL' 'http://127.0.0.1:20128/v1'
$nineKey  = EnvOr 'NINE_ROUTER_API_KEY' ''
$tgToken  = EnvOr 'TELEGRAM_BOT_TOKEN' ''
$tgChats  = EnvOr 'TELEGRAM_ALLOWED_CHAT_IDS' ''
$feedOn   = EnvOr 'MARKET_FEED_ENABLED' 'false'
$feedSyms = EnvOr 'MARKET_FEED_SYMBOLS' 'XAUUSD'
$feedTf   = EnvOr 'MARKET_FEED_TIMEFRAME' 'M5'
$feedInt  = EnvOr 'MARKET_FEED_INTERVAL_S' '60'
$feedCool = EnvOr 'MARKET_FEED_EVENT_COOLDOWN_S' '300'
$tgPollOn = EnvOr 'TELEGRAM_POLLER_ENABLED' 'false'
$tgPollTok = EnvOr 'TELEGRAM_POLLER_BOT_TOKEN' ''
$tgDigestOn = EnvOr 'TELEGRAM_DIGEST_ENABLED' 'true'
$tgDigestWin = EnvOr 'TELEGRAM_DIGEST_WINDOW_S' '600'
$tgDigestMax = EnvOr 'TELEGRAM_DIGEST_MAX_ITEMS' '15'
$lessonP  = EnvOr 'LESSON_STORE_PATH' ''
$pyApiKey = EnvOr 'PYTHON_API_KEY' ''

if (-not $jwt) {
  $bytes = New-Object byte[] 24
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $jwt = [Convert]::ToBase64String($bytes)
  Add-Content -Path $runtimeFile -Value "JWT_SECRET=$jwt"
  Warn "[env] JWT_SECRET baru dibuat & disimpan ke .env.runtime"
}

function Test-Port([int]$port) {
  $hit = netstat -ano | Select-String -Pattern 'LISTENING' | Select-String -Pattern ":$port\s"
  return [bool]$hit
}

function Wait-Health([string]$url, [int]$timeoutSec = 60) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
      if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
    } catch { Start-Sleep -Milliseconds 800 }
  }
  return $false
}

# Standard env export block reused by every service launch.
function Export-CommonEnv {
  $env:JWT_SECRET = $jwt
  $env:DEV_AUTH_ENABLED = $devAuth
  $env:PYTHON_SERVICE_URL = $pyUrl
  $env:MT5_LIVE_DATA = $mt5Live
  $env:NINE_ROUTER_BASE_URL = $nineUrl
  if ($nineKey) { $env:NINE_ROUTER_API_KEY = $nineKey }
  if ($tgToken) { $env:TELEGRAM_BOT_TOKEN = $tgToken }
  if ($tgChats) { $env:TELEGRAM_ALLOWED_CHAT_IDS = $tgChats }
  $env:MARKET_FEED_ENABLED = $feedOn
  $env:MARKET_FEED_SYMBOLS = $feedSyms
  $env:MARKET_FEED_TIMEFRAME = $feedTf
  $env:MARKET_FEED_INTERVAL_S = $feedInt
  $env:MARKET_FEED_EVENT_COOLDOWN_S = $feedCool
  $env:TELEGRAM_POLLER_ENABLED = $tgPollOn
  if ($tgPollTok) { $env:TELEGRAM_POLLER_BOT_TOKEN = $tgPollTok }
  $env:TELEGRAM_DIGEST_ENABLED = $tgDigestOn
  $env:TELEGRAM_DIGEST_WINDOW_S = $tgDigestWin
  $env:TELEGRAM_DIGEST_MAX_ITEMS = $tgDigestMax
  if ($lessonP) { $env:LESSON_STORE_PATH = $lessonP }
  if ($pyApiKey) { $env:PYTHON_API_KEY = $pyApiKey }
}

$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# -- 1. Python API ----------------------------------------------------------
Info ""
Info "[1/3] Python API :$pyPort"
if (Test-Port $pyPort) {
  Ok "      sudah berjalan - dilewati"
} else {
  $pyDir = Join-Path $root 'services\python'
  $pyExe = Join-Path $pyDir '.venv\Scripts\python.exe'
  if (-not (Test-Path $pyExe)) { Fail "      venv Python tidak ditemukan: $pyExe"; exit 1 }
  Export-CommonEnv
  Start-Process -FilePath $pyExe `
    -ArgumentList '-m', 'uvicorn', 'src.main:app', '--host', '127.0.0.1', '--port', "$pyPort" `
    -WorkingDirectory $pyDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'python.log') `
    -RedirectStandardError (Join-Path $logDir 'python.err.log')
  if (Wait-Health "http://127.0.0.1:$pyPort/health" 45) { Ok "      mulai - sehat" }
  else { Fail "      GAGAL sehat - cek logs\python.err.log" }
}

# -- 2. Node API ------------------------------------------------------------
Info ""
Info "[2/3] Node API :$nodePort"
if (Test-Port $nodePort) {
  Ok "      sudah berjalan - dilewati"
} else {
  $apiDir = Join-Path $root 'apps\api'
  if (-not (Test-Path (Join-Path $apiDir 'dist\index.js'))) {
    Warn "      dist belum ada - build (npm run build)..."
    Push-Location $apiDir; npm run build; Pop-Location
  }
  Export-CommonEnv
  $env:PORT = "$nodePort"
  Start-Process -FilePath 'node' -ArgumentList 'dist/index.js' `
    -WorkingDirectory $apiDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'node.log') `
    -RedirectStandardError (Join-Path $logDir 'node.err.log')
  if (Wait-Health "http://127.0.0.1:$nodePort/health" 30) { Ok "      mulai - sehat" }
  else { Fail "      GAGAL sehat - cek logs\node.err.log" }
}

# -- 3. Web Dashboard -------------------------------------------------------
Info ""
Info "[3/3] Web Dashboard :$webPort"
if (Test-Port $webPort) {
  Ok "      sudah berjalan - dilewati"
} else {
  $webDir = Join-Path $root 'apps\web'
  if (-not (Test-Path (Join-Path $webDir '.next\BUILD_ID'))) {
    Warn "      build web belum ada - build (1-2 menit)..."
    Push-Location $webDir; npm run build; Pop-Location
  }
  Export-CommonEnv
  $env:EA_API_URL = $eaApiUrl
  Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "npm run start -- -p $webPort" `
    -WorkingDirectory $webDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'web.log') `
    -RedirectStandardError (Join-Path $logDir 'web.err.log')
  if (Wait-Health "http://127.0.0.1:$webPort/" 60) { Ok "      mulai - sehat" }
  else { Fail "      GAGAL sehat - cek logs\web.err.log" }
}

# -- 4. Ringkasan -----------------------------------------------------------
Info ""
Info "=== Ringkasan ==="
$pyOk  = Wait-Health "http://127.0.0.1:$pyPort/health" 5
$apiOk = Wait-Health "http://127.0.0.1:$nodePort/health" 5
$webOk = Wait-Health "http://127.0.0.1:$webPort/" 5
if ($pyOk)  { Ok  "  [OK] Python API  :$pyPort" } else { Fail "  [X]  Python API  :$pyPort" }
if ($apiOk) { Ok  "  [OK] Node API    :$nodePort" } else { Fail "  [X]  Node API    :$nodePort" }
if ($webOk) { Ok  "  [OK] Web         :$webPort" } else { Fail "  [X]  Web         :$webPort" }
Info ""
Info "  Dashboard : http://localhost:$webPort"
Info "  Docs API  : http://127.0.0.1:$pyPort/docs"
Info "  Stop      : stop.bat"
Info "  Restart   : restart.bat"
Info ""
if ($webOk -and -not $NoBrowser) { Start-Process "http://localhost:$webPort" | Out-Null }
